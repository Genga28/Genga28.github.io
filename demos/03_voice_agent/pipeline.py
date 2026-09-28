"""
The agent's brain and voice. Everything here runs on this machine: no cloud
STT, no cloud TTS, no account, no key except the optional Claude one.

    VAD      webrtcvad          frames -> utterance boundaries
    STT      faster-whisper     utterance -> text            (open source, local)
    LLM      Claude             text -> reply, streamed by sentence
    TTS      Piper              sentence -> 16-bit PCM       (open source, local)

Every stage is swappable and each one degrades to something that still runs:
no Piper voice falls back to the OS speech engine, no Claude key falls back to
a scripted host that can still hold a short conversation.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

log = logging.getLogger("pipeline")

HERE = Path(__file__).parent
VOICES = HERE / "voices"

SAMPLE_RATE = 16_000          # what Whisper and webrtcvad both want
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


# ==========================================================================
# VAD
# ==========================================================================
class Segmenter:
    """Turns a stream of 20 ms frames into complete utterances.

    Speech starts after `start_frames` voiced frames in a row and ends after
    `end_frames` unvoiced ones, which is what stops the agent cutting in on a
    pause mid-sentence. A hard cap keeps one long monologue from starving the
    rest of the pipeline.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        start_frames: int = 5,       # 100 ms of speech to open
        end_frames: int = 24,        # 480 ms of silence to close: snappy but
                                     # still survives a mid-sentence breath
        max_ms: int = 20_000,
    ) -> None:
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(aggressiveness)
        except Exception:
            log.warning("webrtcvad unavailable, falling back to an energy gate")
            self._vad = None

        self.start_frames = start_frames
        self.end_frames = end_frames
        self.max_frames = max_ms // FRAME_MS

        self._buf: list[np.ndarray] = []
        self._voiced = 0
        self._silent = 0
        self._active = False

    def _is_speech(self, frame: np.ndarray) -> bool:
        if self._vad is not None:
            try:
                return self._vad.is_speech(frame.tobytes(), SAMPLE_RATE)
            except Exception:
                pass
        return float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2))) > 0.012

    @property
    def active(self) -> bool:
        return self._active

    def push(self, frame_i16: np.ndarray) -> np.ndarray | None:
        """Feed one 20 ms int16 frame. Returns the utterance when it ends."""
        speech = self._is_speech(frame_i16)

        if not self._active:
            if speech:
                self._voiced += 1
                self._buf.append(frame_i16)
                if self._voiced >= self.start_frames:
                    self._active, self._silent = True, 0
            else:
                self._voiced = 0
                self._buf.clear()
            return None

        self._buf.append(frame_i16)
        self._silent = 0 if speech else self._silent + 1

        if self._silent >= self.end_frames or len(self._buf) >= self.max_frames:
            audio = np.concatenate(self._buf) if self._buf else np.zeros(0, np.int16)
            self._buf, self._voiced, self._silent, self._active = [], 0, 0, False
            # Anything under 300 ms is a cough, a door, or a keyboard.
            return audio if len(audio) > SAMPLE_RATE * 0.3 else None
        return None

    def reset(self) -> None:
        self._buf, self._voiced, self._silent, self._active = [], 0, 0, False


# ==========================================================================
# STT
# ==========================================================================
class Transcriber:
    """faster-whisper. int8 on CPU is real time for `base.en` on a laptop."""

    def __init__(self, model: str = "base.en", device: str = "cpu") -> None:
        from faster_whisper import WhisperModel

        compute = "int8" if device == "cpu" else "float16"
        log.info("loading whisper %s (%s/%s)", model, device, compute)
        self._model = WhisperModel(model, device=device, compute_type=compute)

    def __call__(self, audio_i16: np.ndarray) -> str:
        audio = audio_i16.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=1,               # greedy: this is a live conversation
            vad_filter=False,          # our Segmenter already did that
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


# ==========================================================================
# TTS
# ==========================================================================
@dataclass
class Audio:
    pcm: bytes          # signed 16-bit little endian, mono
    sample_rate: int


class Speaker:
    """Piper if a voice model is present, otherwise the OS speech engine.

    Download a voice once (about 60 MB) into demos/03_voice_agent/voices/:
        https://huggingface.co/rhasspy/piper-voices
    e.g. en/en_US/amy/medium/en_US-amy-medium.onnx  (+ the .onnx.json beside it)
    """

    def __init__(self, voice_path: str | None = None) -> None:
        self.engine = "none"
        self._piper = None
        self._tts = None

        path = Path(voice_path) if voice_path else self._discover()
        if path and path.exists():
            try:
                from piper import PiperVoice
                self._piper = PiperVoice.load(str(path))
                self.engine = f"piper:{path.stem}"
                log.info("tts: %s", self.engine)
                return
            except Exception as exc:
                log.warning("piper failed to load (%s), falling back", exc)

        try:
            import pyttsx3
            self._tts = pyttsx3.init()
            self._tts.setProperty("rate", 178)
            self.engine = "pyttsx3"
            log.info("tts: pyttsx3 (install a Piper voice for better audio)")
        except Exception as exc:
            log.error("no TTS engine available: %s", exc)

    @staticmethod
    def _discover() -> Path | None:
        if not VOICES.exists():
            return None
        found = sorted(VOICES.glob("*.onnx"))
        return found[0] if found else None

    def say(self, text: str) -> Audio | None:
        text = text.strip()
        if not text:
            return None
        if self._piper is not None:
            return self._piper_say(text)
        if self._tts is not None:
            return self._sapi_say(text)
        return None

    def _piper_say(self, text: str) -> Audio | None:
        chunks, rate = [], 22_050
        for chunk in self._piper.synthesize(text):
            rate = chunk.sample_rate
            chunks.append(chunk.audio_int16_bytes)
        return Audio(b"".join(chunks), rate) if chunks else None

    def _sapi_say(self, text: str) -> Audio | None:
        # pyttsx3 has no in-memory sink, so bounce through a temp wav.
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._tts.save_to_file(text, name)
            self._tts.runAndWait()
            with wave.open(name, "rb") as w:
                return Audio(w.readframes(w.getnframes()), w.getframerate())
        except Exception as exc:
            log.error("sapi synthesis failed: %s", exc)
            return None
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass


# ==========================================================================
# LLM
# ==========================================================================
SYSTEM = """You are Aria, a warm and curious voice host having a short live \
conversation with someone who just joined your video room.

You are being spoken to out loud and your replies are read by a speech engine, \
so: one or two sentences, never more. No lists, no markdown, no emoji, no \
stage directions, no asterisks. Contractions are good. Sound like a person, \
not a form.

Open by introducing yourself and asking how their day has been. From there, \
follow what they actually say: ask one genuine follow-up at a time, react to \
the specifics they mention, and let the conversation wander naturally. If they \
ask about you, answer briefly and hand the question back.

If you did not catch something, say so plainly and ask them to repeat it."""

SCRIPT = [
    "Hi there, I'm Aria. Really nice to meet you. How has your day been going so far?",
    "That sounds like a full day. What have you been working on lately?",
    "Nice. And is that the part of it you enjoy most, or is something else the fun bit?",
    "That makes sense. What are you hoping to get to next?",
    "I like that. Thanks for telling me about it, this was a good chat.",
]

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class Brain:
    """Claude when a key is present, a scripted host when it is not."""

    MODEL = "claude-opus-5"

    def __init__(self) -> None:
        self.history: list[dict] = []
        self._turn = 0
        self._client = None

        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self._client = anthropic.Anthropic()
                log.info("brain: %s", self.MODEL)
            except Exception as exc:
                log.warning("anthropic unavailable (%s), using the scripted host", exc)
        if self._client is None:
            log.info("brain: scripted (set ANTHROPIC_API_KEY for the real thing)")

    @property
    def kind(self) -> str:
        return "claude" if self._client else "scripted"

    def greeting(self) -> str:
        if self._client is None:
            return SCRIPT[0]
        return "".join(self.reply("<the user just joined the room>", greeting=True))

    def reply(self, user_text: str, greeting: bool = False) -> Iterator[str]:
        """Yields the reply sentence by sentence so speech starts before the
        model has finished writing. That is most of the perceived latency."""
        if not greeting:
            self.history.append({"role": "user", "content": user_text})

        if self._client is None:
            self._turn += 1
            text = SCRIPT[min(self._turn, len(SCRIPT) - 1)]
            self.history.append({"role": "assistant", "content": text})
            yield text
            return

        messages = self.history or [{"role": "user", "content": user_text}]
        buffer, full = "", []
        try:
            with self._client.messages.stream(
                model=self.MODEL,
                max_tokens=300,
                system=SYSTEM,
                output_config={"effort": "low"},    # it is small talk, not a proof
                messages=messages,
            ) as stream:
                for piece in stream.text_stream:
                    buffer += piece
                    parts = _SENTENCE.split(buffer)
                    while len(parts) > 1:
                        sentence = parts.pop(0).strip()
                        if sentence:
                            full.append(sentence)
                            yield sentence
                        buffer = " ".join(parts)
                        parts = _SENTENCE.split(buffer)
            if buffer.strip():
                full.append(buffer.strip())
                yield buffer.strip()
        except Exception as exc:
            log.error("claude call failed: %s", exc)
            yield "Sorry, I lost my train of thought there. What were you saying?"
            return

        self.history.append({"role": "assistant", "content": " ".join(full)})


# ==========================================================================
# resampling helper
# ==========================================================================
def resample_i16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear resample for mono int16. Good enough for speech, no SciPy."""
    if src_rate == dst_rate or not pcm:
        return pcm
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n_out = int(round(len(a) * dst_rate / src_rate))
    if n_out <= 0:
        return b""
    x_old = np.linspace(0.0, 1.0, num=len(a), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, a).astype(np.int16).tobytes()
