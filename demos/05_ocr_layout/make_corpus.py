"""
A corpus of deliberately awkward pages, for testing and development.

    python make_corpus.py                 write all of them to corpus/
    python make_corpus.py --list          show what each one is for
    python make_corpus.py --only form     just the ones matching "form"
    python make_corpus.py --pdf           also bundle them into one PDF
    python make_corpus.py --check         run the pipeline over each and report

Every page here exists because something got it wrong at some point. They
are regression cases, not decoration:

  form       centred tick marks under left-aligned headers, mostly-empty
             cells. Broke run growth and anchor clustering.
  report     two prose columns, a KPI strip in a filled dark band, charts.
             Broke figure detection and the character grid.
  statement  dense numeric rows, right-aligned money, a running balance.
             The shape a flattening OCR silently corrupts.
  lab        reference ranges, out-of-range flags, indented sub-tests.
  prose      two columns of article text and a label/value block. Must
             yield NO tables; this is the false-positive case.
  mixed      a signature, a stamp, a margin stripe and a full-width rule,
             around one real chart and one real table.

Nothing here is real. Every name, figure, account and identifier is invented.
"""

from __future__ import annotations

import argparse
import math
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "corpus"
A4 = (1654, 2339)            # A4 at 200 dpi, what a rasterised PDF gives us

INK, BODY, MUTE, RULE = "#13181F", "#2A313B", "#5A6472", "#C9D2DE"
NAVY, TEAL, WARN = "#1B2A4A", "#2E9C8E", "#B8860B"


def F(size: int, bold: bool = False):
    for name in (["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def blank():
    img = Image.new("RGB", A4, "white")
    return img, ImageDraw.Draw(img)


def banner(d, title, right, sub=None):
    d.rectangle([0, 0, A4[0], 74], fill=NAVY)
    d.text((64, 25), title, font=F(21, True), fill="#FFFFFF")
    d.text((A4[0] - 560, 29), right, font=F(15), fill="#CFE0FF")
    if sub:
        d.text((64, 98), sub, font=F(14), fill=MUTE)


def table(d, x, y, cols, rows, *, head=NAVY, ruled=True, rh=40, head_h=40):
    """cols = [(label, width, align)] ; align in l c r"""
    total = sum(w for _, w, _ in cols)
    d.rectangle([x, y, x + total, y + head_h], fill=head)
    cx = x
    for label, w, align in cols:
        if align == "r":
            d.text((cx + w - 12, y + 11), label, font=F(14, True), fill="#FFFFFF", anchor="ra")
        elif align == "c":
            d.text((cx + w / 2, y + 11), label, font=F(14, True), fill="#FFFFFF", anchor="ma")
        else:
            d.text((cx + 12, y + 11), label, font=F(14, True), fill="#FFFFFF")
        cx += w
    yy = y + head_h
    for row in rows:
        cx = x
        for (_, w, align), cell in zip(cols, row):
            if ruled:
                d.rectangle([cx, yy, cx + w, yy + rh], outline=RULE, width=1)
            txt = str(cell)
            if txt:
                if align == "r":
                    d.text((cx + w - 12, yy + 11), txt, font=F(14), fill=BODY, anchor="ra")
                elif align == "c":
                    d.text((cx + w / 2, yy + 11), txt, font=F(14), fill=BODY, anchor="ma")
                else:
                    d.text((cx + 12, yy + 11), txt, font=F(14), fill=BODY)
            cx += w
        yy += rh
    return yy


def paragraph(d, x, y, lines, width_font=16, lead=27, fill=BODY):
    for i, line in enumerate(lines):
        d.text((x, y + i * lead), line, font=F(width_font), fill=fill)
    return y + len(lines) * lead


def scrawl(d, x, y, w=240, seed=3):
    rng = random.Random(seed)
    d.line([(x + i * (w / 26), y + rng.randint(-16, 16)) for i in range(27)],
           fill="#1A237E", width=3)


def stamp(d, x, y, text="RECEIVED", sub="VAN DER BERG OFFSHORE"):
    d.rectangle([x, y, x + 300, y + 96], outline="#C0392B", width=3)
    d.text((x + 150, y + 18), text, font=F(24, True), fill="#C0392B", anchor="ma")
    d.text((x + 150, y + 56), sub, font=F(12), fill="#C0392B", anchor="ma")


# ==========================================================================
# the pages
# ==========================================================================
def page_form(seed=1):
    """Centred ticks under left-aligned headers; mostly-empty cells."""
    rng = random.Random(seed)
    img, d = blank()
    banner(d, "VAN DER BERG OFFSHORE B.V.", "Goods Inward  |  Site 3  Rotterdam",
           f"Inspection & Receiving Record  ·  GRN-{rng.randint(10000,99999)}  ·  "
           f"{(date.today()-timedelta(days=rng.randint(1,30))).isoformat()}")

    y = table(d, 64, 150,
              [("Field", 420, "l"), ("Value", 400, "l"), ("Field", 330, "l"), ("Value", 380, "l")],
              [["Supplier", "Kestrel Marine Components", "PO number", "PO-88213-36"],
               ["Carrier", "DSV Road", "AWB / CMR", "CMR 0451927"],
               ["Packages", "6 pallets", "Gross weight", "2,148.5 kg"]],
              head="#334155", rh=38)

    d.text((64, y + 34), "Inspection checklist (to be completed by consignee)",
           font=F(17, True), fill=INK)

    cx = [64, 700, 860, 1010, 1180]
    cw = [636, 160, 150, 170, 410]
    yy = y + 70
    d.rectangle([64, yy, 1590, yy + 40], fill="#EDEFF3")
    for i, lab in enumerate(["Check", "OK", "Damage", "Shortage", "Remarks"]):
        d.text((cx[i] + 10, yy + 11), lab, font=F(15, True), fill=INK)

    rows = [("Seal no. intact (SL 448821)", 1, 0, 0, ""),
            ("Pallet count matches (6)", 1, 0, 0, ""),
            ("Outer packaging condition", 0, 1, 0, "P-02 corner crushed, contents OK"),
            ("Item count vs. list", 1, 0, 0, ""),
            ("Shortage against packing list", 0, 0, 1, "2 x gaskets short, claim raised"),
            ("Documents received", 1, 0, 0, "CI, PL, CMR, DNV certs")]
    yy += 40
    for name, ok, dmg, short, rem in rows:
        for i in range(5):
            d.rectangle([cx[i], yy, cx[i] + cw[i], yy + 46], outline="#9AA7B8", width=1)
        d.text((cx[0] + 10, yy + 14), name, font=F(15), fill="#143C8C")
        for i, flag in ((1, ok), (2, dmg), (3, short)):
            if flag:                                   # centred in its cell
                d.text((cx[i] + cw[i] / 2, yy + 13), "X", font=F(17, True), fill=WARN, anchor="ma")
        if rem:
            d.text((cx[4] + 10, yy + 14), rem, font=F(14), fill="#1A7A4A")
        yy += 46

    d.text((1150, yy + 24), "received 08/09 - 14:20  MdJ", font=F(15), fill="#1A7A4A")
    stamp(d, 620, yy + 70)
    scrawl(d, 160, yy + 120, seed=seed)
    d.text((160, yy + 150), "Authorised signature", font=F(13), fill=MUTE)
    return img


def page_report(seed=2):
    """Two prose columns, a KPI strip on a dark fill, and two charts."""
    rng = random.Random(seed)
    img, d = blank()
    banner(d, "NORTHWIND RENEWABLES PLC", "Annual Report FY2025  |  Confidential Draft v3.2")
    d.text((64, 118), "Annual Report & Accounts 2025", font=F(46, True), fill=NAVY)
    d.text((64, 184), "Financial year ended 31 March 2025 - Published 14 June 2025",
           font=F(17), fill=MUTE)

    d.rectangle([64, 232, 1590, 276], fill=NAVY)
    kpi = [("Revenue", "GBP 412.6m", "+18.4% YoY"), ("EBITDA", "GBP 138.9m", "margin 33.7%"),
           ("Installed capacity", "1,284 MW", "+212 MW added"), ("CO2 avoided", "1.92 Mt", "+0.31 Mt YoY")]
    for i, (lab, val, sub) in enumerate(kpi):
        x = 80 + i * 381
        d.text((x, 244), lab, font=F(16, True), fill="#FFFFFF")
        d.text((x, 292), val, font=F(31, True), fill=INK)
        d.text((x, 336), sub, font=F(14), fill=MUTE)

    left = ["1. Chair's Statement", "",
            "FY2025 was a year of disciplined growth. Revenue",
            "rose to GBP 412.6 million, driven primarily by the",
            "commissioning of the Severn Estuary offshore array",
            "(Phase II) and higher realised power prices under our",
            "corporate PPA book. Operating costs per",
            "megawatt-hour declined by 6.2%, reflecting the",
            "benefits of the predictive-maintenance programme",
            "rolled out across 41 onshore sites.", "",
            "The Board recommends a final dividend of 4.85p per",
            "share, bringing the total for the year to 7.20p."]
    right = ["2. Market Overview", "",
             "Wholesale electricity prices in Great Britain averaged",
             "GBP 78.40/MWh over the period, down from GBP",
             "96.10/MWh in FY2024 as gas prices normalised.",
             "Approximately 71% of our generation was sold under",
             "fixed-price or floor-protected contracts, insulating",
             "earnings from spot volatility.", "",
             "Capacity auctions cleared at GBP 63/kW/year, and we",
             "secured 940 MW of de-rated capacity for delivery",
             "from October 2027."]
    for lines, x in ((left, 64), (right, 860)):
        yy = 400
        for line in lines:
            if not line:
                yy += 13
                continue
            f = F(19, True) if line[0].isdigit() and line[1] == "." else F(16)
            d.text((x, yy), line, font=f, fill=INK if f.size > 17 else BODY)
            yy += 30 if f.size > 17 else 26

    # bar chart
    bx, by, bw, bh = 110, 820, 580, 300
    d.line([bx, by, bx, by + bh], fill="#333", width=2)
    d.line([bx, by + bh, bx + bw, by + bh], fill="#333", width=2)
    for i, v in enumerate([150, 212, 186, 254]):
        x = bx + 46 + i * 132
        d.rectangle([x, by + bh - v, x + 74, by + bh], fill=NAVY if i % 2 else "#4C7DBE")
        d.text((x + 37, by + bh + 10), f"Q{i+1}", font=F(13), fill=MUTE, anchor="ma")
    d.text((bx, by - 28), "Figure 1: Revenue by quarter (GBP m)", font=F(14, True), fill=INK)

    # line chart
    lx, ly, lw, lh = 880, 820, 600, 300
    d.line([lx, ly, lx, ly + lh], fill="#333", width=2)
    d.line([lx, ly + lh, lx + lw, ly + lh], fill="#333", width=2)
    d.line([(lx + i * (lw / 30), ly + lh - 70 - abs(math.sin(i / 4.0)) * 170) for i in range(31)],
           fill=NAVY, width=3)
    d.line([(lx + i * (lw / 30), ly + lh - 50 - i * 2.2) for i in range(31)], fill=TEAL, width=3)
    d.text((lx, ly - 28), "Figure 2: Spot vs PPA price (GBP/MWh)", font=F(14, True), fill=INK)

    y = table(d, 64, 1210,
              [("Segment", 420, "l"), ("FY2025", 190, "r"), ("FY2024", 190, "r"),
               ("EBITDA", 190, "r"), ("Capacity (MW)", 230, "r"), ("Avail. %", 160, "r")],
              [["Offshore Wind", "198.4", "151.2", "79.6", "540", "96.8"],
               ["Onshore Wind", "121.7", "118.9", "41.2", "412", "97.9"],
               ["Utility Solar", "71.3", "62.5", "22.9", "298", "99.1"],
               ["Battery Storage", "14.8", "6.1", "3.1", "34", "98.4"],
               ["Corporate / Other", "6.4", "9.8", "(7.9)", "-", "-"],
               ["Group total", "412.6", "348.5", "138.9", "1,284", "97.6"]], rh=38)
    d.text((64, y + 10), "* Restated. Figures in brackets denote losses. Availability is time-weighted.",
           font=F(13), fill=MUTE)
    return img


def page_statement(seed=3):
    """Dense numeric rows with a running balance."""
    rng = random.Random(seed)
    img, d = blank()
    banner(d, "MERIDIAN TRUST BANK", "Statement 114  |  01 Mar - 31 Mar 2025",
           "Account 8842 1190  ·  Sort 40-21-08  ·  GBP current account")
    rows, bal = [], 184203.55
    descs = ["BACS CREDIT NORTHWIND", "DD BRITISH GAS BUSINESS", "FPS OUT SUPPLIER 4412",
             "CARD PURCHASE SHELL 2291", "CHQ 004182", "BACS CREDIT KESTREL MARINE",
             "STANDING ORDER RENT", "FX SETTLEMENT EUR/GBP", "INTEREST PAID",
             "DD INSURANCE RENEWAL", "FPS IN CUSTOMER 7781", "CARD PURCHASE RAIL 0098"]
    for i in range(16):
        dt = date(2025, 3, 1) + timedelta(days=i * 2)
        amt = round(rng.uniform(-18000, 42000), 2)
        bal += amt
        rows.append([dt.strftime("%d %b"), rng.choice(descs),
                     f"{abs(amt):,.2f}" if amt < 0 else "",
                     f"{amt:,.2f}" if amt > 0 else "", f"{bal:,.2f}"])
    y = table(d, 64, 170,
              [("Date", 150, "l"), ("Description", 640, "l"), ("Paid out", 230, "r"),
               ("Paid in", 230, "r"), ("Balance", 276, "r")], rows, rh=38, ruled=False)
    d.line([64, y + 4, 1590, y + 4], fill=RULE, width=2)
    d.text((1150, y + 18), "Closing balance", font=F(16, True), fill=INK)
    d.text((1578, y + 18), f"{bal:,.2f}", font=F(16, True), fill=INK, anchor="ra")
    paragraph(d, 64, y + 90,
              ["Interest is calculated daily and applied monthly. Figures shown are in",
               "pounds sterling. Please report any discrepancy within 60 days."], 14, 24, MUTE)
    return img


def page_lab(seed=4):
    """Reference ranges, flags and indented sub-tests."""
    img, d = blank()
    banner(d, "CALDERWOOD DIAGNOSTICS", "Report 4471-B  |  Collected 03 Sep 2025",
           "Patient: A. Whitfield  ·  DOB 14/02/1979  ·  NHS 441 882 9013")
    rows = [["Haemoglobin", "g/L", "138", "130 - 170", ""],
            ["White cell count", "x10^9/L", "11.8", "4.0 - 11.0", "HIGH"],
            ["   Neutrophils", "x10^9/L", "8.4", "2.0 - 7.5", "HIGH"],
            ["   Lymphocytes", "x10^9/L", "2.6", "1.0 - 4.0", ""],
            ["   Eosinophils", "x10^9/L", "0.3", "0.0 - 0.5", ""],
            ["Platelets", "x10^9/L", "402", "150 - 400", "HIGH"],
            ["Sodium", "mmol/L", "139", "133 - 146", ""],
            ["Potassium", "mmol/L", "3.2", "3.5 - 5.3", "LOW"],
            ["Creatinine", "umol/L", "88", "59 - 104", ""],
            ["eGFR", "mL/min", "82", "> 90", "LOW"],
            ["CRP", "mg/L", "41.2", "< 5.0", "HIGH"]]
    y = table(d, 64, 170,
              [("Analyte", 520, "l"), ("Unit", 220, "l"), ("Result", 200, "r"),
               ("Reference range", 340, "l"), ("Flag", 216, "c")], rows, head=TEAL, rh=40)
    d.text((64, y + 26), "Interpretation", font=F(17, True), fill=INK)
    paragraph(d, 64, y + 60,
              ["Neutrophil-predominant leucocytosis with a raised CRP, consistent with an acute",
               "bacterial process. Mild hypokalaemia; suggest repeat with magnesium.",
               "eGFR marginally reduced against the previous result of 91 on 12 Jun 2025."])
    scrawl(d, 64, y + 220, seed=seed)
    d.text((64, y + 250), "Dr H. Vasquez, Consultant Haematologist", font=F(13), fill=MUTE)
    return img


def page_prose(seed=5):
    """No tables at all. The false-positive case."""
    img, d = blank()
    d.text((64, 70), "Grid balancing and the duck curve", font=F(38, True), fill=INK)
    d.text((64, 128), "A note on intraday price formation  ·  Research desk  ·  September 2025",
           font=F(15), fill=MUTE)
    d.line([64, 166, 1590, 166], fill=RULE, width=2)
    body = ["Solar output peaks around midday while demand peaks in the early",
            "evening, and the gap between the two is what the industry calls the",
            "duck curve. As penetration rises the belly of the duck deepens and",
            "the evening ramp steepens, so the system needs plant that can move",
            "quickly rather than plant that is merely cheap.",
            "",
            "Batteries address the ramp but not the duration. A two-hour asset",
            "shifts the evening peak and little else; shifting a weekend of low",
            "wind needs something closer to a hundred hours, and at that point",
            "the economics stop resembling storage and start resembling a",
            "conventional peaking plant with an unusual fuel.",
            "",
            "Interconnection helps where the weather is uncorrelated, which in",
            "practice means long distances. The correlation length for wind in",
            "north-west Europe is several hundred kilometres, so a link to a",
            "neighbour is often a link to the same weather."]
    side = ["Curtailment rose to 4.1 TWh in FY2025, most of it in Scotland",
            "behind the B6 boundary. Constraint payments followed, and the",
            "resulting debate about locational pricing has not been settled.",
            "",
            "The counterfactual matters: curtailing a wind farm is only a",
            "loss if the alternative was generating. Where the network is",
            "genuinely full, the alternative is not generating either."]
    paragraph(d, 64, 210, body, 17, 29)
    paragraph(d, 900, 210, side, 17, 29)

    d.text((64, 820), "Publication details", font=F(18, True), fill=INK)
    for i, (k, v) in enumerate([("Registered office", "1 Harbour Quay, Bristol BS1 4QA"),
                                ("Company number", "08812345"),
                                ("Auditor", "Pellerin & Hale LLP"),
                                ("Registrar", "Equiniti Limited"),
                                ("Research contact", "desk@example.invalid")]):
        d.text((64, 870 + i * 40), k, font=F(16), fill=MUTE)
        d.text((460, 870 + i * 40), v, font=F(16), fill=INK)
    return img


def page_mixed(seed=6):
    """Furniture that has caused false figures, around one real chart
    and one real table."""
    img, d = blank()
    d.rectangle([44, 0, 62, A4[1]], fill="#6E6E6E")          # margin stripe
    d.ellipse([36, 760, 76, 800], fill="#3A3A3A")            # bullet dots
    d.ellipse([36, 1700, 76, 1740], fill="#3A3A3A")
    d.rectangle([140, 120, 1600, 127], fill=NAVY)            # full-width rule
    d.text((140, 56), "Sustainability performance", font=F(32, True), fill=INK)

    lx, ly, lw, lh = 200, 220, 640, 300
    d.line([lx, ly, lx, ly + lh], fill="#333", width=2)
    d.line([lx, ly + lh, lx + lw, ly + lh], fill="#333", width=2)
    d.line([(lx + i * (lw / 30), ly + lh - 60 - abs(math.cos(i / 5.0)) * 180) for i in range(31)],
           fill=TEAL, width=3)
    d.text((lx, ly - 28), "Figure 1: Scope 1 and 2 emissions by quarter", font=F(14, True), fill=INK)

    y = table(d, 140, 600,
              [("Metric", 420, "l"), ("Unit", 240, "l"), ("FY25", 200, "r"),
               ("FY24", 200, "r"), ("Target", 300, "l")],
              [["Scope 1", "tCO2e", "4,812", "5,390", "0 (2030)"],
               ["Scope 2 (market)", "tCO2e", "1,205", "1,644", "0 (2028)"],
               ["Scope 3", "tCO2e", "211,470", "188,020", "50% cut"],
               ["LTIFR", "per 1m hrs", "0.41", "0.58", "0.30"],
               ["Women in senior roles", "%", "38", "33", "40"],
               ["Biodiversity net gain", "%", "+14", "+9", "+10"]], head=TEAL, rh=40)

    paragraph(d, 140, y + 40,
              ["Scope 3 rose 12.5% on record construction volume, but intensity per MW",
               "installed fell from 1,042 to 987 tCO2e. Predictive-maintenance savings are",
               "measured against a baseline adjusted for fleet size; see Note 7."])
    stamp(d, 1100, y + 170, "VERIFIED", "DNV ASSURANCE 2025")
    scrawl(d, 200, y + 230, seed=seed)
    d.text((200, y + 262), "Independent assurance signature", font=F(13), fill=MUTE)
    d.text((140, A4[1] - 70), "Registered in England & Wales no. 08812345 - 1 Harbour Quay, Bristol BS1 4QA",
           font=F(13), fill=MUTE)
    return img


PAGES = {
    "form":      (page_form,      "centred ticks, mostly-empty cells, stamp and signature"),
    "report":    (page_report,    "two prose columns, dark KPI band, two charts, segment table"),
    "statement": (page_statement, "dense numeric rows, right-aligned money, running balance"),
    "lab":       (page_lab,       "reference ranges, flags, indented sub-tests"),
    "prose":     (page_prose,     "no tables at all: the false-positive case"),
    "mixed":     (page_mixed,     "margin stripe, rule, stamp, signature, one chart, one table"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="substring of the page name")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pdf", action="store_true", help="also write corpus/corpus.pdf")
    ap.add_argument("--check", action="store_true", help="run the pipeline and report what it finds")
    args = ap.parse_args()

    if args.list:
        print()
        for name, (_, why) in PAGES.items():
            print(f"  {name:<10} {why}")
        print()
        return 0

    names = [n for n in PAGES if not args.only or args.only.lower() in n]
    if not names:
        print(f"  nothing matches {args.only!r}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    made = []
    for i, name in enumerate(names):
        fn, why = PAGES[name]
        img = fn(seed=i + 1)
        path = OUT / f"{name}.png"
        img.save(path)
        made.append((name, path, img))
        print(f"  {path.relative_to(Path(__file__).parent)}   {why}")

    if args.pdf and made:
        pdf = OUT / "corpus.pdf"
        first = made[0][2]
        first.save(pdf, save_all=True, append_images=[m[2] for m in made[1:]], resolution=200)
        print(f"  {pdf.relative_to(Path(__file__).parent)}   all {len(made)} pages, for the PDF path")

    if args.check:
        import layout as L
        print("\n  running the pipeline over each page\n")
        import os
        engine, _ = L.load_engine(prefer=os.environ.get("OCR_ENGINE") or "tesseract")
        print(f"  engine: {engine.name}\n")
        print("  page        boxes  lines  cols  tables  figures  conf")
        for name, path, _ in made:
            b = engine(str(path))
            a = L.analyse(b)
            t = L.detect_tables(b)
            f = L.detect_figures(str(path), b, t)
            print("  %-10s  %5d  %5d  %4d  %6d  %7d  %.3f"
                  % (name, a["boxes"], a["lines"], a["columns"], len(t), len(f), a["mean_conf"]))
            for x in t:
                print("                 table %dx%d  %s" % (len(x["rows"]), x["cols"], x["rows"][0][:5]))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
