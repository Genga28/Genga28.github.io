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

import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
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

    def partial(self) -> np.ndarray | None:
        """What has been heard so far in the utterance still being spoken.

        Returned as a copy: the caller hands it to a worker thread while this
        one keeps appending frames to the live buffer.
        """
        if not self._active or not self._buf:
            return None
        return np.concatenate(self._buf).copy()

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
# Whisper is a generative model and it will write *something* for any audio
# you hand it. Measured on this machine with base.en and no guards: 1.5s of
# digital silence transcribes as "You", and so does low-level room noise.
# Those are the "random words" that arrive when a door closes or someone
# breathes near the mic, and the agent then earnestly answers them.
#
# The thresholds below are the real fix and they cost nothing: with
# vad_filter on and these cut-offs, silence, hiss, room noise and a keyboard
# click all return an empty string, while clean speech still comes back
# word-perfect at about 0.26x real time.
DECODE = dict(
    language="en",
    beam_size=1,                   # greedy: this is a live conversation
    condition_on_previous_text=False,
    vad_filter=True,               # Silero, inside faster-whisper
    no_speech_threshold=0.6,
    log_prob_threshold=-1.0,
    compression_ratio_threshold=2.0,
)

# Belt and braces. These are whisper's favourite things to invent out of
# nothing; a real reply this short carries no information anyway, so dropping
# them costs the conversation nothing.
GHOSTS = {"you", "thank you", "thanks for watching", "thank you.", "bye",
          "the", "uh", "um", "mm", "hmm", "yeah", ".", "!", "?"}
MIN_RMS = 0.006     # below this the clip is quieter than normal room tone


class Transcriber:
    """faster-whisper. int8 on CPU runs base.en at about 0.26x real time."""

    def __init__(self, model: str = "base.en", device: str = "cpu") -> None:
        from faster_whisper import WhisperModel

        compute = "int8" if device == "cpu" else "float16"
        log.info("loading whisper %s (%s/%s)", model, device, compute)
        self._model = WhisperModel(model, device=device, compute_type=compute)

    def __call__(self, audio_i16: np.ndarray, partial: bool = False) -> str:
        audio = audio_i16.astype(np.float32) / 32768.0

        # An energy gate before the model, not after. Running a generative
        # decoder on something with no speech in it is how invented words get
        # a chance to exist in the first place.
        if audio.size == 0 or float(np.sqrt(np.mean(audio ** 2))) < MIN_RMS:
            return ""

        segments, _ = self._model.transcribe(audio, **DECODE)
        segments = list(segments)
        if not segments:
            return ""

        text = " ".join(x.text.strip() for x in segments).strip()
        if not text:
            return ""

        # A low mean log probability on a very short result is the signature
        # of a guess. Long results are left alone: a confident model being
        # unsure about one word in twenty is normal.
        mean_lp = float(np.mean([x.avg_logprob for x in segments]))
        if len(text.split()) <= 3 and mean_lp < -0.9:
            return ""
        if text.strip().strip(".,!?").lower() in GHOSTS:
            return ""

        # A partial is a progress indicator, not a transcript. It is allowed
        # to be wrong at the edges because the final decode replaces it.
        return text


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
# WMO weather codes, in words a person would actually say out loud.
WMO = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "drizzling", 53: "drizzling",
    55: "drizzling", 56: "drizzling", 57: "drizzling",
    61: "raining lightly", 63: "raining", 65: "pouring",
    66: "raining", 67: "raining", 71: "snowing lightly", 73: "snowing",
    75: "snowing hard", 77: "snowing", 80: "showery", 81: "showery",
    82: "pouring", 85: "snowing", 86: "snowing",
    95: "thundery", 96: "thundery", 99: "thundery",
}


class Context:
    """Where and when this conversation is happening.

    A host who can say "rough Monday morning then" or "still raining there?"
    sounds like someone in the room. One who opens with the same line every
    time sounds like a kiosk. This is the cheapest possible source of that:
    the clock is free, and Open-Meteo needs no key and no account.

    The weather is fetched on a background thread and cached, so a slow or
    missing network costs the greeting nothing: the time of day alone is
    already enough to sound present, and the weather simply joins in late.
    """

    TTL = 900.0        # 15 minutes; the weather does not change faster

    def __init__(self, place: str | None = None) -> None:
        self.place = place or os.environ.get("ARIA_LOCATION") or self._from_timezone()
        self._weather: str | None = None
        self._fetched = 0.0
        self._lock = threading.Lock()
        self.refresh()

    @staticmethod
    def _from_timezone() -> str:
        """Asia/Kolkata -> Kolkata, when the platform will say that much.

        No IP lookup and no browser permission prompt: a demo should not
        phone a third party to find out roughly where you live. On Linux and
        macOS the local tzinfo carries an IANA key whose last segment is a
        real city. Windows does not; it reports "India Standard Time", which
        is a zone name, geocodes to nothing, and would put a lie in the
        prompt. So there the honest answer is none, and the clock carries the
        conversation on its own. Set ARIA_LOCATION in demos/.env to get the
        weather.
        """
        name = str(getattr(datetime.now().astimezone().tzinfo, "key", ""))
        return name.split("/")[-1].replace("_", " ").strip() if "/" in name else ""

    # ---------- the clock ----------
    def when(self) -> str:
        now = datetime.now()
        h = now.hour
        part = ("the middle of the night" if h < 5 else "very early" if h < 7
                else "morning" if h < 12 else "afternoon" if h < 17
                else "evening" if h < 21 else "late evening")
        return f"{now:%A} {part}, {h % 12 or 12}:{now:%M}{now:%p}".replace("AM", "am").replace("PM", "pm")


    # ---------- the sky ----------
    def refresh(self) -> None:
        if time.time() - self._fetched < self.TTL:
            return
        self._fetched = time.time()
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        try:
            import urllib.parse
            import urllib.request

            def get(url: str) -> dict:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "aria-voice-demo/1.0"})
                with urllib.request.urlopen(req, timeout=6) as r:
                    return json.loads(r.read().decode("utf-8"))

            geo = get("https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                      + urllib.parse.quote(self.place))
            hit = (geo.get("results") or [None])[0]
            if not hit:
                log.info("context: no coordinates for %r, using the clock only", self.place)
                return

            data = get(
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={hit['latitude']}&longitude={hit['longitude']}"
                "&current=temperature_2m,weather_code&timezone=auto"
            )
            cur = data.get("current") or {}
            temp = cur.get("temperature_2m")
            sky = WMO.get(int(cur.get("weather_code", -1)), None)
            if temp is None or sky is None:
                return
            with self._lock:
                self._weather = f"{sky}, {round(temp)} degrees"
            log.info("context: %s, %s", self.place, self._weather)
        except Exception as exc:
            log.info("context: no weather (%s), using the clock only", type(exc).__name__)

    # ---------- what the model sees ----------
    def line(self) -> str:
        """Facts, not a phrasing.

        The model words things better than a format string does, and a
        sentence it has to rearrange is one it is far less likely to read
        back verbatim as a weather report.
        """
        self.refresh()
        with self._lock:
            sky = self._weather
        bits = [f"their local time is {self.when()}"]
        if self.place:
            bits.append(f"they are in or near {self.place}")
        if sky:
            bits.append(f"the weather there is {sky}")
        return ("WHERE AND WHEN THIS CALL IS HAPPENING\n"
                + ", ".join(bits) + ".\n"
                "Use at most one of these, and only if it gives you something "
                "natural to say. Never read them back as a report.")



SYSTEM = """You are Aria. You are on a voice call with someone who just joined \
your room. You are easy to talk to: warm, curious, a bit informal, genuinely \
interested in whatever they say.

HOW YOU SOUND
A speech engine reads your words out loud, so write the way people talk. One \
or two short sentences. Never three. Short everyday words. Contractions \
always. No lists, no markdown, no emoji, no asterisks, no stage directions, \
and never describe your own tone.

Say "What have you been up to today?" not "What activities have occupied your \
attention?". If a sentence has a word in it you would not say to a friend in a \
cafe, pick a smaller one.

HOW YOU TALK
Open by saying who you are in a few words, then ask how their day is going. \
Use the time of day and the weather below if they give you something natural \
to say, the way anyone would: a Monday morning, a wet evening. Mention it once \
at most, lightly, and never recite it back like a forecast.

After that, follow them. React to the actual thing they said before you ask \
anything. One question at a time, and only when you are curious about the \
answer. It is fine to just say "oh nice" and let them keep going. Vary how you \
start your turns; never open two turns in a row the same way.

Do not interview them. Do not summarise what they just said back to them. Do \
not say "that sounds" at the start of every reply. If they ask about you, \
answer in a sentence and hand it back.

If you did not catch something, just say so and ask them to say it again."""

SCRIPT = [
    "Hey, I'm Aria. How's your day going?",
    "Oh nice. What have you been working on?",
    "That sounds like a good one. Is that the bit you enjoy most?",
    "Makes sense. What's next for it?",
    "I like that. Thanks for telling me, this was a good chat.",
]

# Characters a speech engine should never have to interpret. The dash family
# is the one that actually bites: a model writes "I'm Aria — how's your day?"
# and Piper reads the em dash as a pause of the wrong length while pyttsx3
# sometimes says nothing at all and swallows the clause boundary. A comma
# does the job the dash was doing.
_DASHES = str.maketrans({"\u2014": ",", "\u2013": ",", "\u2012": ",", "\u2015": ","})
_STRIP = re.compile(r"[*_`#>\[\]|]+")
_SPACES = re.compile(r"\s+")


def speakable(text: str) -> str:
    """Plain words, ready for a speech engine and for a caption."""
    out = _SPACES.sub(" ", _STRIP.sub("", text.translate(_DASHES))).strip()
    return _SPACES.sub(" ", out.replace(" ,", ",").replace(",,", ","))

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class Brain:
    """Claude when a key is present, a scripted host when it is not."""

    MODEL = os.environ.get("ARIA_MODEL") or "claude-opus-5"
    EFFORT = os.environ.get("ARIA_EFFORT") or "low"

    def __init__(self, context: "Context | None" = None) -> None:
        self.history: list[dict] = []
        self._turn = 0
        self._client = None
        self.context = context or Context()

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
        return " ".join(self.reply(
            "(they just joined the call and have not said anything yet. "
            "Say hello and ask how their day is going.)", greeting=True))

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
                # The context goes in the system block, not the transcript,
                # so it stays true for the whole call and the model never
                # mistakes it for something the person said.
                system=f"{SYSTEM}\n\n{self.context.line()}",
                output_config={"effort": self.EFFORT},   # small talk, not a proof
                messages=messages,
            ) as stream:
                for piece in stream.text_stream:
                    buffer += piece
                    parts = _SENTENCE.split(buffer)
                    while len(parts) > 1:
                        sentence = speakable(parts.pop(0))
                        if sentence:
                            full.append(sentence)
                            yield sentence
                        buffer = " ".join(parts)
                        parts = _SENTENCE.split(buffer)
            tail = speakable(buffer)
            if tail:
                full.append(tail)
                yield tail
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
