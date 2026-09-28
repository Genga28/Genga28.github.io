# Demo 4 — Real-time proctoring

Four visual signals, scored independently, fused into one calibrated 0–100
number with risk bands and timestamped episodes. Runs at camera frame rate on
CPU.

```powershell
python proctor.py
python proctor.py --record demo.mp4
python proctor.py --camera 1 --no-mesh
```

`q` quit · `m` toggle mesh · `r` reset episodes

## The signals

| Channel | Weight | Derived from |
|---|---|---|
| `gaze` | 0.30 | iris centre against each eye's own corner span, suppressed while the eyelids are shut |
| `pose` | 0.25 | yaw and pitch from `solvePnP` against a six-point canonical face model |
| `absence` | 0.25 | no face in frame |
| `company` | 0.20 | more than one face in frame |

Each is a smooth ramp, not a threshold: zero inside a dead zone, 100 at the far
end, smoothstep between. A hard threshold makes the score flicker at the
boundary, which is what makes a meter look untrustworthy.

## The fusion

```
base  = Σ wᵢ · sᵢ
boost = ((peak − 70) / 30) ^ 1.5 × 18      when peak > 70
score = clamp(base + boost, 0, 100)
```

The boost is the whole argument. A pure weighted sum under-reacts to one
channel screaming — a face that vanishes entirely gets averaged into
irrelevance by three calm channels. The boost lets a single extreme reading
escalate the total without ever letting it convict on its own.

Bands cut at 30 / 60 / 85. Episodes open at 60 and close at 45: the hysteresis
stops one borderline frame from opening and shutting an episode every second.

## Smoothing

`Smooth` is an asymmetric EMA — 0.35 rising, 0.08 falling. A signal that spikes
and instantly clears is noise; one that spikes and lingers is real. Reacting
fast upward and decaying slowly encodes that asymmetry directly.

## Output

- `output/signals.csv` — every frame: score, band, all four channels, yaw, pitch, gaze
- `output/episodes.csv` — start, end, peak, which channels drove it
- `output/demo.mp4` — the annotated view, with `--record`

## Recording it

Sit in frame and let it settle at CLEAR. Then, one at a time: look off to the
side and hold it, turn your head, step out of frame, have someone lean in
behind you. Each one drives a different channel — and the point of the demo is
watching the score respond differently to each rather than just going red.

About 45 seconds is enough for all four.

## Caveats

- `solvePnP` flips sign near frontal; there's a correction for it, but extreme
  angles are still unreliable.
- Iris landmarks need `refine_landmarks=True` and reasonable light. In a dark
  room the gaze channel gets noisy and the smoothing will show it.
- Weights and thresholds here are illustrative and tuned for a webcam at arm's
  length. They are not anyone's production calibration.
