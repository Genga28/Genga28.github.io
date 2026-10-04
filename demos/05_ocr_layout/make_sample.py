"""
Builds a deliberately awkward page: two text columns, a right-aligned figures
table, a sidebar, and a footer. Exactly the shape where reading-order OCR
interleaves the columns and silently produces a document that parses fine and
means something else.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


LEFT_COL = [
    "CLINICAL SUMMARY",
    "",
    "Patient presented with a three day history of",
    "intermittent chest discomfort, worse on exertion",
    "and relieved by rest. No radiation to the jaw or",
    "left arm was reported at the time of admission.",
    "",
    "Baseline observations were within normal limits",
    "on arrival. Troponin was negative at zero and at",
    "six hours. Resting ECG showed sinus rhythm with",
    "no acute ST segment changes.",
    "",
    "A stress test was scheduled for the following",
    "morning and the patient was kept under",
    "observation overnight on the cardiology ward.",
]

RIGHT_COL = [
    "MEDICATION ON DISCHARGE",
    "",
    "Aspirin 75 mg once daily, oral.",
    "Atorvastatin 40 mg nightly, oral.",
    "Bisoprolol 2.5 mg once daily, titrate to",
    "heart rate as tolerated.",
    "",
    "FOLLOW UP",
    "",
    "Cardiology outpatient clinic in six weeks.",
    "Repeat lipid profile before that appointment.",
    "Primary care review in two weeks for blood",
    "pressure and tolerance of the beta blocker.",
    "",
    "Advised to return immediately if the pain",
    "recurs at rest or lasts beyond fifteen minutes.",
]

CHARGES = [
    ("Cardiology consultation", "1", "2,400", "2,400"),
    ("Troponin I, serial", "2", "1,150", "2,300"),
    ("ECG, 12 lead", "3", "500", "1,500"),
    ("Lipid profile", "1", "980", "980"),
    ("Ward bed, 1 night", "1", "4,200", "4,200"),
    ("Pharmacy, discharge pack", "1", "1,640", "1,640"),
]


def build(path: Path, seed: int | None = None) -> Path:
    rng = random.Random(seed)
    W, H = 1240, 1754          # A4 at 150 dpi (210x297mm), so the sheet is a real page
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    h1, h2, lbl, body, mono, small = (
        _font(30, True), _font(17, True), _font(14), _font(15), _font(15), _font(13)
    )
    ink, grey, line = "#111418", "#5A6472", "#D7DDE5"
    M, GUTTER = 64, 40
    col_w = (W - M * 2 - GUTTER) // 2

    # header
    d.rectangle([0, 0, W, 7], fill="#0F62FE")
    d.text((M, 40), "MERIDIAN HEALTH CENTRE", font=h1, fill=ink)
    d.text((M, 82), "Discharge summary and itemised account", font=lbl, fill=grey)

    ref = f"DS-{rng.randint(10000, 99999)}"
    when = (date.today() - timedelta(days=rng.randint(1, 30))).isoformat()
    for i, (k, v) in enumerate([("Ref", ref), ("Discharged", when), ("Ward", "Cardiology 3B")]):
        d.text((W - M - 250, 44 + i * 22), f"{k}:", font=small, fill=grey)
        d.text((W - M - 170, 44 + i * 22), v, font=small, fill=ink)

    d.line([M, 128, W - M, 128], fill=line, width=2)

    # two columns, same vertical band: this is what breaks reading order
    y_start = 158
    for col, (x, lines) in enumerate(
        ((M, LEFT_COL), (M + col_w + GUTTER, RIGHT_COL))
    ):
        y = y_start
        for text in lines:
            if not text:
                y += 12
                continue
            f = h2 if text.isupper() and len(text) < 40 else body
            d.text((x, y), text, font=f, fill=ink if f is h2 else "#2A313B")
            y += 26 if f is h2 else 23

    # column rule, so a human sees the corridor the algorithm has to find
    rule_x = M + col_w + GUTTER // 2
    d.line([rule_x, y_start, rule_x, y_start + 470], fill="#E8ECF2", width=1)

    # charges table, right-aligned numbers
    ty = 700
    d.text((M, ty), "ITEMISED CHARGES", font=h2, fill=ink)
    ty += 34
    d.rectangle([M, ty, W - M, ty + 32], fill="#F1F4F9")
    for label, x, anchor in (
        ("Description", M + 12, "la"), ("Qty", 700, "ra"),
        ("Unit", 860, "ra"), ("Amount", W - M - 12, "ra"),
    ):
        d.text((x, ty + 8), label, font=small, fill="#3A424E", anchor=anchor)

    ty += 42
    total = 0
    for desc, qty, unit, amount in CHARGES:
        d.text((M + 12, ty), desc, font=body, fill="#2A313B")
        d.text((700, ty), qty, font=mono, fill="#2A313B", anchor="ra")
        d.text((860, ty), unit, font=mono, fill="#2A313B", anchor="ra")
        d.text((W - M - 12, ty), amount, font=mono, fill=ink, anchor="ra")
        total += int(amount.replace(",", ""))
        ty += 30

    d.line([M, ty + 6, W - M, ty + 6], fill=line, width=1)
    ty += 22
    tax = round(total * 0.05)
    for label, value, bold in (
        ("Subtotal", total, False), ("GST 5%", tax, False), ("Total payable", total + tax, True)
    ):
        f = _font(17, True) if bold else body
        d.text((860, ty), f"{label}:", font=f, fill=ink, anchor="ra")
        d.text((W - M - 12, ty), f"{value:,}", font=f, fill=ink, anchor="ra")
        ty += 30

    # sidebar box, floats beside the footer text
    box_top = ty + 40
    d.rectangle([W - M - 360, box_top, W - M, box_top + 150], outline=line, width=2)
    d.text((W - M - 344, box_top + 16), "PAYMENT", font=h2, fill=ink)
    for i, text in enumerate([
        "Due within 21 days of discharge.",
        "Bank: Meridian Trust, A/C 8842 1190",
        "IFSC MTBI0004421",
        "Quote the reference above.",
    ]):
        d.text((W - M - 344, box_top + 48 + i * 22), text, font=small, fill="#2A313B")

    for i, text in enumerate([
        "This summary was produced for demonstration purposes.",
        "All names, figures and identifiers on this page are fabricated.",
        "No part of it corresponds to a real patient or a real account.",
    ]):
        d.text((M, box_top + 20 + i * 22), text, font=small, fill=grey)

    d.line([M, H - 70, W - M, H - 70], fill=line, width=1)
    d.text((M, H - 54), f"Page 1 of 1   |   {ref}   |   generated {date.today().isoformat()}",
           font=small, fill=grey)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


if __name__ == "__main__":
    out = build(Path(__file__).parent / "uploads" / "sample.png")
    print(f"wrote {out}")
