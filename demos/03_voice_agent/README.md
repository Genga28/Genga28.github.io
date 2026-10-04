# Demo 3 — Aria, a self-hosted voice agent

A real WebRTC room with an agent in it. No LiveKit, no Twilio, no account, no
per-minute billing. The browser negotiates a peer connection straight to a local
Python process; speech recognition and synthesis both run on this machine.

```
browser ──── POST /offer (SDP) ───────────▶ aiortc peer
browser ════ mic audio, Opus ═════════════▶ VAD ─▶ faster-whisper ─▶ Claude
browser ◀═══ agent audio, Opus ═══════════   Piper ◀────────────────────┘
browser ◀─── captions + state, WebSocket ──  orchestrator
                                              └─▶ SQLite (session.db)
```

| Stage | What runs | Where |
|---|---|---|
| Turn detection | webrtcvad, 20 ms frames | local |
| Speech to text | faster-whisper `base.en`, int8 | local |
| Reasoning | Claude Opus 5, streamed by sentence | API (optional) |
| Text to speech | Piper ONNX voice | local |
| Transport | aiortc, Opus both directions | local |
| Avatar | Three.js, jaw driven by real audio amplitude | browser |

## Install

```powershell
cd demos
.\.venv\Scripts\Activate.ps1
pip install -r 03_voice_agent/requirements.txt
```

`aiortc` pulls PyAV, which ships Windows wheels — no FFmpeg install needed.

### Get a Piper voice (recommended, ~60 MB)

Without it the agent falls back to the Windows SAPI voice, which works but
sounds like 2009.

```powershell
mkdir 03_voice_agent\voices
cd 03_voice_agent\voices
curl.exe -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
curl.exe -L -O https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json
```

Both files must sit together. The server picks up the first `.onnx` it finds.

### Optional: where you are, for the small talk

```
ARIA_LOCATION=Bengaluru
```

in `demos/.env`. Aria then knows the local time and the current weather and
can open with something a person would say. Open-Meteo, no key, no account,
fetched on a background thread and cached for fifteen minutes so a slow
network never delays the greeting.

Without it she still has the clock, which is most of the value. There is
deliberately no IP geolocation fallback: a demo should not quietly ask a
third party roughly where you live. On Linux and macOS the local timezone
carries an IANA city name and that is used automatically; Windows reports
"India Standard Time", which is a zone, not a place, and geocodes to nothing.

### Optional: the Claude brain

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Without a key the agent still holds a short scripted conversation, so the demo
records fine either way — the badge in the UI says which brain is live.

## Run

```powershell
python 03_voice_agent/server.py
```

Then open **http://127.0.0.1:8080** and press *Join the room*. Chrome or Edge.
Use headphones: without them the agent hears itself and interrupts itself.

```powershell
python server.py --whisper tiny.en      # fastest
python server.py --whisper small.en     # most accurate, needs a bit more CPU
python server.py --voice voices\en_US-ryan-high.onnx
```

## Keeping it responsive

Perceived lag in a voice agent is almost entirely the gap between the user
finishing a sentence and the first syllable coming back. Five things buy that
back, and they are all in the code:

- **Sentence streaming.** `Brain.reply()` is a generator. Claude's response is
  split on sentence boundaries as it streams, and each sentence goes to Piper
  immediately. Speech starts while the model is still writing.
- **Warm engines.** `State._warm()` runs a throwaway transcription and a
  throwaway synthesis at boot, so the first real turn doesn't pay ONNX session
  setup and encoder allocation.
- **Greedy decode.** `beam_size=1` and `condition_on_previous_text=False`. Beam
  search buys accuracy you don't need on conversational English.
- **Low effort.** `output_config={"effort": "low"}` — it's small talk, not a
  proof, and effort is the single biggest lever on time-to-first-token.
- **Barge-in.** The moment VAD opens while the agent is mid-sentence, the
  outbound buffer is flushed. Talking over it actually stops it.

If it still drags, in order of impact: `--whisper tiny.en`, then a CUDA build of
CTranslate2, then a `low` Piper voice instead of `medium`.

## Recording it

Join, let it greet you, have a 40-second conversation, stop. The caption bar and
the jaw movement are what sell it, so keep the window at 1280x720 and record
system audio as well as the mic.

## What it does with your voice

The caption updates **while you are still speaking**. Whisper has no
streaming mode, so this is the partial buffer re-decoded every 600 ms and the
text replaced; at base.en's 0.26x real time there is room for that, and a
single in-flight flag means a slow decode skips a beat rather than queueing
behind itself. The partial is a caption only and never reaches the model.
The turn still waits for the segmenter to close the utterance and decode it
properly. A provisional line is shown in italic with a caret, because a
re-decode changes its own last words and a settled-looking line that keeps
rewriting itself looks broken.

### Why it stopped hearing things you did not say

Whisper is generative and will write *something* for any audio at all.
Measured here with `base.en` and no guards: 1.5 s of digital silence
transcribes as "You", and so does low-level room noise. That is where random
words come from, and the agent then answers them in earnest.

| Input | no guards | with guards |
|---|---|---|
| silence, 1.5 s | `"You"` | empty |
| quiet hiss | empty | empty |
| room noise | `"You"` | empty |
| keyboard click | empty | empty |
| four spoken sentences | word perfect | word perfect |

The guards are `vad_filter` plus `no_speech_threshold`, `log_prob_threshold`
and `compression_ratio_threshold`, an RMS gate before the decoder so it is
never asked to interpret near-silence, and a rejection rule for very short
results with a poor mean log probability. They cost nothing measurable:
`base.en` still runs at about 0.26x real time.

`small.en` is available with `--whisper small.en`. On this corpus it was no
more accurate than `base.en` and 2.7x slower, so it is not the default;
it is likely worth it on a noisier microphone than the one this was tested on.

## Files

| File | What's in it |
|---|---|
| `pipeline.py` | VAD segmenter, Whisper wrapper, Claude brain, Piper/SAPI speaker |
| `server.py` | FastAPI, aiortc peer, the outbound audio track, orchestration, SQLite |
| `web/index.html` | Room UI and all of its CSS |
| `web/app.js` | WebRTC handshake, captions, the procedural Three.js bust |
| `session.db` | Every turn, with latency, written as it happens |

## Honest limits

- One room, one participant. Multi-party needs an SFU, which is exactly the
  problem LiveKit exists to solve.
- `iceServers` is empty because both peers are on this machine. Put it on a
  network and it needs STUN, and behind symmetric NAT it needs TURN.
- The avatar is procedural geometry, not a scanned human: a shaped skull with
  a hinged jaw, lids that close, eyes that saccade and a chest that breathes,
  all built from primitives at load time. No asset to download and no licence
  to track, and the things that actually read as alive are the motion rather
  than the polygon count. It will not pass for a photograph. Swapping in a
  Ready Player Me GLB with ARKit blendshapes is a `GLTFLoader` call plus
  mapping `mouth` onto the `jawOpen` morph target; the amplitude signal is
  already there.
- Vertical gaze on the avatar is cosmetic. It is driven by an idle model, not
  by anything it can see: there is no camera input on this demo.
- Echo cancellation is the browser's. Without headphones it is not enough.
