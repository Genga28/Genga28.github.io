"""
Generates a fake medical bill (PDF + PNG preview + sidecar JSON) and the
one-page portal that serves it. Run by rpa_bill_to_excel.py; also runnable
on its own.

The bill is generated rather than shipped so the OCR target is always crisp
and nothing here resembles a real person's medical record.

The portal deliberately puts the Download button below the fold. A real
billing portal buries it under notices and an activity table, and a bot that
only looks at the visible screen has to scroll to find it. That scroll is
the interesting half of the demo, so the page is built to require it.
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

# Exactly five, because five line items become five rows in the workbook and
# that is what the typing stage is paced for.
LINES_PER_BILL = 5

FIRST = ["Aarav", "Divya", "Karthik", "Meera", "Rohan", "Sanjana", "Vikram", "Priya"]
LAST = ["Iyer", "Nair", "Rao", "Sharma", "Menon", "Pillai", "Reddy", "Krishnan"]

CATALOGUE = [
    ("Consultation - General Medicine", 1, 650),
    ("Complete Blood Count", 1, 420),
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
    """Tahoma first, Arial second, PIL's bitmap font anywhere else.

    Not an aesthetic choice. In Arial a capital I and a lowercase l are the
    same glyph, pixel for pixel, so "Iyer" comes back as "lyer" and no
    recogniser can do better without a name lexicon. Tahoma gives the capital
    I crossbars. Measured on the same line: Arial 'Meera lyer and Ill',
    Tahoma 'Meera Iyer and Ill', which is exactly right. Verdana fixes the
    name but then reads 'Ill' as 'III'.

    A document author picking a font whose letters are distinguishable is the
    real fix for this, and it is the one a billing team would make.
    """
    faces = ["tahomabd.ttf", "arialbd.ttf"] if bold else ["tahoma.ttf", "arial.ttf"]
    for name in faces:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_bill(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    patient = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    items = rng.sample(CATALOGUE, k=LINES_PER_BILL)

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


def render(bill: dict) -> Image.Image:
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

    # Two-column header block. Labels are deliberately plain words so the
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

    # Line items. The three numeric columns are right of a wide gap, which is
    # what lets the extractor take the last three tokens on a row and trust
    # that the rest is the description.
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
    return img


# A page of filler between the invoice card and the Download button. Twelve
# activity rows and three notices is roughly one and a half viewports on a
# laptop, so the button starts off screen on any sane window size and the bot
# has to go looking for it.
ACTIVITY = [
    ("2026-09-02", "MH-884120", "Outpatient consultation", "Settled", "1,430"),
    ("2026-08-26", "MH-881907", "Radiology - Chest X-Ray", "Settled", "1,150"),
    ("2026-08-19", "MH-879442", "Pathology panel", "Settled", "2,380"),
    ("2026-08-11", "MH-876015", "Pharmacy dispense", "Settled", "640"),
    ("2026-07-30", "MH-871338", "Day care - Infusion", "Settled", "4,900"),
    ("2026-07-22", "MH-868204", "Physiotherapy, 4 sessions", "Settled", "3,200"),
    ("2026-07-09", "MH-863771", "Outpatient consultation", "Settled", "650"),
    ("2026-06-28", "MH-859630", "Ultrasound - Abdomen", "Settled", "1,750"),
    ("2026-06-14", "MH-854119", "ECG and review", "Settled", "980"),
    ("2026-06-02", "MH-849885", "Vaccination - Influenza", "Settled", "1,100"),
    ("2026-05-21", "MH-845207", "Pathology - Lipid profile", "Settled", "980"),
    ("2026-05-08", "MH-840663", "Outpatient consultation", "Settled", "650"),
]

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Meridian Health Centre - Patient Billing</title>
<style>
  body {{ margin:0; font:16px/1.6 system-ui, "Segoe UI", sans-serif; background:#eef1f6; color:#111; }}
  header {{ background:#0F62FE; color:#fff; padding:18px 40px; font-size:20px; font-weight:600;
            position:sticky; top:0; }}
  .wrap {{ max-width:1000px; margin:28px auto 80px; padding:0 24px; }}
  .card {{ background:#fff; border-radius:10px; padding:26px; box-shadow:0 2px 14px rgba(0,0,0,.08);
           margin-bottom:26px; }}
  .row {{ display:flex; gap:26px; align-items:flex-start; flex-wrap:wrap; }}
  .meta {{ flex:1; min-width:260px; }}
  .meta dt {{ color:#666; font-size:14px; }}
  .meta dd {{ margin:0 0 12px; font-weight:600; }}
  img {{ max-width:420px; border:1px solid #ddd; border-radius:6px; }}
  h2 {{ margin-top:0; }}
  h3 {{ margin:0 0 14px; font-size:17px; color:#0F2B46; }}
  table {{ width:100%; border-collapse:collapse; font-size:15px; }}
  th {{ text-align:left; padding:9px 10px; background:#F2F5FA; color:#44506080;
        color:#445060; font-weight:600; border-bottom:1px solid #E2E8F0; }}
  td {{ padding:9px 10px; border-bottom:1px solid #EEF2F7; }}
  td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .ok {{ color:#0F7B4F; font-weight:600; }}
  .notice {{ border-left:3px solid #0F62FE; padding:2px 0 2px 14px; margin:0 0 16px; color:#445060; }}
  .foot {{ color:#6B7684; font-size:14px; }}
  /* The RPA script clicks this by colour. Do not restyle the background. */
  .dl {{
    display:inline-block; margin-top:8px; padding:20px 44px;
    background:{anchor}; color:#fff; font-size:20px; font-weight:700;
    border-radius:8px; text-decoration:none; letter-spacing:.3px;
  }}
</style>
<header>Meridian Health Centre &mdash; Patient Billing Portal</header>
<div class="wrap">

  <div class="card">
    <h2>Invoice {bill_no}</h2>
    <div class="row">
      <img src="{png}" alt="Invoice preview">
      <dl class="meta">
        <dt>Patient</dt><dd>{patient}</dd>
        <dt>Date</dt><dd>{date}</dd>
        <dt>Attending</dt><dd>{doctor}</dd>
        <dt>Amount due</dt><dd>INR {total:,}</dd>
      </dl>
    </div>
  </div>

  <div class="card">
    <h3>Account activity</h3>
    <table>
      <tr><th>Date</th><th>Reference</th><th>Description</th><th>Status</th><th class="n">Amount</th></tr>
      {activity}
    </table>
  </div>

  <div class="card">
    <h3>Notices</h3>
    <p class="notice">Statements are issued on the first working day of each month.
       Balances outstanding beyond 21 days attract a late settlement fee.</p>
    <p class="notice">Insurance pre-authorisation must be submitted before admission.
       Claims filed after discharge are processed as reimbursements and take longer.</p>
    <p class="notice">For a corrected invoice, raise a billing query from the account
       menu. Corrections are issued as a credit note against the original reference.</p>
    <p class="foot">This is a demonstration portal. Every name, reference and figure on
       this page is fabricated and corresponds to no real patient or account.</p>
  </div>

  <div class="card">
    <h3>Download</h3>
    <p class="foot">The invoice is issued as a PDF. Keep it for your insurer.</p>
    <a class="dl" href="{pdf}" download="{pdf}">Download bill</a>
  </div>

</div>
"""


def _activity_rows() -> str:
    return "\n      ".join(
        f'<tr><td>{d}</td><td>{ref}</td><td>{desc}</td>'
        f'<td class="ok">{status}</td><td class="n">{amt}</td></tr>'
        for d, ref, desc, status, amt in ACTIVITY
    )


def write_page(bill: dict, png_name: str, pdf_name: str) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "index.html").write_text(
        PAGE.format(anchor=ANCHOR, png=png_name, pdf=pdf_name,
                    activity=_activity_rows(), **bill),
        encoding="utf-8",
    )


def generate(seed: int | None = None) -> tuple[dict, Path]:
    """Write the PDF, the PNG preview, the sidecar and the page.

    Returns (bill, pdf_path). The PDF is the download target; the PNG is only
    the thumbnail on the page.
    """
    bill = build_bill(seed)
    SITE.mkdir(parents=True, exist_ok=True)

    img = render(bill)
    png = SITE / f"{bill['bill_no']}.png"
    pdf = SITE / f"{bill['bill_no']}.pdf"
    img.save(png)
    # No text layer by design: a hospital portal hands you a scan, and reading
    # it back is the part worth showing. 110 dpi puts the 900x1180 render on a
    # page about 8.2 by 10.7 inches.
    img.save(pdf, "PDF", resolution=110.0)

    (SITE / "bill.json").write_text(json.dumps(bill, indent=2), encoding="utf-8")
    write_page(bill, png.name, pdf.name)
    return bill, pdf


if __name__ == "__main__":
    b, p = generate()
    print(f"bill  {b['bill_no']}  total INR {b['total']:,}  ({len(b['lines'])} lines)")
    print(f"pdf   {p}")
    print(f"page  {SITE / 'index.html'}")
