"""
Turn any photo into the two images the site needs.

    python tools/prep_photo.py "C:\\path\\to\\photo.jpg"
    python tools/prep_photo.py photo.jpg --no-og          # skip the share card

Produces:
    assets/img/genga.jpg   1000x1250, 4:5, cropped around your face
    assets/img/og.png      1200x630 LinkedIn / Twitter share card

Why not just crop the middle: on a portrait photo the face usually sits in the
upper third, so a centred crop frames your collarbone. This finds the face with
MediaPipe and crops around it, which also means the circular avatar on mobile
lands on your face instead of your shirt.

Run it from the repo root with the demos venv:
    demos\\.venv\\Scripts\\python.exe tools\\prep_photo.py photo.jpg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "assets" / "img"

PORTRAIT = (1000, 1250)     # 4:5, matches the hero frame
OG = (1200, 630)            # what LinkedIn and Twitter want

BG = (10, 13, 18)
INK = (238, 243, 250)
MUTED = (152, 166, 185)
BLUE = (122, 184, 255)
VIOLET = (180, 155, 245)
PINK = (244, 155, 184)


def font(size: int, bold: bool = False):
    for name in (["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------
def find_face(img: Image.Image):
    """Return the face box (cx, cy, w, h) in pixels, or None.

    The box matters as much as the centre: crop height is derived from face
    height, which is what reliably keeps a table, a plate and a lunch out of
    frame regardless of how the original was composed.

    MediaPipe first, then OpenCV's Haar cascade, then give up. All optional.
    """
    try:
        import numpy as np
        import mediapipe as mp

        rgb = np.array(img.convert("RGB"))
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.4
        ) as fd:
            res = fd.process(rgb)
        if res.detections:
            # Largest detection: the subject, not someone at the next table.
            best = max(res.detections, key=lambda d: d.location_data.relative_bounding_box.width)
            b = best.location_data.relative_bounding_box
            fw, fh = b.width * img.width, b.height * img.height
            cx = (b.xmin + b.width / 2) * img.width
            cy = (b.ymin + b.height / 2) * img.height
            print(f"  mediapipe: face at ({cx:.0f}, {cy:.0f}), {fw:.0f}x{fh:.0f}px")
            return cx, cy, fw, fh
    except Exception as exc:
        print(f"  mediapipe unavailable ({type(exc).__name__})")

    try:
        import cv2
        import numpy as np

        grey = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(grey, 1.1, 5, minSize=(80, 80))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            print(f"  opencv: face at ({x + w / 2:.0f}, {y + h / 2:.0f}), {w}x{h}px")
            return x + w / 2, y + h / 2, float(w), float(h)
    except Exception:
        pass

    print("  no face detected, falling back to the upper-third rule")
    return None


def crop_to(img: Image.Image, size: tuple[int, int], face=None,
            zoom: float = 4.2, headroom: float = 0.40):
    """Crop a headshot around `face`, then resize to `size`.

    `zoom` is crop height as a multiple of face height. Around 3.1 gives head
    and shoulders, which is what cuts off a table in front of the subject.
    Much above 3.5 and a plate on the table creeps back into frame. `headroom` is where the face centre sits vertically in the
    result: 0.40 puts it slightly above centre, the way portraits are framed.

    With no face, fall back to an aspect-only crop biased toward the top,
    since in a portrait photo the head is almost never in the middle.
    """
    target = size[0] / size[1]
    w, h = img.size

    if face:
        cx, cy, _, fh = face
        crop_h = min(h, fh * zoom)
        crop_w = crop_h * target
        if crop_w > w:                       # narrow image: width is the limit
            crop_w = w
            crop_h = crop_w / target
    elif w / h > target:
        crop_w, crop_h = h * target, h
        cx, cy = w / 2, h * 0.33
    else:
        crop_w, crop_h = w, w / target
        cx, cy = w / 2, h * 0.33

    left = int(round(cx - crop_w / 2))
    top = int(round(cy - crop_h * headroom))
    left = max(0, min(left, w - int(crop_w)))
    top = max(0, min(top, h - int(crop_h)))

    box = (left, top, left + int(crop_w), top + int(crop_h))
    return img.crop(box).resize(size, Image.LANCZOS)


# --------------------------------------------------------------------------
def make_og(portrait: Image.Image, name: str, title: str, out: Path, face=None) -> None:
    """The card LinkedIn shows when the link is pasted. Without this the post
    renders as a bare blue link and gets scrolled past."""
    card = Image.new("RGB", OG, BG)
    d = ImageDraw.Draw(card)

    # soft colour wash, same palette as the site
    glow = Image.new("RGB", (OG[0] // 4, OG[1] // 4), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-40, -60, 150, 120], fill=(34, 58, 96))
    gd.ellipse([120, -30, 260, 110], fill=(56, 42, 92))
    card.paste(glow.resize(OG, Image.LANCZOS).filter(ImageFilter.GaussianBlur(70)), (0, 0))

    # photo on the right, feathered into the background
    ph = crop_to(portrait, (470, 630), face=face, zoom=2.9, headroom=0.40)
    mask = Image.new("L", (470, 630), 255)
    md = ImageDraw.Draw(mask)
    for i in range(170):                       # horizontal fade on the left edge
        md.line([(i, 0), (i, 630)], fill=int(255 * (i / 170) ** 1.4))
    card.paste(ph, (OG[0] - 470, 0), mask)

    # accent rule
    for i, c in enumerate((BLUE, VIOLET, PINK)):
        d.rectangle([64 + i * 46, 96, 64 + i * 46 + 38, 100], fill=c)

    d.text((64, 140), name, font=font(74, True), fill=INK)
    d.text((64, 232), title, font=font(34), fill=BLUE)

    for i, line in enumerate([
        "Voice agents, document automation and",
        "real-time video analysis.",
    ]):
        d.text((64, 306 + i * 44), line, font=font(31), fill=MUTED)

    stats = [("3+", "years"), ("~5K", "docs / day"), ("10", "systems")]
    x = 64
    for value, label in stats:
        d.text((x, 434), value, font=font(44, True), fill=INK)
        d.text((x, 490), label, font=font(24), fill=MUTED)
        x += 150

    d.text((64, 560), "genga28.github.io", font=font(27), fill=VIOLET)

    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out, "PNG", optimize=True)


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="any photo of you, any size")
    ap.add_argument("--name", default="Genga K")
    ap.add_argument("--title", default="Applied AI Engineer")
    ap.add_argument("--no-og", action="store_true", help="skip the share card")
    ap.add_argument("--zoom", type=float, default=3.1,
                    help="crop height as a multiple of face height. 3.2 = tight head and "
                         "shoulders, 5.5 = looser. Lower this if anything unwanted is still in frame.")
    ap.add_argument("--headroom", type=float, default=0.40,
                    help="where the face sits vertically, 0.3 high and 0.5 centred")
    args = ap.parse_args()

    src = Path(args.photo).expanduser()
    if not src.exists():
        print(f"  No such file: {src}")
        return 1

    img = Image.open(src)
    img = img.convert("RGB")
    print(f"\n  source {src.name}  {img.width}x{img.height}  {src.stat().st_size // 1024} KB")

    face = find_face(img)
    portrait = crop_to(img, PORTRAIT, face, args.zoom, args.headroom)

    IMG.mkdir(parents=True, exist_ok=True)
    jpg = IMG / "genga.jpg"
    portrait.save(jpg, "JPEG", quality=88, optimize=True, progressive=True)
    print(f"  wrote {jpg.relative_to(ROOT)}  {PORTRAIT[0]}x{PORTRAIT[1]}  {jpg.stat().st_size // 1024} KB")

    if not args.no_og:
        og = IMG / "og.png"
        make_og(img, args.name, args.title, og, face)
        print(f"  wrote {og.relative_to(ROOT)}  {OG[0]}x{OG[1]}  {og.stat().st_size // 1024} KB")

    print("\n  Next:")
    print("    git add assets/img && git commit -m \"Add photo and share card\" && git push\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
