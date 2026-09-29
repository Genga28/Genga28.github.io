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
from fastapi.responses import FileResponse, JSONResponse
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

            # Barge-in: the moment the user starts talking over the agent, stop.
            if self.seg.active and self.voice.speaking and not self._busy:
                await self.voice.flush()
                await self.emit("state", state="listening", note="barge-in")

            utterance = self.seg.push(frame)
            if utterance is not None and not self._busy:
                asyncio.create_task(self._turn(utterance))

    # ---------- one exchange ----------
    async def _turn(self, audio: np.ndarray) -> None:
        self._busy = True
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

            for sentence in self.brain.reply(text):
                spoken.append(sentence)
                await self.emit("caption", who="agent", text=" ".join(spoken), final=False)
                clip = await loop.run_in_executor(None, self.state.speaker.say, sentence)
                if clip is None:
                    continue
                if first_audio_ms is None:
                    first_audio_ms = int((time.time() - t0) * 1000)
                    await self.emit("state", state="speaking")
                await self.voice.push(resample_i16(clip.pcm, clip.sample_rate, OUT_RATE))

            reply = " ".join(spoken)
            log.info("[%s] aria: %s  (first audio %s ms)", self.sid[:8], reply, first_audio_ms)
            await self.emit("caption", who="agent", text=reply, final=True)
            self.record("agent", reply, first_audio_ms)

            while await self.voice.pending() > 0:
                await asyncio.sleep(0.1)
            await self.emit("state", state="listening")
        except Exception as exc:
            log.exception("turn failed: %s", exc)
            await self.emit("state", state="listening", note=str(exc))
        finally:
            self._busy = False

    async def greet(self) -> None:
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


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health():
    s: State = app.state.s
    return {"brain": Brain().kind, "tts": s.speaker.engine, "stt": "faster-whisper", "sessions": len(s.sessions)}


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
        "type": "ready", "brain": session.brain.kind, "tts": s.speaker.engine, "session": sid,
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
    ap.add_argument("--whisper", default=os.environ.get("WHISPER_MODEL") or "base.en",
                    help="tiny.en | base.en | small.en  (or WHISPER_MODEL in .env)")
    ap.add_argument("--voice", default=os.environ.get("PIPER_VOICE") or None,
                    help="path to a Piper .onnx voice  (or PIPER_VOICE in .env)")
    args = ap.parse_args()

    app.state.s = State(args.whisper, args.voice)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    print(f"\n  Room ready at http://{args.host}:{args.port}")
    print(f"  stt faster-whisper/{args.whisper}   tts {app.state.s.speaker.engine}   brain {Brain().kind}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
