"""
A self-hosted WebRTC room with a voice agent in it.

    python server.py            then open http://127.0.0.1:8080

No LiveKit, no Twilio, no account. aiortc is the peer on the server side, so
the browser negotiates a real PeerConnection against this process: mic audio
comes in over Opus, synthesized speech goes back out over Opus, and a
WebSocket alongside it carries captions and agent state for the UI.

    browser  --- offer/answer over POST /offer ---> aiortc
    browser  === mic audio (opus) ==============>  VAD -> whisper -> claude
    browser  <== agent audio (opus) ============   piper
    browser  <-- captions + state over /ws ------  orchestrator

Transcripts land in session.db so a conversation survives a refresh.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import fractions
import json
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import av
import numpy as np
import uvicorn
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# demos/.env is shared by every demo and must load before pipeline reads it.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from pipeline import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    Brain,
    Segmenter,
    Speaker,
    Transcriber,
    resample_i16,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-12s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("room")
logging.getLogger("aiortc").setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)

HERE = Path(__file__).parent
WEB = HERE / "web"
DB = HERE / "session.db"

OUT_RATE = 48_000                      # what WebRTC wants on the wire
OUT_FRAME = OUT_RATE * 20 // 1000      # 20 ms

# How often to re-decode the half-spoken utterance for the live caption.
# Fast enough that the words appear while they are still talking, slow
# enough that the partials never crowd out the real turn behind them.
PARTIAL_EVERY = 0.4

# How long someone has to keep talking over the agent before it counts as an
# interruption rather than the agent hearing itself. On headphones this could
# be near zero; on speakers the microphone picks up her own output, and a
# zero-length test makes her cut herself off mid-word. A real interruption
# lasts and is loud; echo that survives the browser's canceller is neither.
BARGE_FRAMES = 22                      # 440 ms of continuous speech
BARGE_RMS = 0.02

# The tail of the utterance a live caption is decoded from. Short, because
# the cost scales with it and a caption only needs the words being said now.
# The final decode still sees the whole utterance.
PARTIAL_WINDOW = 2.0


# ==========================================================================
# storage
# ==========================================================================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id TEXT PRIMARY KEY, started REAL, brain TEXT, voice TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS turns(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, at REAL,
        speaker TEXT, text TEXT, latency_ms INTEGER)""")
    conn.commit()
    return conn


# ==========================================================================
# outbound audio track
# ==========================================================================
class AgentVoice(MediaStreamTrack):
    """Streams whatever the TTS queue holds, silence otherwise.

    WebRTC pulls frames on a clock, so this must always return one on time.
    Underrunning produces clicks; returning silence does not.
    """

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._buf = bytearray()
        self._lock = asyncio.Lock()
        self._pts = 0
        self._t0: float | None = None
        self.speaking = False

    async def push(self, pcm48: bytes) -> None:
        async with self._lock:
            self._buf.extend(pcm48)

    async def flush(self) -> None:
        """Barge-in: drop everything not yet on the wire."""
        async with self._lock:
            self._buf.clear()

    async def pending(self) -> int:
        async with self._lock:
            return len(self._buf)

    async def recv(self) -> av.AudioFrame:
        if self._t0 is None:
            self._t0 = time.time()

        # Pace to the wall clock so we hand over exactly one 20 ms frame per 20 ms.
        target = self._t0 + (self._pts + OUT_FRAME) / OUT_RATE
        delay = target - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

        need = OUT_FRAME * 2  # bytes, int16 mono
        async with self._lock:
            if len(self._buf) >= need:
                chunk = bytes(self._buf[:need])
                del self._buf[:need]
                self.speaking = True
            elif self._buf:
                chunk = bytes(self._buf).ljust(need, b"\x00")
                self._buf.clear()
                self.speaking = True
            else:
                chunk = b"\x00" * need
                self.speaking = False

        frame = av.AudioFrame(format="s16", layout="mono", samples=OUT_FRAME)
        frame.planes[0].update(chunk)
        frame.sample_rate = OUT_RATE
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, OUT_RATE)
        self._pts += OUT_FRAME
        return frame


# ==========================================================================
# the conversation
# ==========================================================================
class Session:
    def __init__(self, app_state, sid: str) -> None:
        self.sid = sid
        self.state = app_state
        self.voice = AgentVoice()
        self.seg = Segmenter()
        self.brain = Brain()
        self.sockets: set[WebSocket] = set()
        self._tail = np.zeros(0, dtype=np.int16)
        self._busy = False
        self._speak_task: asyncio.Task | None = None
        self._partial_at = 0.0
        self._partial_busy = False
        self._partial_text = ""
        self._queued: np.ndarray | None = None
        self._cancel = False
        self._over = 0                 # frames of speech on top of the agent

        self.state.conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
            (sid, time.time(), self.brain.kind, self.state.speaker.engine),
        )
        self.state.conn.commit()

    # ---------- fan-out to the UI ----------
    async def emit(self, kind: str, **payload) -> None:
        msg = json.dumps({"type": kind, **payload})
        for ws in list(self.sockets):
            try:
                await ws.send_text(msg)
            except Exception:
                self.sockets.discard(ws)

    def record(self, speaker: str, text: str, latency: int | None = None) -> None:
        self.state.conn.execute(
            "INSERT INTO turns(session_id, at, speaker, text, latency_ms) VALUES (?,?,?,?,?)",
            (self.sid, time.time(), speaker, text, latency),
        )
        self.state.conn.commit()

    # ---------- inbound audio ----------
    async def on_track(self, track: MediaStreamTrack) -> None:
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        log.info("[%s] mic track attached", self.sid[:8])
        try:
            while True:
                frame = await track.recv()
                for r in resampler.resample(frame):
                    pcm = np.frombuffer(bytes(r.planes[0]), dtype=np.int16)
                    await self._consume(pcm)
        except (MediaStreamError, asyncio.CancelledError):
            log.info("[%s] mic track ended", self.sid[:8])

    async def _consume(self, pcm: np.ndarray) -> None:
        self._tail = np.concatenate([self._tail, pcm])
        while len(self._tail) >= FRAME_SAMPLES:
            frame, self._tail = self._tail[:FRAME_SAMPLES], self._tail[FRAME_SAMPLES:]

            # Barge-in, and the reason it is not a one-line check.
            #
            # It was first gated on `not self._busy`, which it can never
            # satisfy, so it never fired at all. Removing that gate made it
            # fire far too easily instead: on speakers the microphone hears
            # the agent, the VAD opens on her own voice, she cuts herself off
            # mid-sentence, and then she stays silent, because the cancel
            # flag she just set is only cleared at the end of a turn and the
            # greeting does not run inside one.
            #
            # So an interruption now has to look like one: continuously
            # voiced for BARGE_FRAMES and louder than BARGE_RMS.
            loud = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
            if self.voice.speaking and self.seg.active and loud > BARGE_RMS:
                self._over += 1
            else:
                self._over = 0

            if self._over == BARGE_FRAMES:
                await self.voice.flush()
                self._cancel = True
                self.seg.reset()
                log.info("[%s] barge-in", self.sid[:8])
                await self.emit("state", state="listening", note="barge-in")

            utterance = self.seg.push(frame)
            if utterance is not None:
                self._partial_text = ""
                if self._busy:
                    # Hold it, do not bin it. Dropping whatever someone says
                    # while the agent is still talking is most of what makes
                    # an agent feel like it is ignoring you, and it is silent:
                    # nothing in the log says a sentence was lost.
                    self._queued = utterance
                    log.info("[%s] queued %0.1fs spoken over the agent",
                             self.sid[:8], len(utterance) / SAMPLE_RATE)
                else:
                    asyncio.create_task(self._turn(utterance))
            elif self.seg.active and not self._busy:
                self._maybe_partial()

    # ---------- the user's words, while they are still speaking ----------
    def _maybe_partial(self) -> None:
        """Re-decode the utterance so far, at most one decode in flight.

        Whisper has no streaming mode: it transcribes a finished buffer. So
        a live caption means decoding the partial buffer again every so
        often and replacing the text. base.en runs at about 0.26x real time,
        which leaves plenty of headroom at this cadence, and the single
        in-flight flag means a slow decode simply skips a beat instead of
        queueing up behind itself and falling further behind.

        Nothing here can reach the model. The partial is a caption only; the
        turn still waits for the segmenter to close the utterance and decode
        it properly.
        """
        now = time.time()
        if self._busy or self._partial_busy or now - self._partial_at < PARTIAL_EVERY:
            return
        audio = self.seg.partial()
        if audio is None or len(audio) < SAMPLE_RATE * 0.5:
            return
        # Only ever the last few seconds. A partial re-decodes the whole
        # buffer, so on a long utterance the cost grows without limit: at
        # small.en's 0.57x real time a 20 s buffer takes 11 s, by which point
        # the decode is useless and the queue behind it is worse. The caption
        # only needs the words someone is saying now.
        audio = audio[-int(SAMPLE_RATE * PARTIAL_WINDOW):]
        self._partial_at = now
        self._partial_busy = True
        asyncio.create_task(self._run_partial(audio))

    async def _run_partial(self, audio: np.ndarray) -> None:
        try:
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, self.state.stt_fast, audio, True)
            # Discard it if the utterance closed while we were decoding: the
            # final transcript is already on its way and is better.
            if text and text != self._partial_text and self.seg.active and not self._busy:
                self._partial_text = text
                await self.emit("caption", who="user", text=text, final=False)
        except Exception as exc:
            log.debug("partial decode skipped: %s", exc)
        finally:
            self._partial_busy = False

    async def _stream(self, fn, *args):
        """Run a blocking generator on a thread, yield its items here."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        DONE = object()

        def pump():
            try:
                for item in fn(*args):
                    loop.call_soon_threadsafe(q.put_nowait, item)
            except Exception as exc:          # noqa: BLE001 - reported below
                loop.call_soon_threadsafe(q.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, DONE)

        loop.run_in_executor(None, pump)
        while True:
            item = await q.get()
            if item is DONE:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    # ---------- one exchange ----------
    async def _turn(self, audio: np.ndarray) -> None:
        self._busy = True
        # Always begin uncancelled. A flag left set by anything outside a
        # turn breaks out of the reply loop before the first sentence, and
        # the agent then never speaks again for the rest of the call.
        self._cancel = False
        self._over = 0
        loop = asyncio.get_running_loop()
        t0 = time.time()
        try:
            await self.emit("state", state="thinking")
            text = await loop.run_in_executor(None, self.state.stt, audio)
            if not text or len(text) < 2:
                await self.emit("state", state="listening")
                return

            heard_ms = int((time.time() - t0) * 1000)
            log.info("[%s] user: %s  (%d ms)", self.sid[:8], text, heard_ms)
            await self.emit("caption", who="user", text=text, final=True)
            self.record("user", text, heard_ms)

            spoken: list[str] = []
            first_audio_ms: int | None = None

            # The brain is a blocking generator doing network I/O. Iterated
            # straight from here it stalls the whole event loop between
            # chunks, which also stalls the 20 ms pacing of the outbound
            # audio track. Run it on a thread and take the events through a
            # queue, so captions, speech and the audio clock all keep moving.
            async for kind, payload in self._stream(self.brain.reply, text):
                if self._cancel:
                    log.info("[%s] cut off mid-reply", self.sid[:8])
                    break
                if kind == "text":
                    await self.emit("caption", who="agent", text=payload, final=False)
                    continue
                spoken.append(payload)
                clip = await loop.run_in_executor(None, self.state.speaker.say, payload)
                if clip is None:
                    continue
                if first_audio_ms is None:
                    first_audio_ms = int((time.time() - t0) * 1000)
                    await self.emit("state", state="speaking")
                # push is buffered and returns at once, so the next sentence
                # is already being synthesised while this one plays.
                await self.voice.push(resample_i16(clip.pcm, clip.sample_rate, OUT_RATE))

            reply = " ".join(spoken)
            log.info("[%s] aria: %s  (first audio %s ms)", self.sid[:8], reply, first_audio_ms)
            await self.emit("caption", who="agent", text=reply, final=True)
            self.record("agent", reply, first_audio_ms)

            while await self.voice.pending() > 0 and not self._cancel:
                await asyncio.sleep(0.1)
            await self.emit("state", state="listening")
        except Exception as exc:
            log.exception("turn failed: %s", exc)
            await self.emit("state", state="listening", note=str(exc))
        finally:
            self._busy = False
            self._cancel = False
            # Whatever was said over the top of that answer is the next turn.
            queued, self._queued = self._queued, None
            if queued is not None:
                asyncio.create_task(self._turn(queued))

    async def greet(self) -> None:
        # Held busy for the whole greeting. Without it an echo of the
        # greeting is taken for the user's first utterance and starts a turn
        # while she is still saying hello.
        self._busy = True
        try:
            await self._greet()
        finally:
            self._busy = False
            self._cancel = False
            self._over = 0
            self.seg.reset()
            self._queued = None        # anything heard during it was her

    async def _greet(self) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(0.8)
        await self.emit("state", state="speaking")
        text = await loop.run_in_executor(None, self.brain.greeting)
        await self.emit("caption", who="agent", text=text, final=True)
        self.record("agent", text)
        clip = await loop.run_in_executor(None, self.state.speaker.say, text)
        if clip:
            await self.voice.push(resample_i16(clip.pcm, clip.sample_rate, OUT_RATE))
        while await self.voice.pending() > 0:
            await asyncio.sleep(0.1)
        await self.emit("state", state="listening")


# ==========================================================================
# app
# ==========================================================================
class State:
    def __init__(self, model: str, voice: str | None) -> None:
        self.conn = db()
        self.stt = Transcriber(model)
        # A separate model for the live caption.
        #
        # Sharing one means the partial decode and the decode the reply
        # actually waits on queue behind each other inside CTranslate2, so a
        # caption nobody is waiting for delays the answer everybody is. A
        # second base.en costs about 150 MB and removes the contention. The
        # partial is throwaway text, so it always uses the fast model even
        # when the final one is set to something heavier.
        # tiny.en, not base.en. On the 2s window a live caption decodes,
        # tiny.en returned the same text in 0.52s against base.en's 0.97s.
        # A partial is replaced by the final decode a moment later, so it
        # can afford to be the rough one; what it cannot afford is to be
        # late, because a caption that trails your voice by a second is
        # worse than no caption.
        self.stt_fast = Transcriber("tiny.en")
        self.model_name = model
        # Probed once at boot. A health check used to construct a Brain,
        # which now means building a client and re-running provider
        # selection on every single request.
        probe = Brain()
        self.brain_kind, self.brain_model = probe.kind, probe.model
        self.speaker = Speaker(voice)
        self.sessions: dict[str, Session] = {}
        self.pcs: set[RTCPeerConnection] = set()
        self._warm()

    def _warm(self) -> None:
        """Both engines lazy-load on first call: whisper allocates its encoder,
        piper builds its ONNX session. Paying that here costs a second at boot
        instead of putting it in front of the user's first sentence."""
        t0 = time.time()
        try:
            self.stt(np.zeros(SAMPLE_RATE // 2, dtype=np.int16))
        except Exception as exc:
            log.warning("stt warmup: %s", exc)
        try:
            self.speaker.say("Ready.")
        except Exception as exc:
            log.warning("tts warmup: %s", exc)
        log.info("engines warm in %.1fs", time.time() - t0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    for pc in list(app.state.s.pcs):
        await pc.close()
    app.state.s.pcs.clear()


app = FastAPI(lifespan=lifespan)


# A browser will happily keep serving the app.js it fetched an hour ago, and
# StaticFiles's ETag does not stop a module that is already in the memory
# cache. During a demo that means editing the UI, restarting the server, and
# watching the old build come back with no error anywhere to explain it.
# Nothing here is worth caching: it is all local and it is all being changed.
@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
async def index():
    """index.html with the asset URLs stamped by their mtime.

    no-store tells a browser not to reuse what it has, but a module already
    resolved in an open tab can still be served from memory, and then an
    edited UI simply does not appear with nothing anywhere to explain it.
    A changing URL is not a request to revalidate, it is a different file.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for name in ("app.js",):
        stamp = int((WEB / name).stat().st_mtime)
        html = html.replace(f"/static/{name}", f"/static/{name}?v={stamp}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health():
    s: State = app.state.s
    return {"brain": s.brain_kind, "model": s.brain_model, "tts": s.speaker.engine,
            "stt": f"faster-whisper/{s.model_name}", "sessions": len(s.sessions)}


@app.get("/api/transcript/{sid}")
async def transcript(sid: str):
    s: State = app.state.s
    rows = s.conn.execute(
        "SELECT at, speaker, text, latency_ms FROM turns WHERE session_id=? ORDER BY id", (sid,)
    ).fetchall()
    return JSONResponse([{"at": r[0], "speaker": r[1], "text": r[2], "latency_ms": r[3]} for r in rows])


@app.post("/offer")
async def offer(request: Request):
    s: State = app.state.s
    body = await request.json()
    sid = body.get("session") or uuid.uuid4().hex

    session = Session(s, sid)
    s.sessions[sid] = session

    pc = RTCPeerConnection()
    s.pcs.add(pc)
    log.info("[%s] peer connecting", sid[:8])

    @pc.on("connectionstatechange")
    async def on_state():
        log.info("[%s] peer %s", sid[:8], pc.connectionState)
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            s.pcs.discard(pc)
            s.sessions.pop(sid, None)

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.create_task(session.on_track(track))

    pc.addTrack(session.voice)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    asyncio.create_task(session.greet())
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "session": sid}


@app.websocket("/ws/{sid}")
async def ws(socket: WebSocket, sid: str):
    await socket.accept()
    s: State = app.state.s
    for _ in range(40):                       # /offer and /ws race on connect
        if sid in s.sessions:
            break
        await asyncio.sleep(0.1)

    session = s.sessions.get(sid)
    if session is None:
        await socket.close()
        return

    session.sockets.add(socket)
    await socket.send_text(json.dumps({
        "type": "ready", "brain": session.brain.kind, "model": session.brain.model,
        "stt": f"faster-whisper/{s.model_name}", "tts": s.speaker.engine, "session": sid,
    }))
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        session.sockets.discard(socket)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    # base.en. I moved this to small.en on the theory it would read a real
    # accent better than base.en managed on my synthetic corpus, and that
    # was wrong in the way that matters. Timed on this machine, small.en
    # takes 3.69s to transcribe a 2.2s sentence: slower than real time. Every
    # turn opened with a four second hole and the live partials piled up
    # behind it until nothing moved. base.en returns the identical text for
    # the same clip in 0.76s.
    #
    # Accuracy was never the bottleneck here. The words were being lost to a
    # VAD that would not close the utterance and to a microphone level that
    # sat under every downstream threshold, both fixed above.
    ap.add_argument("--whisper", default=os.environ.get("WHISPER_MODEL") or "base.en",
                    help="tiny.en | base.en | small.en  (or WHISPER_MODEL in .env)")
    ap.add_argument("--voice", default=os.environ.get("PIPER_VOICE") or None,
                    help="path to a Piper .onnx voice  (or PIPER_VOICE in .env)")
    args = ap.parse_args()

    app.state.s = State(args.whisper, args.voice)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    print(f"\n  Room ready at http://{args.host}:{args.port}")
    st = app.state.s
    print(f"  stt faster-whisper/{args.whisper}   tts {st.speaker.engine}   brain {st.brain_model or st.brain_kind}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
