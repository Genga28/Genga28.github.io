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

import collections
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
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

log = logging.getLogger("pipeline")

# faster-whisper logs two lines for every decode. With a live partial every
# 600 ms that buries everything else in the terminal, including the lines
# that say what was actually heard.
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

HERE = Path(__file__).parent
VOICES = HERE / "voices"

SAMPLE_RATE = 16_000          # what Whisper and webrtcvad both want
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
PRE_ROLL_FRAMES = 15           # 300 ms kept from before speech opens


# ==========================================================================
# VAD
# ==========================================================================
class Silero:
    """Streaming speech probability from the Silero VAD that ships inside
    faster-whisper. It takes 512-sample windows and carries state between them,
    so 20 ms frames are accumulated until a window is full.

    webrtcvad is a 2013 energy-and-spectrum heuristic: ordinary room noise,
    a fan, or a laptop mic with automatic gain turned up all read as speech,
    which means an utterance never ends, the live caption decodes noise
    forever, and the agent never answers. Silero is a trained model and tells
    speech from noise.
    """

    WINDOW = 512

    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model
        self._model = get_vad_model()
        self.reset()

    def reset(self) -> None:
        self._state, self._ctx = self._model.get_initial_states(1)
        self._carry = np.zeros(0, dtype=np.float32)
        self.p = 0.0

    def __call__(self, frame_i16: np.ndarray) -> float:
        self._carry = np.concatenate(
            [self._carry, frame_i16.astype(np.float32) / 32768.0])
        while len(self._carry) >= self.WINDOW:
            window, self._carry = self._carry[:self.WINDOW], self._carry[self.WINDOW:]
            out, self._state, self._ctx = self._model(
                window[None, :], self._state, self._ctx, SAMPLE_RATE)
            self.p = float(np.ravel(out)[0])
        return self.p


class Segmenter:
    """Turns a stream of 20 ms frames into complete utterances.

    Speech starts after `start_frames` voiced frames in a row and ends after
    `end_frames` unvoiced ones, which is what stops the agent cutting in on a
    pause mid-sentence. A hard cap keeps one long monologue from starving the
    rest of the pipeline.
    """

    def __init__(
        self,
        # Aggressiveness 2, not 1. At 1 webrtcvad calls ordinary room noise
        # speech, so the utterance never ends: the buffer runs all the way to
        # max_ms, flushes, and starts again, and because a turn only begins
        # when an utterance *closes*, nothing is ever answered. Silero,
        # downstream and far more accurate, was meanwhile throwing away 100%
        # of every one of those buffers as containing no speech at all. Two
        # VADs disagreeing that completely is the tell.
        aggressiveness: int = 2,
        start_frames: int = 5,       # 100 ms of speech to open
        end_frames: int = 16,        # 320 ms of silence to close. Every ms
                                     # here is dead air at the end of every
                                     # single thing the user says, and it is
                                     # the largest single piece of the gap
                                     # before the agent answers.
        # 20 s was long enough that one stuck utterance stalled the whole
        # conversation while small.en chewed through it.
        max_ms: int = 12_000,
    ) -> None:
        self._silero: Silero | None = None
        try:
            self._silero = Silero()
        except Exception as exc:
            log.warning("silero vad unavailable (%s), falling back to webrtcvad", exc)
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
        # Rolling 300 ms of everything heard before speech opens. The VAD only
        # confirms speech a hundred milliseconds in, and without this the
        # first syllable of every sentence is thrown away: "working on" comes
        # out as "orking on", which is most of what read as bad recognition.
        self._pre: collections.deque[np.ndarray] = collections.deque(maxlen=PRE_ROLL_FRAMES)
        self._voiced = 0
        self._silent = 0
        self._active = False
        self._speech = 0               # voiced frames in the open utterance

    # Hysteresis. A higher bar to open than to stay open: opening on a cough
    # is a false turn, but dropping out between two words is a cut-off one.
    OPEN_P, STAY_P = 0.55, 0.30

    def _is_speech(self, frame: np.ndarray) -> bool:
        if self._silero is not None:
            return self._silero(frame) >= (self.STAY_P if self._active else self.OPEN_P)
        if self._vad is not None:
            try:
                return self._vad.is_speech(frame.tobytes(), SAMPLE_RATE)
            except Exception:
                pass
        return float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2))) > 0.012

    @property
    def active(self) -> bool:
        return self._active

    @property
    def speech_ratio(self) -> float:
        """Share of the open utterance the VAD called speech.

        A buffer that is mostly "not speech" is room noise the VAD flickered
        on. Whisper will still write something for it, and what it writes for
        noise is a repeated phrase or a run of dots.
        """
        return self._speech / len(self._buf) if self._buf else 0.0

    def partial(self) -> np.ndarray | None:
        """What has been heard so far in the utterance still being spoken.

        Returned as a copy: the caller hands it to a worker thread while this
        one keeps appending frames to the live buffer.
        """
        if not self._active or not self._buf or self.speech_ratio < 0.3:
            return None
        return np.concatenate(self._buf).copy()

    def push(self, frame_i16: np.ndarray) -> np.ndarray | None:
        """Feed one 20 ms int16 frame. Returns the utterance when it ends."""
        speech = self._is_speech(frame_i16)

        if not self._active:
            self._pre.append(frame_i16)
            if speech:
                self._voiced += 1
                if self._voiced >= self.start_frames:
                    self._buf = list(self._pre)
                    self._speech = self._voiced
                    self._pre.clear()
                    self._active, self._silent = True, 0
            else:
                self._voiced = 0
            return None

        self._buf.append(frame_i16)
        self._silent = 0 if speech else self._silent + 1
        self._speech += speech

        if self._silent >= self.end_frames or len(self._buf) >= self.max_frames:
            audio = np.concatenate(self._buf) if self._buf else np.zeros(0, np.int16)
            noise = self.speech_ratio < 0.2
            self._speech = 0
            self._buf, self._voiced, self._silent, self._active = [], 0, 0, False
            self._pre.clear()
            # Anything under 300 ms is a cough, a door, or a keyboard.
            return audio if len(audio) > SAMPLE_RATE * 0.3 and not noise else None
        return None

    def reset(self) -> None:
        self._buf, self._voiced, self._silent, self._active = [], 0, 0, False
        self._speech = 0
        self._pre.clear()


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
    beam_size=5,                   # the final decode is the one that is kept
    condition_on_previous_text=False,
    vad_filter=True,               # Silero, inside faster-whisper
    # The default Silero settings clip soft word onsets and cut at the first
    # breath. A wide pad and a patient silence keep the whole sentence.
    vad_parameters=dict(threshold=0.35, min_silence_duration_ms=600,
                        speech_pad_ms=400),
    no_speech_threshold=0.6,
    log_prob_threshold=-1.0,
    compression_ratio_threshold=2.4,
    # Vocabulary this conversation actually uses. Whisper spells what it was
    # primed with: without it "agentic" is "a gentic" or "agenda", and "Aria"
    # is "area".
    initial_prompt="Aria. Agentic AI, voice agents, LLM, RAG, Python, portfolio.",
)

# The live caption is throwaway text that the final decode replaces, so it is
# decoded greedily and with every confidence cut-off removed. Those cut-offs
# exist to stop invented words reaching the model; a caption never reaches
# the model, and applying them to a tiny.en decode of a half-finished
# sentence dropped nearly every partial, so nothing showed until the end.
PARTIAL_DECODE = dict(
    language="en",
    beam_size=1,
    condition_on_previous_text=False,
    temperature=0.0,               # no retry ladder, so no latency spikes
    initial_prompt="Aria. Agentic AI, voice agents, LLM, RAG, Python, portfolio.",
    vad_filter=False,              # the segmenter already decided this is speech
    no_speech_threshold=None,
    log_prob_threshold=None,
    compression_ratio_threshold=None,
)

# Whisper's favourite things to invent out of nothing. This list only
# applies to a result the model was *also* unsure about: "Yeah" is both the
# classic hallucination and a perfectly normal answer, and a blocklist that
# cannot tell them apart throws away half of what someone says. Confidence
# is what separates them.
GHOSTS = {"you", "thank you", "thanks for watching", "bye", "the",
          "uh", "um", "mm", "hmm", "yeah", ".", "!", "?", ",", "-"}
GHOST_LP = -0.75    # only drop a ghost word when the model was unsure too

# Low enough to pass quiet speech on a laptop microphone held at arm's
# length. The earlier 0.006 was set from synthesised audio at full scale and
# silently swallowed real sentences spoken at a normal volume.
MIN_RMS = 0.0022
TARGET_RMS = 0.06      # a normal speaking level once normalised
MAX_GAIN = 12.0        # enough for a quiet mic, not enough to turn hiss into words


# What Whisper writes for audio with nothing in it. Each of these was seen in
# a live log with nobody speaking.
HALLUCINATIONS = {
    "music", "applause", "laughter", "silence", "thank you", "thanks for watching",
    "i'm going to go to the next one", "so, let's go", "so let's go",
    "i'm going to be right back", "you",
}


def degenerate(text: str) -> bool:
    """True for what Whisper writes when there is nothing to transcribe:
    punctuation only, or one phrase looped. Real speech repeats a word, not
    a whole sentence nine times over."""
    if not re.search(r"[A-Za-z]{2}", text):
        return True
    # The vocabulary prompt handed to Whisper, written back out as a
    # transcript. It happens on audio with little in it, and it has to be
    # dropped, not answered.
    prompt_words = {"aria", "agentic", "ai", "voice", "agents", "agent", "llm",
                    "rag", "python", "portfolio"}
    toks = re.findall(r"[a-z']+", text.lower())
    if len(toks) >= 3 and all(t in prompt_words for t in toks):
        return True
    if re.sub(r"[^a-z' ,]", "", text.lower()).strip(" ,") in HALLUCINATIONS:
        return True
    if re.fullmatch(r"[\[\(].*[\]\)]", text.strip()):     # "[Music]", "(applause)"
        return True
    words = text.lower().split()
    if len(words) >= 12 and len(set(words)) <= len(words) * 0.35:
        return True
    return len(text) > 40 and len(zlib.compress(text.encode())) < len(text) / 2.6


class Transcriber:
    """faster-whisper, int8 on CPU. small.en runs at about 0.3x real time with 8
    threads, which is the price of reading a real accent properly."""

    def __init__(self, model: str = "base.en", device: str = "cpu",
                 threads: int = 0) -> None:
        from faster_whisper import WhisperModel

        compute = "int8" if device == "cpu" else "float16"
        log.info("loading whisper %s (%s/%s)", model, device, compute)
        self._model = WhisperModel(model, device=device, compute_type=compute,
                                   cpu_threads=threads)

    def __call__(self, audio_i16: np.ndarray, partial: bool = False) -> str:
        audio = audio_i16.astype(np.float32) / 32768.0

        # An energy gate before the model, not after. Running a generative
        # decoder on something with no speech in it is how invented words get
        # a chance to exist in the first place.
        if audio.size == 0:
            return ""
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < MIN_RMS:
            return ""

        # Bring the clip up to a normal speaking level. Laptop microphones
        # vary by more than a factor of ten, and everything downstream has an
        # absolute threshold: Silero's speech probability, whisper's
        # no-speech threshold, the log-probability floor. On a quiet mic all
        # three fire at once and every single clip comes back empty, which
        # looks exactly like the model being deaf. Gain is capped so that
        # amplifying near-silence cannot manufacture speech out of hiss.
        audio = audio * min(TARGET_RMS / max(rms, 1e-6), MAX_GAIN)
        np.clip(audio, -1.0, 1.0, out=audio)

        if partial:
            segments, _ = self._model.transcribe(audio, **PARTIAL_DECODE)
            text = " ".join(x.text.strip() for x in segments).strip()
            text = re.sub(r"[\s/\|_~^<>*=+-]+$", "", text).strip()
            return "" if degenerate(text) else text

        # Half a second of silence either side. Whisper was trained on clips
        # with room around the speech and is measurably worse on ones that
        # start or stop dead on a word.
        pad = np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)
        audio = np.concatenate([pad, audio, pad])

        segments, _ = self._model.transcribe(audio, **DECODE)
        segments = list(segments)
        if not segments:
            return ""

        text = " ".join(x.text.strip() for x in segments).strip()
        # base.en likes to end a clip with a stray "//" or a run of dots and
        # dashes. It is not a word, it reaches the model as one, and it ends
        # up read aloud in the caption.
        text = re.sub(r"[\s/\|_~^<>*=+-]+$", "", text).strip()
        if not text or degenerate(text):
            return ""

        # A poor mean log probability on a very short result is the signature
        # of a guess. Long results are left alone: a confident model being
        # unsure about one word in twenty is normal. The bar is deliberately
        # low, because rejecting a real "no, not really" is a worse failure
        # than letting one invented word through.
        mean_lp = float(np.mean([x.avg_logprob for x in segments]))
        short = len(text.split()) <= 3
        if short and mean_lp < -1.05:
            return ""
        if short and mean_lp < GHOST_LP and text.strip().strip(".,!?").lower() in GHOSTS:
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

# Appended to the system prompt on the turn that ends the call.
# The call ends when Aria says so, by putting END_TOKEN at the end of a reply.
# The token is stripped before anything is spoken or shown.
END_TOKEN = "[END]"
WRAP = {
    "soft": (
        "THE CALL HAS RUN ITS NATURAL LENGTH. First respond properly to what "
        "they just said or asked, in one or two short sentences, as you "
        "normally would. If this feels like a natural place to finish, close "
        "warmly: thank them, say it was good talking, say goodbye, and put the "
        f"exact token {END_TOKEN} at the very end of your reply. If they are "
        "clearly mid-thought, or closing now would feel abrupt, do not close "
        "yet: answer them, and mention that you should let them go soon. Never "
        f"ask a new question in a reply that ends with {END_TOKEN}."
    ),
    "hard": (
        "THIS MUST BE THE LAST EXCHANGE. React briefly to what they said, then "
        "thank them, say it was good talking, say goodbye, and put the exact "
        f"token {END_TOKEN} at the very end. Do not ask a question."
    ),
    "goodbye": (
        "THEY ARE SAYING GOODBYE. Reply with one short warm sentence: you "
        f"enjoyed it, thanks, bye. Put the exact token {END_TOKEN} at the very "
        "end. Do not ask a question."
    ),
}

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
    """The reply, as two streams out of one.

    Speech can only begin on a whole sentence, but a caption should not wait
    for one: at conversational speed the gap between the first word arriving
    and the full stop is most of a second, and a caption that lands all at
    once at the end of it reads as lag. So `reply` yields ("text", all of it
    so far) as the words arrive and ("say", one sentence) when there is
    something the voice can start on.

    Two providers, because the only thing that matters for this job is how
    fast the first sentence appears. Measured on this machine, time to first
    token for the same prompt:

        gemini-2.5-flash-lite   0.80s
        claude-haiku-4-5        1.13s
        gemini-2.5-flash        1.24s
        claude-opus-5           1.53s

    None of them is the bottleneck; recognising the speech costs more than
    any of them. Opus writes the best small talk of the four and is still a
    perfectly good choice at a second and a half, which is why the gap is
    worth knowing rather than worth agonising over.
    """

    PROVIDER = (os.environ.get("ARIA_PROVIDER") or "").strip().lower()
    CLAUDE_MODEL = os.environ.get("ARIA_MODEL") or "claude-haiku-4-5-20251001"
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    EFFORT = os.environ.get("ARIA_EFFORT") or "low"

    def __init__(self, context: "Context | None" = None) -> None:
        self.history: list[dict] = []
        self._turn = 0
        self._client = None
        self.provider = "scripted"
        self.model = ""
        self.context = context or Context()

        order = ([self.PROVIDER] if self.PROVIDER else
                 ["gemini", "claude"] if os.environ.get("GOOGLE_API_KEY") else
                 ["claude", "gemini"])
        for name in order:
            if self._start(name):
                break
        if self._client is None:
            log.info("brain: scripted (set ANTHROPIC_API_KEY or GOOGLE_API_KEY "
                     "for the real thing)")

    def _start(self, name: str) -> bool:
        try:
            if name == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
                import anthropic
                self._client = anthropic.Anthropic()
                self.provider, self.model = "claude", self.CLAUDE_MODEL
            elif name == "gemini" and os.environ.get("GOOGLE_API_KEY"):
                from google import genai
                self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
                self.provider, self.model = "gemini", self.GEMINI_MODEL
            else:
                return False
        except Exception as exc:
            log.warning("%s unavailable (%s)", name, exc)
            self._client = None
            return False
        log.info("brain: %s", self.model)
        return True

    @property
    def kind(self) -> str:
        return self.provider

    def _effort(self) -> dict:
        """output_config is a 4.6-and-later thing.

        Sent to Haiku 4.5 it is a 400, and the agent then apologises for
        losing its train of thought on every single turn instead.
        """
        modern = any(k in self.model for k in
                     ("opus-5", "sonnet-5", "fable-5", "opus-4-8", "opus-4-7",
                      "opus-4-6", "sonnet-4-6"))
        return {"output_config": {"effort": self.EFFORT}} if modern else {}

    def greeting(self) -> str:
        if self._client is None:
            return SCRIPT[0]
        opener = ("(they just joined the call and have not said anything yet. "
                  "Say hello and ask how their day is going.)")
        return " ".join(t for k, t in self.reply(opener, greeting=True) if k == "say")

    # ---------------- the stream ----------------
    def reply(self, user_text: str, greeting: bool = False,
              wrap: str | None = None) -> Iterator[tuple[str, str]]:
        if not greeting:
            self.history.append({"role": "user", "content": user_text})

        if self._client is None:
            self._turn += 1
            text = SCRIPT[-1 if wrap else min(self._turn, len(SCRIPT) - 1)]
            self.history.append({"role": "assistant", "content": text})
            yield ("text", text)
            yield ("say", text)
            if wrap:
                yield ("end", "")
            return

        messages = list(self.history or [{"role": "user", "content": user_text}])
        system = f"{SYSTEM}\n\n{self.context.line()}"
        if wrap in WRAP:
            # In the system prompt it was being ignored: Aria asked another
            # question and the call hung up on her. On the message she is
            # answering, it is part of what she is replying to.
            system += f"\n\n{WRAP[wrap]}"
            last = messages[-1]
            messages[-1] = {**last, "content": f"{last['content']}\n\n[{WRAP[wrap]}]"}
        pieces = (self._claude(system, messages) if self.provider == "claude"
                  else self._gemini(system, messages))

        buffer, said, full, ended = "", "", [], False
        try:
            for piece in pieces:
                buffer += piece
                said += piece
                if END_TOKEN in buffer:
                    ended = True
                    buffer = buffer.replace(END_TOKEN, "")
                    said = said.replace(END_TOKEN, "")
                yield ("text", speakable(said))
                parts = _SENTENCE.split(buffer)
                while len(parts) > 1:
                    sentence = speakable(parts.pop(0))
                    if sentence:
                        full.append(sentence)
                        yield ("say", sentence)
                    buffer = " ".join(parts)
                    parts = _SENTENCE.split(buffer)
            # A token cut off mid-way by max_tokens must not be read aloud.
            buffer = re.sub(r"\[[A-Z]{0,3}$", "", buffer)
            tail = speakable(buffer)
            if tail:
                full.append(tail)
                yield ("say", tail)
            if ended:
                yield ("end", "")
        except Exception as exc:
            log.error("%s call failed: %s", self.provider, exc)
            lost = "Sorry, I lost my train of thought there. What were you saying?"
            yield ("text", lost)
            yield ("say", lost)
            return

        self.history.append({"role": "assistant", "content": " ".join(full)})

    def _claude(self, system: str, messages: list[dict]) -> Iterator[str]:
        with self._client.messages.stream(
            model=self.model, max_tokens=300, system=system,
            messages=messages, **self._effort(),
        ) as stream:
            yield from stream.text_stream

    def _gemini(self, system: str, messages: list[dict]) -> Iterator[str]:
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=300,
            # Thinking is the whole latency budget for a reply this short,
            # and there is nothing here to think about.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user",
                          parts=[types.Part(text=m["content"])])
            for m in messages
        ]
        for chunk in self._client.models.generate_content_stream(
            model=self.model, contents=contents, config=cfg,
        ):
            if chunk.text:
                yield chunk.text


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
