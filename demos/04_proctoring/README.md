# Demo 4 — Real-time proctoring

Four visual signals, scored independently, fused into one calibrated 0–100
number with risk bands and timestamped episodes. Runs at camera frame rate on
CPU.

```powershell
python proctor.py
python proctor.py --record demo.mp4
python proctor.py --camera 1 --no-mesh
```

`q` quit · `m` toggle mesh · `r` reset episodes · `c` recalibrate gaze

## Gaze direction

Alongside the fused score the overlay names where the eyes are pointing
(`LEFT` `RIGHT` `UP` `DOWN` `CENTRE` `EYES SHUT` `FACE NOT VISIBLE`), how long
that direction has held, and a running total per direction. When the face
leaves frame a banner says so in the middle of the picture with the clock
running on it.

Three things make that label mean something rather than flicker:

**A measured origin, not an assumed one.** The iris does not sit at the
geometric centre of the eye. The lower lid is further from it than the upper
one, so a subject looking straight down the lens measures about `-0.14`
vertically, well past any useful dead zone. Without correcting for it the
label reads `UP` for the entire session. The first 25 frames of a single
open-eyed face set the origin, taken as a median so a blink during
calibration cannot move it. A camera mounted off to one side biases the
horizontal the same way, and the same correction handles it. Press `c` to
redo it if you move.

**Each axis against its own dead zone.** Horizontal is the iris across the
eye's corner span; vertical is the iris within the eyelid aperture. Those are
different spans, so the raw numbers are not comparable. Each is divided by its
own threshold first, and whichever is further outside its own names the
direction.

**Hysteresis at both ends.** A new direction has to hold for 200 ms before the
label changes, so one frame of tracker jitter cannot open a dwell, and a dwell
under 300 ms is left out of the log, because a saccade that clips the dead
zone on its way somewhere else is not a glance at anything.

The horizontal reading is re-signed to the displayed image before it is
labelled. `eye_ratio` runs corner-to-corner along the face, so its sign is
anatomical and does not follow the horizontal flip the preview applies;
reading which corner currently has the larger x recovers the on-screen
direction either way. A label that disagrees with the picture is worse than no
label.

Vertical is the weaker of the two: look down and the upper lid follows the
iris, so the aperture ratio moves less than the eye did. It carries a wider
dead zone for that reason, and it names the direction without feeding the
score.

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

- `output/signals.csv` — every frame: score, band, all four channels, yaw,
  pitch, both gaze axes, the current direction and how long it had held
- `output/gaze_log.csv` — one row per dwell: direction, start, end, duration.
  Flushed as each dwell closes, so the log is complete even if the process is
  killed rather than quit
- `output/episodes.csv` — start, end, peak, which channels drove it
- `output/demo.mp4` — the annotated view, with `--record`

On exit it also prints time by direction as a share of the session.

## Recording it

Look at the camera for the first second while the gaze origin is measured;
the overlay says `CALIBRATING` until it is done. Then let it settle at CLEAR.

Then, one at a time: look off to the side and hold it, look down as if at a
phone, turn your head, step out of frame, have someone lean in behind you.
Each drives a different channel, and the point is watching the score respond
differently to each rather than just going red. The direction label and its
held-time make the gaze moves legible on camera in a way a bar alone does not.

About 45 seconds is enough for all of them.

## Caveats

- `solvePnP` flips sign near frontal; there's a correction for it, but extreme
  angles are still unreliable.
- Iris landmarks need `refine_landmarks=True` and reasonable light. In a dark
  room the gaze channel gets noisy and the smoothing will show it.
- Weights and thresholds here are illustrative and tuned for a webcam at arm's
  length. They are not anyone's production calibration.
- The measured origin corrects the direction label only. The `gaze` channel
  that feeds the score still uses the raw offset, so a subject whose resting
  gaze sits outside the dead zone carries a small constant on that channel.
  Fixing that means recalibrating the published weights, which is a larger
  change than it looks.
