"""
Real-time proctoring: four independent visual signals fused into one calibrated
0-100 score with risk bands and timestamped episodes.

    python proctor.py
    python proctor.py --record demo.mp4
    python proctor.py --camera 1 --no-mesh

    q / Esc  quit        m  toggle mesh        r  reset episodes

The point is not any single detector. Gaze drifts because people think. Heads
turn because someone knocked. A face vanishes because the laptop lid moved.
Firing on any one of those produces false accusations, and demanding all four
produces silence. So each channel scores independently, they blend by weight,
and a single extreme reading can escalate the total through an exponential
boost without ever being able to convict on its own.

Every score carries the episodes that produced it. That is the difference
between a number someone can audit and a verdict they have to trust.

Illustrative weights and thresholds. Nothing here is anyone's production
calibration.
"""

from __future__ import annotations

import argparse
import csv
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

OUT = Path(__file__).parent / "output"

# ---- fusion model (mirrors the interactive widget on the portfolio) --------
WEIGHTS = {"gaze": 0.30, "pose": 0.25, "absence": 0.25, "company": 0.20}
BOOST_KNEE, BOOST_POWER, BOOST_GAIN = 70.0, 1.5, 18.0

BANDS = [(30, "CLEAR", (122, 216, 111)), (60, "REVIEW", (94, 193, 239)),
         (85, "ELEVATED", (92, 160, 240)), (101, "CRITICAL", (127, 127, 238))]

# ---- thresholds -----------------------------------------------------------
GAZE_DEADZONE, GAZE_FULL = 0.055, 0.30     # normalised iris offset
YAW_DEADZONE, YAW_FULL = 12.0, 42.0        # degrees
PITCH_DEADZONE, PITCH_FULL = 12.0, 38.0
EAR_CLOSED = 0.17
EPISODE_ENTER, EPISODE_EXIT = 60.0, 45.0   # hysteresis on the fused score

# ---- landmarks ------------------------------------------------------------
L_EYE, R_EYE = (33, 133), (362, 263)
L_IRIS, R_IRIS = 468, 473
L_LID, R_LID = (159, 145), (386, 374)
PNP_IDX = [1, 152, 33, 263, 61, 291]
PNP_3D = np.array([
    (0.0, 0.0, 0.0), (0.0, -63.6, -12.5), (-43.3, 32.7, -26.0),
    (43.3, 32.7, -26.0), (-28.9, -28.9, -24.1), (28.9, -28.9, -24.1),
], dtype=np.float64)

WHITE, DIM, INK = (240, 243, 248), (150, 165, 185), (24, 18, 12)
ACCENT = (255, 184, 122)      # BGR of the portfolio blue


def ramp(value: float, dead: float, full: float) -> float:
    """0 inside the dead zone, 100 at `full`, smooth in between."""
    v = abs(value)
    if v <= dead:
        return 0.0
    t = min(1.0, (v - dead) / max(full - dead, 1e-6))
    return 100.0 * (t * t * (3 - 2 * t))


def band(score: float):
    for limit, name, colour in BANDS:
        if score < limit:
            return name, colour
    return BANDS[-1][1], BANDS[-1][2]


@dataclass
class Episode:
    start: float
    end: float | None = None
    peak: float = 0.0
    drivers: set[str] = field(default_factory=set)

    def label(self) -> str:
        span = f"{self.start:6.1f}s" + (f" - {self.end:5.1f}s" if self.end else " ...  ")
        return f"{span}  {self.peak:3.0f}  {', '.join(sorted(self.drivers)) or 'mixed'}"


class Smooth:
    """Asymmetric EMA: react fast to a rise, decay slowly. A signal that spikes
    and instantly clears reads as noise; one that spikes and lingers is real."""

    def __init__(self, up: float = 0.35, down: float = 0.08) -> None:
        self.v, self.up, self.down = 0.0, up, down

    def __call__(self, x: float) -> float:
        a = self.up if x > self.v else self.down
        self.v += (x - self.v) * a
        return self.v


class Proctor:
    def __init__(self, show_mesh: bool = True) -> None:
        self.mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=3, refine_landmarks=True,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        )
        self.smooth = {k: Smooth() for k in WEIGHTS}
        self.episodes: list[Episode] = []
        self.current: Episode | None = None
        self.show_mesh = show_mesh
        self.fps = deque(maxlen=30)
        self.rows: list[dict] = []

    # ---------------- per-frame signals ----------------
    def measure(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        res = self.mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        faces = res.multi_face_landmarks or []

        raw = {"gaze": 0.0, "pose": 0.0, "absence": 0.0, "company": 0.0}
        info = {"faces": len(faces), "yaw": 0.0, "pitch": 0.0, "gaze": 0.0, "ear": 1.0, "eyes_shut": False}

        if not faces:
            raw["absence"] = 100.0
            return raw, info, None

        if len(faces) > 1:
            raw["company"] = 100.0

        lm = faces[0].landmark
        pts = np.array([(p.x * w, p.y * h) for p in lm], dtype=np.float64)

        # --- gaze: iris centre against the eye's own corner span -----------
        def eye_ratio(corners, iris) -> float:
            (x0, _), (x1, _) = pts[corners[0]], pts[corners[1]]
            cx = pts[iris][0]
            span = x1 - x0
            if abs(span) < 1e-6:
                return 0.0
            return ((cx - x0) / span) - 0.5      # 0 = centred

        gaze = (eye_ratio(L_EYE, L_IRIS) + eye_ratio(R_EYE, R_IRIS)) / 2.0
        info["gaze"] = gaze

        # --- eyelids: a closed eye makes the iris reading meaningless ------
        def ear(corners, lids) -> float:
            width = np.linalg.norm(pts[corners[1]] - pts[corners[0]])
            height = np.linalg.norm(pts[lids[0]] - pts[lids[1]])
            return height / width if width > 1e-6 else 1.0

        info["ear"] = (ear(L_EYE, L_LID) + ear(R_EYE, R_LID)) / 2.0
        info["eyes_shut"] = info["ear"] < EAR_CLOSED

        if not info["eyes_shut"]:
            raw["gaze"] = ramp(gaze, GAZE_DEADZONE, GAZE_FULL)

        # --- head pose via solvePnP ----------------------------------------
        focal = float(w)
        cam = np.array([[focal, 0, w / 2.0], [0, focal, h / 2.0], [0, 0, 1]], dtype=np.float64)
        ok, rvec, _ = cv2.solvePnP(
            PNP_3D, pts[PNP_IDX], cam, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE
        )
        if ok:
            rot, _ = cv2.Rodrigues(rvec)
            sy = math.sqrt(rot[0, 0] ** 2 + rot[1, 0] ** 2)
            pitch = math.degrees(math.atan2(-rot[2, 0], sy))
            yaw = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
            yaw = (yaw + 180) % 360 - 180
            if abs(yaw) > 90:                      # solvePnP sign flip near frontal
                yaw = (180 - abs(yaw)) * (1 if yaw > 0 else -1)
            info["yaw"], info["pitch"] = yaw, pitch
            raw["pose"] = max(ramp(yaw, YAW_DEADZONE, YAW_FULL),
                              ramp(pitch, PITCH_DEADZONE, PITCH_FULL))

        return raw, info, pts

    # ---------------- fusion ----------------
    def fuse(self, raw: dict) -> tuple[float, dict]:
        sig = {k: self.smooth[k](v) for k, v in raw.items()}
        base = sum(WEIGHTS[k] * sig[k] for k in WEIGHTS)
        peak = max(sig.values())
        boost = (((peak - BOOST_KNEE) / (100 - BOOST_KNEE)) ** BOOST_POWER) * BOOST_GAIN if peak > BOOST_KNEE else 0.0
        return max(0.0, min(100.0, base + boost)), sig

    def track_episode(self, t: float, score: float, sig: dict) -> None:
        drivers = {k for k, v in sig.items() if v >= 50}
        if self.current is None:
            if score >= EPISODE_ENTER:
                self.current = Episode(start=t, peak=score, drivers=set(drivers))
        else:
            self.current.peak = max(self.current.peak, score)
            self.current.drivers |= drivers
            if score < EPISODE_EXIT:
                self.current.end = t
                self.episodes.append(self.current)
                self.current = None

    # ---------------- overlay ----------------
    def draw(self, frame, pts, score, sig, info, t):
        h, w = frame.shape[:2]
        name, colour = band(score)

        if pts is not None and self.show_mesh:
            for i in range(0, len(pts), 3):
                cv2.circle(frame, tuple(pts[i].astype(int)), 1, (70, 90, 115), -1)
            for iris in (L_IRIS, R_IRIS):
                cv2.circle(frame, tuple(pts[iris].astype(int)), 4, ACCENT, 1, cv2.LINE_AA)
            for corners in (L_EYE, R_EYE):
                for c in corners:
                    cv2.circle(frame, tuple(pts[c].astype(int)), 2, (200, 210, 225), -1)
            nose = pts[1].astype(int)
            tip = (int(nose[0] + info["gaze"] * 420), int(nose[1] - info["pitch"] * 2.4))
            cv2.arrowedLine(frame, tuple(nose), tip, ACCENT, 2, cv2.LINE_AA, tipLength=0.25)

        panel = frame.copy()
        cv2.rectangle(panel, (0, 0), (w, 108), (16, 12, 8), -1)
        cv2.rectangle(panel, (0, h - 132), (w, h), (16, 12, 8), -1)
        cv2.addWeighted(panel, 0.78, frame, 0.22, 0, frame)

        cv2.putText(frame, f"{score:5.1f}", (22, 74), cv2.FONT_HERSHEY_DUPLEX, 2.1, colour, 3, cv2.LINE_AA)
        cv2.putText(frame, "/100", (196, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.62, DIM, 1, cv2.LINE_AA)
        cv2.putText(frame, name, (196, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.66, colour, 2, cv2.LINE_AA)

        # meter with band segments underneath
        mx, my, mw, mh = 330, 40, w - 360, 20
        prev = 0
        for limit, _, bcol in BANDS:
            x0 = mx + int(mw * prev / 100)
            x1 = mx + int(mw * min(limit, 100) / 100)
            cv2.rectangle(frame, (x0, my), (x1, my + mh), tuple(int(c * 0.30) for c in bcol), -1)
            prev = limit
        cv2.rectangle(frame, (mx, my), (mx + int(mw * score / 100), my + mh), colour, -1)
        cv2.rectangle(frame, (mx, my), (mx + mw, my + mh), (60, 70, 85), 1)
        for limit in (30, 60, 85):
            x = mx + int(mw * limit / 100)
            cv2.line(frame, (x, my - 4), (x, my + mh + 4), (95, 110, 130), 1)
            cv2.putText(frame, str(limit), (x - 8, my + mh + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.38, DIM, 1, cv2.LINE_AA)

        # per-signal bars
        y = h - 116
        for key in ("gaze", "pose", "absence", "company"):
            v = sig[key]
            cv2.putText(frame, f"{key:<8}{v:5.1f}", (22, y + 11), cv2.FONT_HERSHEY_SIMPLEX, 0.46, WHITE, 1, cv2.LINE_AA)
            bx = 168
            cv2.rectangle(frame, (bx, y), (bx + 240, y + 13), (40, 48, 60), -1)
            c = ACCENT if v < 55 else (127, 127, 238)
            cv2.rectangle(frame, (bx, y), (bx + int(240 * v / 100), y + 13), c, -1)
            cv2.putText(frame, f"w {WEIGHTS[key]:.2f}", (bx + 250, y + 11), cv2.FONT_HERSHEY_SIMPLEX, 0.4, DIM, 1, cv2.LINE_AA)
            y += 22

        # episode log
        cv2.putText(frame, "FLAGGED EPISODES", (w - 430, h - 116), cv2.FONT_HERSHEY_SIMPLEX, 0.44, DIM, 1, cv2.LINE_AA)
        shown = ([self.current] if self.current else []) + self.episodes[::-1]
        if not shown:
            cv2.putText(frame, "none", (w - 430, h - 94), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (120, 200, 130), 1, cv2.LINE_AA)
        for i, ep in enumerate(shown[:4]):
            cv2.putText(frame, ep.label(), (w - 430, h - 94 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, WHITE if ep.end else (127, 127, 238), 1, cv2.LINE_AA)

        fps = len(self.fps) / max(sum(self.fps), 1e-6)
        status = (f"faces {info['faces']}   yaw {info['yaw']:+5.1f}   pitch {info['pitch']:+5.1f}   "
                  f"gaze {info['gaze']:+.3f}   {'EYES SHUT' if info['eyes_shut'] else 'eyes open'}   "
                  f"{fps:4.1f} fps   t {t:5.1f}s")
        cv2.putText(frame, status, (22, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, DIM, 1, cv2.LINE_AA)
        return frame


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--record", metavar="FILE", help="also write an annotated mp4")
    ap.add_argument("--no-mesh", action="store_true")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"  Could not open camera {args.camera}. Try --camera 1.")
        return 1

    proctor = Proctor(show_mesh=not args.no_mesh)
    writer = None
    t0 = time.time()

    print("\n  Proctoring live.  q quit   m mesh   r reset\n")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            tick = time.time()
            t = tick - t0

            raw, info, pts = proctor.measure(frame)
            score, sig = proctor.fuse(raw)
            proctor.track_episode(t, score, sig)
            frame = proctor.draw(frame, pts, score, sig, info, t)

            proctor.rows.append({
                "t": round(t, 3), "score": round(score, 2), "band": band(score)[0],
                **{k: round(v, 2) for k, v in sig.items()},
                "faces": info["faces"], "yaw": round(info["yaw"], 2),
                "pitch": round(info["pitch"], 2), "gaze": round(info["gaze"], 4),
            })

            if args.record:
                if writer is None:
                    OUT.mkdir(parents=True, exist_ok=True)
                    path = OUT / args.record
                    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                             20.0, (frame.shape[1], frame.shape[0]))
                    print(f"  recording to {path}")
                writer.write(frame)

            cv2.imshow("proctoring - multi-signal fusion", frame)
            proctor.fps.append(time.time() - tick)

            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
            if k == ord("m"):
                proctor.show_mesh = not proctor.show_mesh
            if k == ord("r"):
                proctor.episodes.clear()
                proctor.current = None
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()

    if proctor.current:
        proctor.current.end = time.time() - t0
        proctor.episodes.append(proctor.current)

    OUT.mkdir(parents=True, exist_ok=True)
    if proctor.rows:
        with open(OUT / "signals.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(proctor.rows[0]))
            wr.writeheader()
            wr.writerows(proctor.rows)
    with open(OUT / "episodes.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["start_s", "end_s", "peak_score", "drivers"])
        for ep in proctor.episodes:
            wr.writerow([f"{ep.start:.2f}", f"{ep.end:.2f}" if ep.end else "",
                         f"{ep.peak:.1f}", "|".join(sorted(ep.drivers))])

    print(f"\n  {len(proctor.rows)} frames, {len(proctor.episodes)} episode(s)")
    for ep in proctor.episodes:
        print("   ", ep.label())
    print(f"  wrote {OUT / 'signals.csv'} and {OUT / 'episodes.csv'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
