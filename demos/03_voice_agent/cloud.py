"""
Streaming speech services: Deepgram for hearing, Cartesia for speaking.

    DeepgramStream   16 kHz PCM in over a WebSocket, interim and final words out
                     as they are recognised. Deepgram does the endpointing too,
                     so "the user finished a thought" is decided by a model that
                     was trained to decide it, not by an energy threshold.
    CartesiaVoice    one sentence in, 48 kHz PCM out in chunks as they are
                     generated. Playback starts on the first chunk instead of
                     after the whole sentence has been synthesised.

Both are plain WebSocket / HTTP, no vendor SDK, and both are optional: with no
key, server.py keeps using the local faster-whisper and Piper path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import urlencode

import websockets

log = logging.getLogger("cloud")
logging.getLogger("websockets").setLevel(logging.WARNING)

# Words the recogniser should lean towards. Nova-3 keyterm prompting biases
# the decoder at inference time, which is the difference between "agentic AI"
# and "agent-to-gear AI" for a speaker it has never heard before.
KEYTERMS = [
    "Aria", "agentic AI", "voice agent", "LLM", "RAG", "RPA", "OCR",
    "WebRTC", "Claude", "Anthropic", "Gemini", "Deepgram", "Cartesia",
    "LangChain", "LangGraph", "n8n", "Python", "portfolio", "automation",
]


# ==========================================================================
# STT
# ==========================================================================
class DeepgramStream:
    """A long-lived streaming recogniser for one call.

    The caller `feed()`s 16 kHz int16 frames and gets two callbacks:

        on_interim(text)   the whole utterance so far, growing and correcting
        on_final(text)     the utterance is over, here is the settled text

    An utterance is closed by Deepgram's endpointing (`speech_final`), with
    `UtteranceEnd` as a backstop for the case where a trailing noise stops the
    first signal from ever firing. `ready` is False until the socket is up and
    again whenever it drops, so the caller can fall back to local STT for as
    long as this is unavailable rather than going deaf.
    """

    URL = "wss://api.deepgram.com/v1/listen"
    interims = True

    def __init__(
        self,
        on_interim: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
        api_key: str | None = None,
        model: str | None = None,
        on_fatal: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
        self.model = model or os.environ.get("DEEPGRAM_MODEL") or "nova-3"
        self.label = f"deepgram/{self.model}"
        self.on_interim = on_interim
        self.on_final = on_final
        self.on_fatal = on_fatal
        self.ready = False
        self.fatal = False                 # a rejected key will not heal itself
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=400)
        self._task: asyncio.Task | None = None
        self._parts: list[str] = []        # finalised pieces of the open utterance
        self._interim = ""

    # ---- lifecycle ----
    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self.ready = False
        try:
            self._audio.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def feed(self, pcm16: bytes) -> None:
        if not self.ready:
            return
        try:
            self._audio.put_nowait(pcm16)
        except asyncio.QueueFull:
            # Falling behind real time is worse than a gap: drop the oldest.
            try:
                self._audio.get_nowait()
                self._audio.put_nowait(pcm16)
            except Exception:
                pass

    def reset(self) -> None:
        """Forget a half-heard utterance (barge-in, or the agent talking over it)."""
        self._parts.clear()
        self._interim = ""

    # ---- the socket ----
    def _url(self) -> str:
        q = [
            ("model", self.model), ("language", "en"),
            ("encoding", "linear16"), ("sample_rate", "16000"), ("channels", "1"),
            ("interim_results", "true"),
            ("smart_format", "true"), ("punctuate", "true"),
            # 400 ms of silence closes an utterance. Lower cuts people off
            # mid-thought, higher is dead air before every answer.
            ("endpointing", "400"),
            ("utterance_end_ms", "1200"), ("vad_events", "true"),
        ]
        if self.model.startswith("nova-3"):
            q += [("keyterm", k) for k in KEYTERMS]
        return f"{self.URL}?{urlencode(q)}"

    async def _run(self) -> None:
        backoff = 0.5
        while True:
            try:
                async with websockets.connect(
                    self._url(),
                    additional_headers={"Authorization": f"Token {self.key}"},
                    open_timeout=8, ping_interval=None, max_size=None,
                ) as ws:
                    log.info("deepgram: connected (%s)", self.model)
                    self.ready, backoff = True, 0.5
                    # Drain audio queued while we were offline: it is stale.
                    while not self._audio.empty():
                        self._audio.get_nowait()
                    await asyncio.gather(self._send(ws), self._recv(ws))
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.InvalidStatus as exc:
                code = getattr(exc.response, "status_code", 0)
                if code in (401, 402, 403):
                    why = {401: "key rejected", 402: "account has no credits",
                           403: "key lacks permission"}[code]
                    log.error("deepgram: %s (HTTP %s), using local STT", why, code)
                    self.fatal = True
                    if self.on_fatal:
                        await self.on_fatal()
                    return
                log.warning("deepgram: connect failed (%s)", code)
            except Exception as exc:
                log.warning("deepgram: %s: %s", type(exc).__name__, exc)
            finally:
                self.ready = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5.0)

    async def _send(self, ws) -> None:
        last = time.time()
        while True:
            try:
                chunk = await asyncio.wait_for(self._audio.get(), timeout=3.0)
            except asyncio.TimeoutError:
                # Deepgram drops a silent socket after ~10 s.
                await ws.send(json.dumps({"type": "KeepAlive"}))
                continue
            if chunk is None:
                try:
                    await ws.send(json.dumps({"type": "CloseStream"}))
                except Exception:
                    pass
                return
            await ws.send(chunk)
            last = time.time()

    async def _recv(self, ws) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "Results":
                alt = (msg.get("channel", {}).get("alternatives") or [{}])[0]
                text = (alt.get("transcript") or "").strip()
                if msg.get("is_final"):
                    if text:
                        self._parts.append(text)
                    self._interim = ""
                else:
                    self._interim = text

                live = " ".join(self._parts + ([self._interim] if self._interim else []))
                if live and not msg.get("speech_final"):
                    await self.on_interim(live)
                if msg.get("speech_final"):
                    await self._flush()

            elif kind == "UtteranceEnd":
                await self._flush()

    async def _flush(self) -> None:
        text = " ".join(self._parts).strip()
        self._parts.clear()
        self._interim = ""
        if text:
            await self.on_final(text)


# ==========================================================================
# STT, Cartesia
# ==========================================================================
class CartesiaSTT:
    """Streaming recogniser on Cartesia, same shape as DeepgramStream so the
    session can use either. Two models behave differently:

    ink-2        streams the words as they are spoken, one fragment at a time,
                 and never says the utterance is over. The words are accumulated
                 here and shown live through `on_interim`; the session decides
                 when the speaker has stopped (its own VAD) and calls `flush()`,
                 which asks Cartesia for the trailing words and returns the text.
    ink-whisper  reports a whole utterance after a pause, with no interim words.
    """

    URL = "wss://api.cartesia.ai/stt/websocket"
    VERSION = "2025-04-16"

    def __init__(
        self,
        on_interim: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
        api_key: str | None = None,
        on_fatal: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.key = api_key or os.environ.get("CARTESIA_API_KEY", "")
        self.model = os.environ.get("CARTESIA_STT_MODEL") or "ink-2"
        self.label = f"cartesia/{self.model}"
        self.streaming = self.model.startswith("ink-2")
        self.interims = self.streaming
        self.text = ""                     # words heard so far (streaming only)
        self._flushed = asyncio.Event()
        self.on_interim = on_interim
        self.on_final = on_final
        self.on_fatal = on_fatal
        self.ready = False
        self.fatal = False
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=400)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self.ready = False
        try:
            self._audio.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def feed(self, pcm16: bytes) -> None:
        if not self.ready:
            return
        try:
            self._audio.put_nowait(pcm16)
        except asyncio.QueueFull:
            try:
                self._audio.get_nowait()
                self._audio.put_nowait(pcm16)
            except Exception:
                pass

    def reset(self) -> None:
        self.text = ""

    async def flush(self, timeout: float = 1.5) -> str:
        """Ask for the trailing words, then return and clear everything heard
        since the last flush."""
        if self.streaming and self.ready:
            self._flushed.clear()
            try:
                self._audio.put_nowait("finalize")
                await asyncio.wait_for(self._flushed.wait(), timeout)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                pass
        text, self.text = self.text.strip(), ""
        return text

    def _url(self) -> str:
        return f"{self.URL}?" + urlencode([
            ("model", self.model), ("language", "en"),
            ("encoding", "pcm_s16le"), ("sample_rate", "16000"),
            # How quiet counts as silence, and how long it must last before the
            # utterance is closed. Short on purpose: the session joins pieces itself, using the local
            # VAD, so this only needs to be fast.
            ("min_volume", "0.1"), ("max_silence_duration_secs", "0.5"),
        ])

    async def _run(self) -> None:
        backoff = 0.5
        while True:
            try:
                async with websockets.connect(
                    self._url(),
                    additional_headers={"X-API-Key": self.key,
                                        "Cartesia-Version": self.VERSION},
                    open_timeout=8, ping_interval=20, max_size=None,
                ) as ws:
                    log.info("cartesia stt: connected (%s)", self.model)
                    self.ready, backoff = True, 0.5
                    while not self._audio.empty():
                        self._audio.get_nowait()
                    await asyncio.gather(self._send(ws), self._recv(ws))
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.InvalidStatus as exc:
                code = getattr(exc.response, "status_code", 0)
                if code in (401, 402, 403):
                    log.error("cartesia stt: rejected (HTTP %s), using fallback STT", code)
                    self.fatal = True
                    if self.on_fatal:
                        await self.on_fatal()
                    return
                log.warning("cartesia stt: connect failed (%s)", code)
            except Exception as exc:
                log.warning("cartesia stt: %s: %s", type(exc).__name__, exc)
            finally:
                self.ready = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5.0)

    async def _send(self, ws) -> None:
        while True:
            chunk = await self._audio.get()
            if chunk is None:
                try:
                    await ws.send("done")
                except Exception:
                    pass
                return
            await ws.send(chunk)

    async def _recv(self, ws) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "transcript" and msg.get("is_final"):
                if self.streaming:
                    # A word or two at a time, each with its own leading space.
                    # Punctuation arrives alone and attaches to the word before.
                    frag = msg.get("text") or ""
                    if frag.strip():
                        self.text += frag if (frag[0] == " " or frag.strip()[0] not in ".,?!") else frag.strip()
                        await self.on_interim(self.text.strip())
                else:
                    text = (msg.get("text") or "").strip()
                    if text:
                        await self.on_final(text)
            elif kind == "flush_done":
                self._flushed.set()
            elif kind == "error":
                log.warning("cartesia stt: %s", msg.get("message") or msg)


# ==========================================================================
# TTS
# ==========================================================================
OUT_RATE = 48_000


class CartesiaVoice:
    """Sentence in, audio and per-word timing out, over one kept-open socket.

    `stream()` yields two kinds of event as they are generated:

        ("pcm", bytes)                     48 kHz s16 mono audio
        ("words", [(word, start, end)])    seconds from the start of this
                                           sentence's audio

    The word times are what lets a caption print each word at the moment it
    is spoken, instead of spreading a sentence evenly across its duration and
    being wrong on every word. A single connection is reused for every
    sentence, so only the first one pays for the TLS handshake.
    """

    URL = "wss://api.cartesia.ai/tts/websocket"
    VERSION = "2025-04-16"
    # Ariana - Kind Friend. Warm, American, conversational: close to what a
    # voice called Aria should sound like. Override with CARTESIA_VOICE.
    DEFAULT_VOICE = "ec1e269e-9ca0-402f-8a18-58e0e022355a"

    def __init__(self, api_key: str | None = None) -> None:
        self.key = api_key or os.environ.get("CARTESIA_API_KEY", "")
        self.voice = os.environ.get("CARTESIA_VOICE") or self.DEFAULT_VOICE
        self.model = os.environ.get("CARTESIA_MODEL") or "sonic-3"
        self.engine = f"cartesia:{self.model}"
        self.failures = 0
        self._ws = None
        self._lock = asyncio.Lock()        # one sentence on the socket at a time

    async def _connect(self):
        if self._ws is not None and self._ws.state.name == "OPEN":
            return self._ws
        self._ws = await websockets.connect(
            self.URL, max_size=None, open_timeout=6, ping_interval=20,
            additional_headers={"X-API-Key": self.key, "Cartesia-Version": self.VERSION},
        )
        return self._ws

    async def aclose(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def warm(self) -> None:
        """Open the socket now so the first sentence does not pay for it."""
        try:
            async with self._lock:
                await self._connect()
        except Exception as exc:
            log.warning("cartesia warmup: %s", exc)

    async def stream(self, text: str) -> AsyncIterator[tuple[str, object]]:
        import base64
        import uuid

        async with self._lock:
            try:
                ws = await self._connect()
                cid = uuid.uuid4().hex
                await ws.send(json.dumps({
                    "model_id": self.model, "transcript": text, "context_id": cid,
                    "voice": {"mode": "id", "id": self.voice}, "language": "en",
                    "output_format": {"container": "raw", "encoding": "pcm_s16le",
                                      "sample_rate": OUT_RATE},
                    "add_timestamps": True, "continue": False,
                }))
                carry = b""
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
                    if msg.get("context_id") not in (None, cid):
                        continue                    # a late message from a dropped sentence
                    kind = msg.get("type")
                    if kind == "chunk":
                        # Keep whole 16-bit samples: a split sample is a click.
                        data = carry + base64.b64decode(msg["data"])
                        cut = len(data) - (len(data) % 2)
                        carry = data[cut:]
                        if cut:
                            yield ("pcm", data[:cut])
                    elif kind == "timestamps":
                        w = msg["word_timestamps"]
                        yield ("words", list(zip(w["words"], w["start"], w["end"])))
                    elif kind == "done":
                        self.failures = 0
                        return
                    elif kind == "error":
                        raise RuntimeError(f"cartesia: {msg.get('error') or msg}")
            except GeneratorExit:
                # Abandoned mid-sentence (barge-in). The socket still has the
                # rest of that sentence queued, so it cannot be reused.
                await self.aclose()
                raise
            except Exception:
                self.failures += 1
                await self.aclose()
                raise


# ==========================================================================
# STT, second choice
# ==========================================================================
class GeminiTranscriber:
    """Final-utterance transcription with Gemini's audio input.

    Used when Deepgram is unavailable and a GOOGLE_API_KEY is set. It is a
    large multimodal model, so it copes with accents, quiet microphones and
    background noise far better than a small local Whisper, and it can be told
    to answer NO_SPEECH, which a Whisper decoder cannot: Whisper always writes
    something, and for noise that something is "Music" or "I'm going to go to
    the next one". Blocking call; run it on a thread.
    """

    # No vocabulary list. An earlier prompt named a few terms to expect, and on
    # quiet or short audio the model answered with that list as the transcript:
    # the user said "I'm working on an application" and Aria heard "Aria,
    # agentic AI, voice agent, LLM, RAG, Python, portfolio".
    PROMPT = (
        "Transcribe this audio exactly as spoken, in English. It may be very "
        "short, even one or two words such as a name or a greeting: transcribe "
        "those too. Output only the words you hear, nothing else. Answer "
        "NO_SPEECH only if there is no human voice at all."
    )

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from google import genai
        self.model = model or os.environ.get("GEMINI_STT_MODEL") or "gemini-2.5-flash"
        self._client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])

    def __call__(self, audio_i16) -> str:
        import io
        import wave

        import numpy as np
        from google.genai import types

        # Bring a quiet microphone up to a normal level. Gemini is much more
        # likely to give up on, or invent around, audio that is barely there.
        x = audio_i16.astype(np.float32)
        rms = float(np.sqrt(np.mean((x / 32768.0) ** 2))) if x.size else 0.0
        if 1e-5 < rms < 0.05:
            x = np.clip(x * min(0.05 / rms, 12.0), -32768, 32767)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16_000)
            w.writeframes(x.astype(np.int16).tobytes())
        r = self._client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="audio/wav"),
                      self.PROMPT],
            config=types.GenerateContentConfig(
                temperature=0, max_output_tokens=300,
                thinking_config=types.ThinkingConfig(thinking_budget=0)),
        )
        text = (r.text or "").strip()
        if "NO_SPEECH" in text.upper().replace(" ", "_"):
            return ""
        # A transcript that is only the words of our own prompt is the model
        # echoing instructions, not hearing speech. Raise so the caller falls
        # back to a different recogniser instead of acting on it.
        words = re.findall(r"[a-z']+", text.lower())
        if len(words) >= 3 and all(w in self._ECHO for w in words):
            raise ValueError(f"model echoed its prompt: {text!r}")
        return text

    _ECHO = {"transcribe", "this", "audio", "exactly", "as", "spoken", "in", "english",
             "output", "only", "the", "words", "you", "hear", "nothing", "else", "if",
             "there", "is", "no", "clear", "human", "speech", "exactly", "no_speech",
             "aria", "agentic", "ai", "voice", "agent", "llm", "rag", "python",
             "portfolio", "and", "terms", "that", "may", "appear"}
