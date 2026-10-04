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
import re
import fractions
import json
import logging
import sqlite3
import time
import uuid
import wave
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

from cloud import CartesiaSTT, CartesiaVoice, DeepgramStream, GeminiTranscriber
from pipeline import (
    FRAME_MS,
    FRAME_SAMPLES,
    SAMPLE_RATE,
    Brain,
    Segmenter,
    Speaker,
    Transcriber,
    resample_i16,
)

logging.basicConfig(level=(logging.DEBUG if os.environ.get("ARIA_DEBUG") else logging.INFO), format="%(asctime)s  %(name)-12s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("room")
logging.getLogger("aiortc").setLevel(logging.WARNING)
for noisy in ("httpx", "google_genai", "google_genai.models", "google.genai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("aioice").setLevel(logging.WARNING)

HERE = Path(__file__).parent
WEB = HERE / "web"
DB = HERE / "session.db"

OUT_RATE = 48_000                      # what WebRTC wants on the wire
OUT_FRAME = OUT_RATE * 20 // 1000      # 20 ms

# How often to re-decode the half-spoken utterance for the live caption.
# Fast enough that the words appear while they are still talking, slow
# enough that the partials never crowd out the real turn behind them.
PARTIAL_EVERY = 0.5

# How long someone has to keep talking over the agent before it counts as an
# interruption rather than the agent hearing itself. On headphones this could
# be near zero; on speakers the microphone picks up her own output, and a
# zero-length test makes her cut herself off mid-word. A real interruption
# lasts and is loud; echo that survives the browser's canceller is neither.
BARGE_FRAMES = 22                      # 440 ms of continuous speech
BARGE_RMS = 0.02

# Half-duplex: the microphone is ignored while the agent is speaking, and
# for a moment after she stops.
#
# On headphones this is unnecessary and barge-in is strictly better. On
# speakers it is the only thing that works. The browser's echo canceller is
# built for a remote talker and it does not fully suppress a local synthetic
# voice, so enough of Aria reaches the microphone to open the VAD, get
# transcribed, and come back as the user's next turn. She then answers
# herself, which is what produced a transcript reading "Alright, thanks for
# being with me" from a user who said nothing at all.
#
# The tail covers the room's reverberation plus the last frames still in the
# outbound buffer when `speaking` goes false.
DEAF_TAIL = 0.45

# The tail of the utterance a live caption is decoded from. Long enough that
# an ordinary sentence is captioned from its first word: a 2 s window made the
# caption show only the last couple of words and drop the rest, which reads as
# nothing being transcribed until the end. tiny.en decodes 8 s in about 0.6 s.
PARTIAL_WINDOW = 6.0

# How the call ends. From SOFT_TURNS exchanges Aria starts winding down: she
# answers what was just said, and closes with thanks and goodbye only when it
# feels natural. The room hangs up once she has actually said it. HARD_TURNS
# is the backstop so a chatty caller cannot keep it going for ever.
SOFT_TURNS = int(os.environ.get("ARIA_SOFT_TURNS") or 8)
HARD_TURNS = int(os.environ.get("ARIA_HARD_TURNS") or 10)

# How long the local VAD must have heard nothing before a turn starts. The
# recogniser can close an utterance on a pause shorter than a breath; this is
# what stops Aria answering half a sentence.
HOLD = 0.45

# A turn that trails off on one of these is a thought still being formed: "It's
# uh", "and", "because the". Answering it gets "Hmm?", so wait for more.
TRAILING = re.compile(
    r"\b(uh+|um+|er+|hmm+|and|but|so|because|like|or|the|a|an|to|of|with|"
    r"it'?s|i'?m|i|my|that|is|are|for|in|on)\b[\s.,…-]*$", re.I)
HESITATION_EXTRA = 1.5     # extra quiet required after such a turn

# A short message that says goodbye. "Thanks" alone is not one: people thank
# each other mid-conversation, and hanging up on it was cutting calls short.
# Long messages that merely contain a farewell word are not goodbyes either.
CLOSING = re.compile(
    r"\b(bye|goodbye|good night|see you|see ya|talk (to you )?later|"
    r"catch you later|take care|gotta go|have to go)\b", re.I)

# After Aria says her goodbye she waits this long for theirs before hanging up.
BYE_WAIT = 9.0


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
def _agreed(prev: list[str], cur: list[str]) -> int:
    """How many leading words two successive decodes share, ignoring case and
    punctuation."""
    norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())
    n = 0
    for x, y in zip(prev, cur):
        if norm(x) != norm(y):
            break
        n += 1
    return n


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
        self._deaf_until = 0.0
        self._queued_text = ""         # cloud STT equivalent of _queued
        self._pending = ""             # finals waiting for the user to stop
        self._pending_at = 0.0
        self._last_voice = 0.0         # last time the local VAD heard speech
        self._turns = 0                # completed exchanges, for the wrap-up
        self._pending_audio: list[np.ndarray] = []   # local-STT utterances waiting
        self._cur_audio: np.ndarray | None = None    # the turn in flight
        self._cur_text = ""
        self._merge = False            # the turn in flight is being folded into a new one
        self._greeting = False
        self._audio_started = False    # has the current reply begun to play
        self._last_live = ""           # last live caption, for the log
        self._awaiting_bye = 0.0       # when Aria said goodbye and is waiting for theirs
        self._held_text = ""           # a dangling thought we are waiting on
        self._hold_until = 0.0
        self._prev_live: list[str] = []   # previous decode, for agreement
        self._word_tasks: list[asyncio.Task] = []

        # Streaming recogniser. Created inside the running loop. None when
        # there is no key, in which case the local VAD + whisper path below
        # does everything.
        self.dg: CartesiaSTT | DeepgramStream | None = None
        if self.state.stt_kind == "cartesia":
            self.dg = CartesiaSTT(self._on_interim, self._on_final, on_fatal=self._announce)
        elif self.state.stt_kind == "deepgram":
            self.dg = DeepgramStream(self._on_interim, self._on_final, on_fatal=self._announce)
        if self.dg:
            self.dg.start()

        self.state.conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)",
            (sid, time.time(), self.brain.kind, self.state.speaker.engine),
        )
        self.state.conn.commit()

    async def _announce(self) -> None:
        """Tell the UI what is actually doing the work, once that is known."""
        await self.emit("ready", brain=self.brain.kind, model=self.brain.model,
                        stt=self.stt_label, tts=self.state.tts_label, session=self.sid)

    async def close(self) -> None:
        if self.dg:
            await self.dg.close()

    @property
    def cloud_stt(self) -> bool:
        return bool(self.dg and self.dg.ready)

    @property
    def stt_label(self) -> str:
        if self.dg and not self.dg.fatal:
            return self.dg.label
        if self.state.gemini_stt is not None:
            return f"gemini/{self.state.gemini_stt.model}"
        return f"faster-whisper/{self.state.model_name}"

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

            # Half-duplex gate. Nothing the microphone hears while she is
            # talking is trusted, because most of it is her.
            now = time.time()
            if self.voice.speaking:
                self._deaf_until = now + DEAF_TAIL
            if not self.state.duplex and now < self._deaf_until:
                if self.seg.active:
                    self.seg.reset()
                if self.dg:
                    self.dg.reset()
                    # Keep the stream fed with silence, not paused: it closes
                    # a socket that goes quiet, and it needs to see the
                    # silence to know the last thing said was finished.
                    self.dg.feed(bytes(len(frame) * 2))
                continue

            # The recogniser hears everything that passes the gate above.
            # Local VAD still runs below: it drives barge-in, and it is the
            # whole recogniser when Deepgram is unavailable.
            if self.dg:
                self.dg.feed(frame.tobytes())

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
            if (self.state.duplex and self.voice.speaking
                    and self.seg.active and loud > BARGE_RMS):
                self._over += 1
            else:
                self._over = 0

            if self._over == BARGE_FRAMES:
                await self.voice.flush()
                self._cancel = True
                self._stop_words()
                self.seg.reset()
                log.info("[%s] barge-in", self.sid[:8])
                await self.emit("state", state="listening", note="barge-in")

            utterance = self.seg.push(frame)
            if self.seg.active or utterance is not None:
                self._last_voice = now
            if utterance is not None and not self.cloud_stt:
                # Held, not started. A pause between two clauses closes an
                # utterance, and answering each clause on its own is what
                # made the conversation a pile of fragments.
                self._partial_text = ""
                self._prev_live = []
                self._pending_audio.append(utterance)
                self._pending_at = time.time()
            if self._pending or self._pending_audio:
                self._try_start()
            if (utterance is None and self.seg.active and not self._busy
                    and (not self.cloud_stt or not self.dg.interims)):
                self._maybe_partial()

    # ---------- streaming recogniser callbacks ----------
    async def _on_interim(self, text: str) -> None:
        if self._busy and not self.state.duplex:
            return
        if getattr(self.dg, "streaming", False):
            # Words are arriving live. They are also the turn: when the VAD
            # says the speaker has stopped, this is what gets answered.
            self._pending = text
            self._pending_at = time.time()
        await self.emit("caption", who="user", text=text, final=False)

    async def _on_final(self, text: str) -> None:
        text = re.sub(r"^[\s\-–—…]+", "", text)   # stray leading dash
        if len(text) < 2:
            return
        self._pending = f"{self._pending} {text}".strip()
        self._pending_at = time.time()
        self._try_start()

    def _try_start(self) -> None:
        """Begin a turn for what has been heard, once the user has stopped.

        Both recognisers close an utterance on a short pause, and people pause
        that long between two clauses. So whatever arrives is held until the
        local VAD has heard nothing for HOLD seconds, and the pieces are joined
        into one turn. The 4 s cap stops a stuck VAD holding a turn for ever.

        If she is still thinking when the user carries on (no audio of hers has
        played yet), the turn in flight is abandoned and its words are folded
        into the new one, instead of her answering half a sentence and then
        answering the rest separately.
        """
        if not (self._pending or self._pending_audio):
            return
        need = HOLD
        if self._pending and TRAILING.search(self._pending):
            need += HESITATION_EXTRA
        quiet = time.time() - self._last_voice >= need
        if (self.seg.active or not quiet or time.time() < self._hold_until)                 and time.time() - self._pending_at < 4.0:
            return
        log.debug("[%s] start check: pending=%r need=%.2f quiet_for=%.2f active=%s busy=%s",
                  self.sid[:8], self._pending, need, time.time() - self._last_voice,
                  self.seg.active, self._busy)
        if self._busy:
            if not (self._greeting or self._audio_started or self._cancel):
                log.info("[%s] more speech while thinking, merging", self.sid[:8])
                self._merge = True
                self._cancel = True
            return                     # her turn's `finally` relaunches
        self._launch(merge=False)

    def _launch(self, merge: bool) -> None:
        """Start a turn from everything pending. `merge` prepends the turn that
        was just abandoned."""
        if self._pending_audio:
            parts = self._pending_audio
            if merge and self._cur_audio is not None:
                parts = [self._cur_audio] + parts
            gap = np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.int16)
            audio = parts[0]
            for part in parts[1:]:
                audio = np.concatenate([audio, gap, part])
            self._pending_audio = []
            self._busy = True
            asyncio.create_task(self._turn(audio))
        elif self._pending:
            text, self._pending = self._pending, ""
            if merge and self._cur_text:
                text = f"{self._cur_text} {text}"
            self._busy = True
            if getattr(self.dg, "streaming", False):
                asyncio.create_task(self._flush_then_turn(text))
            else:
                asyncio.create_task(self._turn(None, text))

    async def _flush_then_turn(self, heard: str) -> None:
        """The last word or two are still in the recogniser: collect them."""
        tail = await self.dg.flush()
        # `tail` is everything since the last flush, so it already contains
        # `heard` and whatever followed it.
        text = tail if len(tail) >= len(heard) else heard
        # The recogniser's words trail the speech by a second or two, so the
        # check in _try_start sees a stale "It'" and finds nothing to wait for.
        # Only now is the whole of what was said known: if it still dangles
        # ("It's uh"), give the rest of the thought a moment to arrive.
        if TRAILING.search(text) and text != self._held_text:
            self._held_text = text
            self._hold_until = time.time() + HESITATION_EXTRA
            self.dg.text = text
            self._pending, self._pending_at = text, time.time()
            self._busy = False
            return
        self._held_text = ""
        await self._turn(None, text)

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
            # Only words two decodes in a row agree on reach the screen. One
            # decode of half a sentence is a guess ("Losa?", "They running.")
            # and the line then visibly rewrites itself. A word that survives
            # the next decode of a longer buffer is much more likely real.
            words = text.split()
            keep = _agreed(self._prev_live, words)
            self._prev_live = words
            if not keep and len(audio) >= SAMPLE_RATE * PARTIAL_WINDOW:
                keep = len(words)      # the window has slid; nothing to compare
            shown = " ".join(words[:keep])
            if shown and shown != self._partial_text and not self._busy:
                self._partial_text = shown
                self._last_live = shown
                log.info("[%s] live  : %s", self.sid[:8], shown)
                await self.emit("caption", who="user", text=shown, final=False)
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
    async def _synth(self, sentence: str):
        """Yield 48 kHz PCM for one sentence as it is generated.

        Cartesia first, streaming. If it fails before producing any audio the
        sentence is spoken by the local engine instead, so a dead network
        costs voice quality, not the conversation.
        """
        loop = asyncio.get_running_loop()
        cv = self.state.cartesia
        produced = False
        if cv is not None and cv.failures < 3:
            try:
                gen = cv.stream(sentence)
                try:
                    async for event in gen:
                        produced = produced or event[0] == "pcm"
                        yield event
                finally:
                    await gen.aclose()     # frees the socket on barge-in
                return
            except Exception as exc:
                log.warning("[%s] cartesia failed (%s)", self.sid[:8], exc)
                if produced:
                    return
        clip = await loop.run_in_executor(None, self.state.speaker.say, sentence)
        if clip is not None:
            yield ("pcm", resample_i16(clip.pcm, clip.sample_rate, OUT_RATE))

    async def _show_words(self, shown: str, words: list, lo: int, hi: int,
                          base: float) -> None:
        """Print each word at the moment it is spoken.

        `words` is the sentence's word list with each word's start time in
        seconds, `base` is when that sentence's audio reaches the speaker.
        Everything said earlier in the reply is already on screen as `shown`,
        so each event is the reply so far plus the sentence up to this word.
        """
        for i in range(lo, hi):
            await asyncio.sleep(max(0.0, base + words[i][1] - time.time()))
            if self._cancel:
                return
            upto = " ".join(w for w, _, _ in words[: i + 1])
            await self.emit("caption", who="agent", text=f"{shown} {upto}".strip(),
                            final=False)

    def _stop_words(self) -> None:
        for t in self._word_tasks:
            t.cancel()
        self._word_tasks.clear()

    async def _turn(self, audio: np.ndarray | None, said: str | None = None) -> None:
        self._busy = True
        # Always begin uncancelled. A flag left set by anything outside a
        # turn breaks out of the reply loop before the first sentence, and
        # the agent then never speaks again for the rest of the call.
        self._cancel = False
        self._merge = False
        self._audio_started = False
        self._cur_audio, self._cur_text = audio, said or ""
        self._over = 0
        loop = asyncio.get_running_loop()
        t0 = time.time()
        try:
            await self.emit("state", state="thinking")
            if said is not None:
                text = said                       # already transcribed, live
            else:
                text = await loop.run_in_executor(None, self.state.transcribe, audio)
                self._cur_text = text
            if self._cancel:
                return                            # folded into the next turn
            if not text or len(text) < 2:
                # Saved as well: a clip that produced nothing is exactly the
                # one worth listening back to.
                if audio is not None:
                    self.state.dump(audio, "(nothing recognised)")
                await self.emit("state", state="listening")
                return

            heard_ms = int((time.time() - t0) * 1000)
            source = self.stt_label if said is not None else (
                f"gemini/{self.state.gemini_stt.model}" if self.state.gemini_stt
                else f"whisper/{self.state.model_name}")
            if self._last_live and self._last_live != text:
                log.info("[%s] live  : %s   (shown while speaking)", self.sid[:8], self._last_live)
            self._last_live = ""
            log.info("[%s] heard : %s   [%s, %d ms]", self.sid[:8], text, source, heard_ms)
            if audio is not None:
                self.state.dump(audio, text)
            await self.emit("caption", who="user", text=text, final=True)
            self.record("user", text, heard_ms)

            spoken: list[str] = []
            first_audio_ms: int | None = None

            short = len(text.split()) <= 8
            nth = self._turns + 1
            replying_to_goodbye, self._awaiting_bye = bool(self._awaiting_bye), 0.0
            wrap = ("goodbye" if replying_to_goodbye or (short and CLOSING.search(text)) else
                    "hard" if nth >= HARD_TURNS else
                    "soft" if nth >= SOFT_TURNS else None)
            ended = wrap in ("goodbye", "hard")      # these always end the call
            if wrap:
                log.info("[%s] wrapping up (%s)", self.sid[:8], wrap)

            # Speech synthesis runs in its own task. It used to be awaited
            # inline, so while Piper was busy with one sentence every caption
            # chunk behind it sat in the queue, and the agent's text arrived
            # in lumps long after the model had written it.
            sentences: asyncio.Queue = asyncio.Queue()

            async def speak() -> None:
                nonlocal first_audio_ms
                shown = ""
                while True:
                    sentence = await sentences.get()
                    if sentence is None:
                        return
                    if self._cancel:
                        continue
                    base, total = None, 0
                    sw: list = []          # this sentence's words, as timed
                    done = 0               # how many of them are scheduled

                    def schedule(prefix: str) -> None:
                        nonlocal done
                        if base is None or done >= len(sw):
                            return
                        self._word_tasks.append(asyncio.create_task(
                            self._show_words(prefix, sw, done, len(sw), base)))
                        done = len(sw)

                    async for kind, data in self._synth(sentence):
                        if self._cancel:
                            break
                        if kind == "words":
                            sw += data
                            schedule(shown)
                            continue
                        if first_audio_ms is None:
                            first_audio_ms = int((time.time() - t0) * 1000)
                            self._audio_started = True
                            await self.emit("state", state="speaking")
                        if base is None:
                            # When this sentence's first sample reaches the
                            # speaker: now, plus whatever is still queued.
                            base = time.time() + await self.voice.pending() / (OUT_RATE * 2)
                        await self.voice.push(data)
                        total += len(data)
                        schedule(shown)    # timings that beat the first audio
                    if not total or self._cancel:
                        continue
                    if not sw:
                        # No word timings (local voice): spread it evenly.
                        self._word_tasks.append(asyncio.create_task(self._reveal(
                            (shown + " " + sentence).strip(),
                            base - time.time(), total / (OUT_RATE * 2))))
                    shown = (shown + " " + sentence).strip()

            speaker_task = asyncio.create_task(speak())

            # The brain is a blocking generator doing network I/O. Iterated
            # straight from here it stalls the whole event loop between
            # chunks, which also stalls the 20 ms pacing of the outbound
            # audio track. Run it on a thread and take the events through a
            # queue, so captions, speech and the audio clock all keep moving.
            async for kind, payload in self._stream(self.brain.reply, text, False, wrap):
                if self._cancel:
                    log.info("[%s] cut off mid-reply", self.sid[:8])
                    break
                if kind == "say":
                    spoken.append(payload)
                    await sentences.put(payload)
                elif kind == "end":
                    ended = True
            await sentences.put(None)
            await speaker_task
            if self._cancel:
                return

            reply = " ".join(spoken)
            log.info("[%s] aria  : %s   [first audio %s ms]", self.sid[:8], reply, first_audio_ms)
            self.record("agent", reply, first_audio_ms)

            while await self.voice.pending() > 0 and not self._cancel:
                await asyncio.sleep(0.1)
            if len(text.split()) >= 3 or wrap:
                self._turns += 1                 # fragments do not count
            if ended and not self._cancel:
                if wrap == "goodbye":
                    # They said goodbye (or answered hers) and she has replied.
                    await asyncio.sleep(1.2)
                    log.info("[%s] call over (goodbye)", self.sid[:8])
                    await self.emit("end", reason="goodbye")
                    return
                # She has said goodbye first. Wait for theirs.
                self._awaiting_bye = time.time()
                log.info("[%s] said goodbye, waiting for theirs", self.sid[:8])
                asyncio.create_task(self._bye_timeout(self._awaiting_bye))
            await self.emit("state", state="listening")
        except Exception as exc:
            log.exception("turn failed: %s", exc)
            await self.emit("state", state="listening", note=str(exc))
        finally:
            merging, self._merge = self._merge, False
            if merging and self.brain.history and self.brain.history[-1]["role"] == "user":
                self.brain.history.pop()         # the abandoned question, re-asked merged
            self._busy = False
            self._cancel = False
            self._stop_words()
            # Whatever was said while she was busy is the next turn.
            if self._pending or self._pending_audio:
                self._launch(merge=merging)

    async def _bye_timeout(self, stamp: float) -> None:
        """Hang up if they never answer her goodbye. Anything they do say
        cancels this by taking `_awaiting_bye` for their own turn."""
        for _ in range(3):
            await asyncio.sleep(BYE_WAIT / 3)
            if self._awaiting_bye != stamp:
                return                       # they answered
        while self._busy or self.seg.active:  # mid-sentence: give them a moment
            await asyncio.sleep(0.5)
            if self._awaiting_bye != stamp:
                return
        log.info("[%s] call over (no reply to goodbye)", self.sid[:8])
        await self.emit("end", reason="timeout")

    async def _reveal(self, text: str, delay: float, dur: float) -> None:
        """Release a caption when its audio starts, spread across its length."""
        await asyncio.sleep(max(0.0, delay))
        if self._cancel:
            return
        await self.emit("caption", who="agent", text=text, final=False, dur=round(dur, 2))

    async def greet(self) -> None:
        # Held busy for the whole greeting. Without it an echo of the
        # greeting is taken for the user's first utterance and starts a turn
        # while she is still saying hello.
        self._busy = True
        self._greeting = True
        try:
            await self._greet()
        finally:
            self._busy = False
            self._greeting = False
            self._cancel = False
            self._over = 0
            self.seg.reset()
            self._pending_audio = []   # anything heard during it was her
            self._pending = ""
            if self.dg:
                self.dg.reset()

    async def _greet(self) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(0.8)
        await self.emit("state", state="speaking")
        text = await loop.run_in_executor(None, self.brain.greeting)
        self.record("agent", text)
        base, words, done, timed = None, [], 0, False
        async for kind, data in self._synth(text):
            if kind == "words":
                words += data
                timed = True
            else:
                if base is None:
                    base = time.time() + await self.voice.pending() / (OUT_RATE * 2)
                await self.voice.push(data)
            if base is not None and done < len(words):
                self._word_tasks.append(asyncio.create_task(
                    self._show_words("", words, done, len(words), base)))
                done = len(words)
        if not timed:                          # local voice: no word times
            await self.emit("caption", who="agent", text=text, final=True)
        while await self.voice.pending() > 0:
            await asyncio.sleep(0.1)
        await self.emit("state", state="listening")


# ==========================================================================
# app
# ==========================================================================
class State:
    def __init__(self, model: str, voice: str | None, duplex: bool = False,
                 save_audio: bool = False) -> None:
        self.conn = db()
        self.stt = Transcriber(model, threads=8)
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
        self.stt_fast = Transcriber(os.environ.get("ARIA_LIVE_MODEL") or "base.en", threads=4)
        # Cloud speech, each independently optional. The local models stay
        # loaded either way: they are the fallback when a key is missing, out
        # of credit, or the network is down.
        # Which streaming recogniser to try first: Cartesia, then Deepgram.
        # ARIA_STT=cartesia|deepgram|gemini|local overrides.
        want = (os.environ.get("ARIA_STT") or "").lower()
        has = {"cartesia": bool(os.environ.get("CARTESIA_API_KEY")),
               "deepgram": bool(os.environ.get("DEEPGRAM_API_KEY"))}
        # Cartesia's streaming recogniser by default. Measured on six clips of
        # the real microphone: 0.3-0.4 s per clip against 2.5-3.3 s for Gemini
        # audio, with the same or better text ("It's AI" where Gemini heard
        # "It's a"), and Gemini refused outright on one- and two-word clips.
        # Gemini stays as the fallback if Cartesia is unreachable.
        self.stt_kind = (want if has.get(want) else
                         "" if want in ("gemini", "local") else
                         next((k for k in ("cartesia", "deepgram") if has[k]), ""))
        self.cartesia = CartesiaVoice() if os.environ.get("CARTESIA_API_KEY") else None
        # Final transcripts when Deepgram is not doing the job: Gemini audio
        # if there is a key (set ARIA_STT=local to force Whisper), else Whisper.
        self.gemini_stt = None
        if os.environ.get("GOOGLE_API_KEY") and (os.environ.get("ARIA_STT") or "").lower() == "gemini":
            try:
                self.gemini_stt = GeminiTranscriber()
            except Exception as exc:
                log.warning("gemini stt unavailable (%s), using whisper", exc)
        self.model_name = model
        self.duplex = duplex
        self.save_audio = save_audio
        self.clip_no = 0
        if save_audio:
            (HERE / "output" / "utterances").mkdir(parents=True, exist_ok=True)
            log.info("saving every utterance to %s", HERE / "output" / "utterances")

        # Probed once at boot. A health check used to construct a Brain,
        # which now means building a client and re-running provider
        # selection on every single request.
        probe = Brain()
        self.brain_kind, self.brain_model = probe.kind, probe.model
        self.speaker = Speaker(voice)
        self.tts_label = self.cartesia.engine if self.cartesia else self.speaker.engine
        self.sessions: dict[str, Session] = {}
        self.pcs: set[RTCPeerConnection] = set()
        self._warm()

    def transcribe(self, audio: np.ndarray) -> str:
        """Gemini first, Whisper if it errors. An empty answer from Gemini
        means there was no speech and is believed, not retried."""
        if self.gemini_stt is not None:
            try:
                text = self.gemini_stt(audio)
                if text or not self._sounds_like_speech(audio):
                    return text
                # Gemini said "no speech" about a clip the VAD is sure is a
                # voice. That happens on one- and two-word utterances ("I'm
                # Aria", "It is fine"), and trusting it was losing four
                # answers in five. A second opinion is cheap.
                log.info("gemini heard nothing but the VAD hears speech, "
                         "asking whisper")
            except Exception as exc:
                log.warning("gemini stt failed (%s), using whisper", exc)
        return self.stt(audio)

    def _sounds_like_speech(self, audio: np.ndarray) -> bool:
        """Silero's verdict on a finished clip: at least 0.4 s of confident
        speech. Independent of the recogniser being second-guessed."""
        try:
            from pipeline import Silero
            vad = Silero()
            hits = sum(vad(audio[i:i + FRAME_SAMPLES]) >= 0.6
                       for i in range(0, len(audio) - FRAME_SAMPLES, FRAME_SAMPLES))
            return hits * FRAME_MS / 1000 >= 0.4
        except Exception:
            return False

    def dump(self, audio: np.ndarray, text: str) -> None:
        """Write the exact audio the recogniser was given, and what it said.

        Transcription being wrong has two very different causes and they are
        not distinguishable from the transcript alone: the audio reaching
        whisper may be clipped, quiet, truncated by the segmenter or full of
        the agent's own voice, or the audio may be fine and the model simply
        wrong. Listening to the clip settles it in seconds.
        """
        if not self.save_audio:
            return
        self.clip_no += 1
        base = HERE / "output" / "utterances" / f"{self.clip_no:03d}"
        try:
            with wave.open(str(base.with_suffix(".wav")), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(audio.tobytes())
            peak = float(np.max(np.abs(audio)) / 32768.0)
            rms = float(np.sqrt(np.mean((audio / 32768.0) ** 2)))
            base.with_suffix(".txt").write_text(
                f"{len(audio) / SAMPLE_RATE:.2f}s  peak {peak:.3f}  rms {rms:.4f}"
                f"{'  CLIPPED' if peak > 0.98 else ''}\n{text}\n", encoding="utf-8")
            log.info("  saved %s  %.2fs peak %.2f rms %.4f", base.name,
                     len(audio) / SAMPLE_RATE, peak, rms)
        except Exception as exc:
            log.warning("could not save clip: %s", exc)
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
    if app.state.s.cartesia:
        await app.state.s.cartesia.warm()
    yield
    for session in list(app.state.s.sessions.values()):
        await session.close()
    if app.state.s.cartesia:
        await app.state.s.cartesia.aclose()
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
    return {"brain": s.brain_kind, "model": s.brain_model, "tts": s.tts_label,
            "stt": s.stt_kind if s.stt_kind else (
                f"gemini/{s.gemini_stt.model}" if s.gemini_stt else f"faster-whisper/{s.model_name}"),
            "sessions": len(s.sessions)}


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
            gone = s.sessions.pop(sid, None)
            if gone:
                await gone.close()

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
        "stt": session.stt_label, "tts": s.tts_label, "session": sid,
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
    # small.en by default: base.en mangles accented English badly, and on this
    # 12-core machine small.en runs at about 0.3x real time with 8 threads. The
    # 3.69 s figure below was measured with the library's default 4 threads
    # while a second model fought it for them.
    #
    # History: I moved this to small.en on the theory it would read a real
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
    ap.add_argument("--whisper", default=os.environ.get("WHISPER_MODEL") or "small.en",
                    help="tiny.en | base.en | small.en  (or WHISPER_MODEL in .env)")
    ap.add_argument("--save-audio", action="store_true",
                    help="write every utterance to output/utterances as a wav "
                         "with its transcript, peak and rms. The way to tell a "
                         "bad microphone from a bad recognition")
    ap.add_argument("--duplex", action="store_true",
                    help="keep the microphone live while the agent speaks, so you "
                         "can interrupt her. Wear headphones: on speakers she hears "
                         "herself and answers it")
    ap.add_argument("--voice", default=os.environ.get("PIPER_VOICE") or None,
                    help="path to a Piper .onnx voice  (or PIPER_VOICE in .env)")
    args = ap.parse_args()

    app.state.s = State(args.whisper, args.voice, duplex=args.duplex,
                        save_audio=args.save_audio)
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    print(f"\n  Room ready at http://{args.host}:{args.port}")
    st = app.state.s
    local = f"gemini/{st.gemini_stt.model}" if st.gemini_stt else f"faster-whisper/{args.whisper}"
    stt = f"{st.stt_kind}, then {local}" if st.stt_kind else local
    print(f"  stt {stt}   tts {st.tts_label}   brain {st.brain_model or st.brain_kind}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
