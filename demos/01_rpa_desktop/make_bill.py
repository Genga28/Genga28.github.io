"""
Generates a fake medical bill (PNG + sidecar JSON) and the one-page website
that serves it. Run by rpa_bill_to_excel.py; also runnable on its own.

The bill is generated rather than shipped so the OCR target is always crisp
and nothing here resembles a real person's medical record.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
SITE = HERE / "site"

# The Download button is painted in this exact colour. The RPA script finds it
# on screen by colour rather than by template match, which makes the click
# immune to browser zoom, DPI scaling and theme. Fiducial targeting: the same
# idea as a Sikuli/Lackey image anchor, just far more robust to record with.
ANCHOR = "#FF00AA"

FIRST = ["Aarav", "Divya", "Karthik", "Meera", "Rohan", "Sanjana", "Vikram", "Priya"]
LAST = ["Iyer", "Nair", "Rao", "Sharma", "Menon", "Pillai", "Reddy", "Krishnan"]

CATALOGUE = [
    ("Consultation - General Medicine", 1, 650),
    ("Complete Blood Count (CBC)", 1, 420),
    ("Lipid Profile", 1, 980),
    ("Chest X-Ray PA view", 1, 1150),
    ("ECG - 12 lead", 1, 500),
    ("Room charges - Semi private", 2, 2400),
    ("Pharmacy - Amoxicillin 500mg", 10, 18),
    ("Pharmacy - Pantoprazole 40mg", 7, 24),
    ("Nursing care", 2, 800),
    ("Ultrasound - Abdomen", 1, 1750),
]


def _font(size: int, bold: bool = False):
    """Windows ships Arial; fall back to PIL's bitmap font anywhere else."""
    for name in (["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_bill(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    patient = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    items = rng.sample(CATALOGUE, k=rng.randint(4, 6))

    lines = []
    for desc, qty, rate in items:
        qty = qty if qty > 1 else rng.randint(1, 3)
        lines.append({"description": desc, "qty": qty, "rate": rate, "amount": qty * rate})

    subtotal = sum(l["amount"] for l in lines)
    tax = round(subtotal * 0.05)

    return {
        "bill_no": f"MH-{rng.randint(100000, 999999)}",
        "date": (date.today() - timedelta(days=rng.randint(0, 20))).isoformat(),
        "patient": patient,
        "age": rng.randint(21, 78),
        "sex": rng.choice(["M", "F"]),
        "doctor": f"Dr. {rng.choice(FIRST)} {rng.choice(LAST)}",
        "hospital": "Meridian Health Centre",
        "lines": lines,
        "subtotal": subtotal,
        "tax": tax,
        "total": subtotal + tax,
    }


def render(bill: dict, path: Path) -> None:
    W, H = 900, 1180
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    h1, h2, body, small, mono = _font(34, True), _font(19, True), _font(19), _font(16), _font(19)
    ink, grey = "#111111", "#555555"
    M = 60

    d.rectangle([0, 0, W, 8], fill="#0F62FE")
    d.text((M, 46), bill["hospital"], font=h1, fill=ink)
    d.text((M, 92), "14 Ring Road, Coimbatore 641014  |  +91 422 555 0100", font=small, fill=grey)
    d.line([M, 130, W - M, 130], fill="#DDDDDD", width=2)

    d.text((M, 158), "TAX INVOICE", font=h2, fill=ink)

    # Two-column header block. Labels are deliberately plain words so the OCR
    # regexes in the RPA script have something stable to anchor on.
    left = [("Bill No", bill["bill_no"]), ("Date", bill["date"]), ("Doctor", bill["doctor"])]
    right = [("Patient", bill["patient"]), ("Age", str(bill["age"])), ("Sex", bill["sex"])]
    for i, (k, v) in enumerate(left):
        y = 200 + i * 32
        d.text((M, y), f"{k}:", font=small, fill=grey)
        d.text((M + 110, y), v, font=body, fill=ink)
    for i, (k, v) in enumerate(right):
        y = 200 + i * 32
        d.text((W // 2 + 20, y), f"{k}:", font=small, fill=grey)
        d.text((W // 2 + 130, y), v, font=body, fill=ink)

    # Line items
    ty = 330
    d.rectangle([M, ty, W - M, ty + 38], fill="#F2F4F8")
    for label, x in (("Description", M + 14), ("Qty", 560), ("Rate", 650), ("Amount", 760)):
        d.text((x, ty + 10), label, font=small, fill=ink)

    y = ty + 52
    for line in bill["lines"]:
        d.text((M + 14, y), line["description"], font=body, fill=ink)
        d.text((575, y), str(line["qty"]), font=mono, fill=ink)
        d.text((650, y), f"{line['rate']:,}", font=mono, fill=ink)
        d.text((760, y), f"{line['amount']:,}", font=mono, fill=ink)
        y += 36

    y += 14
    d.line([M, y, W - M, y], fill="#DDDDDD", width=2)
    y += 18
    for label, value, bold in (
        ("Subtotal", bill["subtotal"], False),
        ("GST 5%", bill["tax"], False),
        ("Total", bill["total"], True),
    ):
        f = _font(21, True) if bold else body
        d.text((610, y), f"{label}:", font=f, fill=ink)
        d.text((760, y), f"INR {value:,}", font=f, fill=ink)
        y += 34

    d.text((M, H - 90), "Computer generated invoice. Sample data for demonstration only.",
           font=small, fill=grey)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Meridian Health Centre - Patient Billing</title>
<style>
  body {{ margin:0; font:16px/1.6 system-ui, "Segoe UI", sans-serif; background:#eef1f6; color:#111; }}
  header {{ background:#0F62FE; color:#fff; padding:18px 40px; font-size:20px; font-weight:600; }}
  .wrap {{ max-width:1000px; margin:28px auto; padding:0 24px; }}
  .card {{ background:#fff; border-radius:10px; padding:26px; box-shadow:0 2px 14px rgba(0,0,0,.08); }}
  .row {{ display:flex; gap:26px; align-items:flex-start; flex-wrap:wrap; }}
  .meta {{ flex:1; min-width:260px; }}
  .meta dt {{ color:#666; font-size:14px; }}
  .meta dd {{ margin:0 0 12px; font-weight:600; }}
  img {{ max-width:420px; border:1px solid #ddd; border-radius:6px; }}
  /* The RPA script clicks this by colour. Do not restyle the background. */
  .dl {{
    display:inline-block; margin-top:20px; padding:20px 44px;
    background:{anchor}; color:#fff; font-size:20px; font-weight:700;
    border-radius:8px; text-decoration:none; letter-spacing:.3px;
  }}
</style>
<header>Meridian Health Centre &mdash; Patient Billing Portal</header>
<div class="wrap">
  <div class="card">
    <h2 style="margin-top:0">Invoice {bill_no}</h2>
    <div class="row">
      <img src="{png}" alt="Invoice preview">
      <dl class="meta">
        <dt>Patient</dt><dd>{patient}</dd>
        <dt>Date</dt><dd>{date}</dd>
        <dt>Attending</dt><dd>{doctor}</dd>
        <dt>Amount due</dt><dd>INR {total:,}</dd>
      </dl>
    </div>
    <a class="dl" href="{png}" download="{png}">Download bill</a>
  </div>
</div>
"""


def generate(seed: int | None = None) -> tuple[dict, Path]:
    """Write site/bill.png, site/bill.json and site/index.html. Returns (bill, png_path)."""
    bill = build_bill(seed)
    png = SITE / f"{bill['bill_no']}.png"
    render(bill, png)
    (SITE / "bill.json").write_text(json.dumps(bill, indent=2), encoding="utf-8")
    (SITE / "index.html").write_text(
        PAGE.format(anchor=ANCHOR, png=png.name, **bill), encoding="utf-8"
    )
    return bill, png


if __name__ == "__main__":
    b, p = generate()
    print(f"bill  {b['bill_no']}  total INR {b['total']:,}")
    print(f"png   {p}")
    print(f"page  {SITE / 'index.html'}")
