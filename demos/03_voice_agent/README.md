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

## Files

| File | What's in it |
|---|---|
| `pipeline.py` | VAD segmenter, Whisper wrapper, Claude brain, Piper/SAPI speaker |
| `server.py` | FastAPI, aiortc peer, the outbound audio track, orchestration, SQLite |
| `web/index.html` | Room UI and all of its CSS |
| `web/app.js` | WebRTC handshake, captions, Three.js avatar |
| `session.db` | Every turn, with latency, written as it happens |

## Honest limits

- One room, one participant. Multi-party needs an SFU, which is exactly the
  problem LiveKit exists to solve.
- `iceServers` is empty because both peers are on this machine. Put it on a
  network and it needs STUN, and behind symmetric NAT it needs TURN.
- The avatar is procedural geometry, not a rigged human. Swapping in a Ready
  Player Me GLB with ARKit blendshapes is a `GLTFLoader` call plus mapping
  `mouth` onto the `jawOpen` morph target — the amplitude signal is already there.
- Echo cancellation is the browser's. Without headphones it is not enough.
