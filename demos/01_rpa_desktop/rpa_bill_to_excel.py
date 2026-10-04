"""
Desktop RPA: open a billing portal, scroll until the download button comes
into view, click it by colour, read the downloaded PDF, then open a clean
Excel workbook and type the table in cell by cell.

    python rpa_bill_to_excel.py                       generated invoice
    python rpa_bill_to_excel.py --bill my_scan.pdf    your own document
    python rpa_bill_to_excel.py --runs 2 --no-open
    python rpa_bill_to_excel.py --no-excel            stop after extraction

Nothing here talks to a DOM or to Excel's object model. The bot screenshots
the screen, moves the real cursor and sends real keystrokes, which is the
technique you need when the target is a legacy desktop app with no API.

Three stages worth watching:

  scroll    the button starts below the fold, so a screen-only bot has to
            page down and re-look after every scroll
  extract   the download is a PDF with no text layer, so it is rasterised
            and OCR'd, and each row is checked with qty x rate = amount
  type      headers first, then five rows, Tab across and Enter to wrap,
            Shift+arrow to select the header, Ctrl+B to bold it

Safety: PyAutoGUI's failsafe is on. Slam the pointer into the top-left corner
of the screen to abort a run.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import numpy as np
import pyautogui
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from make_bill import ANCHOR, SITE, generate  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "output"
DOWNLOADS = Path.home() / "Downloads"

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

# Six columns, five rows. The columns are the shape a billing team actually
# wants: the bill identity repeated against each line, so the sheet can be
# filtered and pivoted without a join.
HEADERS = ["Bill No", "Date", "Patient", "Description", "Qty", "Amount"]


def log(step: str, msg: str) -> None:
    print(f"  [{step:^9}] {msg}", flush=True)


# --------------------------------------------------------------------------
# 1. serve the portal
# --------------------------------------------------------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int) -> socketserver.TCPServer:
    handler = type(
        "Quiet",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "log_message": lambda *a, **k: None,
            "__init__": lambda self, *a, **k: http.server.SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(SITE), **k
            ),
        },
    )
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# --------------------------------------------------------------------------
# 2. find the button on screen, by colour, scrolling until it appears
# --------------------------------------------------------------------------
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def find_anchor(colour: str, tol: int = 26, min_px: int = 900):
    """Return the centre of the largest on-screen blob of `colour`, or None.

    Screenshot -> per-channel distance mask -> trimmed centroid. Scale and DPI
    independent, unlike template matching, because a flat colour block stays
    the same colour at any zoom level.
    """
    shot = np.array(pyautogui.screenshot().convert("RGB")).astype(np.int16)
    target = np.array(hex_rgb(colour), dtype=np.int16)
    mask = (np.abs(shot - target).max(axis=2) <= tol)

    if mask.sum() < min_px:
        return None

    ys, xs = np.nonzero(mask)
    # Trim outliers so a stray antialiased pixel elsewhere cannot drag the centre.
    y0, y1 = np.percentile(ys, [2, 98])
    x0, x1 = np.percentile(xs, [2, 98])
    keep = (ys >= y0) & (ys <= y1) & (xs >= x0) & (xs <= x1)
    if keep.sum() < min_px:
        return None
    return int(xs[keep].mean()), int(ys[keep].mean()), int(keep.sum())


def scroll_to_anchor(colour: str, max_scrolls: int = 14, notches: int = 4):
    """Look, scroll, look again.

    A screen-only bot cannot know the button exists until it can see it, so
    the search is a loop over scroll positions rather than one screenshot.
    The cursor is parked over the page body first, because Windows delivers
    wheel events to whatever is under the pointer, not to the focused window.
    """
    w, h = pyautogui.size()
    pyautogui.moveTo(w // 2, h // 2, duration=0.3)

    for attempt in range(max_scrolls + 1):
        hit = find_anchor(colour)
        if hit:
            if attempt:
                log("scroll", f"button came into view after {attempt} scroll(s)")
            else:
                log("scroll", "button already visible, no scrolling needed")
            return hit
        if attempt == 0:
            log("scroll", "button is below the fold, scrolling to find it")
        # Three wheel notches at a time: enough to move, small enough that the
        # button cannot pass through the viewport between two screenshots.
        pyautogui.scroll(-notches * 100)
        time.sleep(0.45)

    # It may have been above the starting position. Go back to the top and
    # say so, rather than failing with a misleading message.
    pyautogui.hotkey("ctrl", "home")
    time.sleep(0.6)
    return find_anchor(colour)


# --------------------------------------------------------------------------
# 3. wait for the download
# --------------------------------------------------------------------------
def wait_for_download(name: str, since: float, timeout: float = 30.0) -> Path | None:
    stem, suffix = Path(name).stem, Path(name).suffix
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in DOWNLOADS.glob(f"{stem}*{suffix}"):
            if p.stat().st_mtime >= since - 2 and not p.with_suffix(".crdownload").exists():
                size = p.stat().st_size
                time.sleep(0.6)
                if p.exists() and p.stat().st_size == size and size > 0:
                    return p
        time.sleep(0.5)
    return None


# --------------------------------------------------------------------------
# 4. read the PDF
# --------------------------------------------------------------------------
HEADER_FIELDS = {
    "bill_no": r"Bill\s*No\.?\s*:?\s*([A-Z]{2}-\d{4,8})",
    "date": r"Date\s*:?\s*(\d{4}-\d{2}-\d{2})",
    "patient": r"Patient\s*:?\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
}


def rasterise(path: Path, dpi: int = 200) -> Image.Image:
    """PDF page 1 to an image. Plain images pass straight through."""
    if path.suffix.lower() != ".pdf":
        return Image.open(path)
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        return doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def ocr_text(img: Image.Image) -> str:
    import pytesseract

    # One Tesseract search, shared with the OCR studio, so there is a single
    # place to fix when an install path changes.
    sys.path.insert(0, str(HERE.parent / "05_ocr_layout"))
    from layout import find_tesseract

    exe = find_tesseract()
    if not exe:
        raise RuntimeError("tesseract binary not found")
    pytesseract.pytesseract.tesseract_cmd = exe
    # PSM 4, a single column of variable sizes, keeps the invoice's wide
    # numeric gutters intact. The default PSM 3 reflows them away.
    return pytesseract.image_to_string(img, config="--psm 4")


def _num(tok: str) -> int | None:
    return int(tok.replace(",", "")) if re.fullmatch(r"[\d,]+", tok) else None


def _misread_of(tok: str, value: int) -> bool:
    """Does `tok` look like `value` with one character misrecognised?

    Same digit count, at most one position different. Tight enough that an
    unrelated number cannot slip through, loose enough to catch the real
    failure: "1,150" came back as "4:150", which is the leading digit and the
    separator both wrong on one token.
    """
    seen = re.sub(r"[^0-9]", "", tok)
    want = str(value)
    return len(seen) == len(want) and sum(a != b for a, b in zip(seen, want)) <= 1


def parse_line_items(text: str) -> list[dict]:
    """Rows ending in rate and amount, with qty recovered where OCR lost it.

    Taking tokens from the right beats one regex here: the descriptions carry
    their own digits ("ECG - 12 lead", "Amoxicillin 500mg") and a lazy pattern
    grabs those instead.

    Qty is the fragile field. It is a single isolated glyph in a column of its
    own, which is the hardest thing on the page for a recogniser: across ten
    generated bills Tesseract read a lone "2" as "z" twice. Rather than keep a
    table of lookalikes, derive it. Rate and amount are multi-digit and come
    out clean, so when amount divides by rate the quotient is the quantity,
    and the division either works or it does not. No guessing either way.
    """
    out: list[dict] = []
    for raw in text.splitlines():
        toks = raw.split()
        if len(toks) < 4:
            continue
        rate, amount = _num(toks[-2]), _num(toks[-1])
        if not rate or not amount:
            continue

        desc = " ".join(toks[:-3]).strip(" .:-")
        if len(desc) < 4 or desc.lower().startswith(("subtotal", "gst", "total")):
            continue

        qty, recovered = _num(toks[-3]), False
        if qty is None or qty * rate != amount:
            # Bounded so a rate of 1 cannot make any amount look divisible.
            if amount % rate == 0 and 1 <= amount // rate <= 99:
                qty, recovered = amount // rate, True
        if not qty or qty * rate != amount:
            continue

        out.append({"description": desc, "qty": qty, "rate": rate, "amount": amount,
                    "checks": True, "recovered": recovered})
    return out


def recover_broken_amounts(text: str, have: list[dict]) -> list[dict]:
    """Rows the strict pass dropped because the amount token would not parse.

    Two of the three numbers are enough to reconstruct the third, but only
    with a guard: qty x rate alone would also "reconstruct" the hospital
    phone number into a line item. So the derived amount has to look like
    what the recogniser actually saw, digit for digit, before it is believed.
    """
    seen = {l["description"] for l in have}
    extra: list[dict] = []
    for raw in text.splitlines():
        toks = raw.split()
        if len(toks) < 4 or _num(toks[-1]) is not None:
            continue
        qty, rate = _num(toks[-3]), _num(toks[-2])
        if not qty or not rate or not 1 <= qty <= 99:
            continue
        amount = qty * rate
        if not _misread_of(toks[-1], amount):
            continue
        desc = " ".join(toks[:-3]).strip(" .:-")
        if len(desc) < 4 or desc in seen:
            continue
        extra.append({"description": desc, "qty": qty, "rate": rate,
                      "amount": amount, "checks": True, "recovered": True})
    return extra


# The arithmetic is the filter, not a warning. The shape test alone is far too
# generous: the hospital's own phone number, "+91 422 555 0100", ends in three
# numeric tokens and parses as a line item worth 422 x 555. Nothing on a real
# invoice satisfies qty x rate = amount by accident.


def read_bill(path: Path) -> tuple[dict, list[dict], str]:
    """Returns (header fields, line items, engine used)."""
    try:
        text = ocr_text(rasterise(path))
        header = {}
        for key, pattern in HEADER_FIELDS.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                header[key] = m.group(1).strip()
        lines = parse_line_items(text)
        broken = recover_broken_amounts(text, lines)
        if broken:
            # Back into document order; the recovered rows are appended, and a
            # row out of sequence in the workbook is its own kind of wrong.
            order = [" ".join(l.split()[:-3]).strip(" .:-") for l in text.splitlines()]
            lines = sorted(lines + broken,
                           key=lambda l: order.index(l["description"])
                           if l["description"] in order else len(order))
        if len(header) == 3 and len(lines) >= 3:
            fixed = sum(1 for l in lines if l["recovered"])
            log("verify", f"{len(lines)} rows satisfy qty x rate = amount"
                          + (f", {fixed} with the qty recovered from it" if fixed else ""))
            return header, lines, "tesseract"
        log("ocr", f"matched {len(header)}/3 header fields and {len(lines)} verified "
                   f"rows of {len(found)} candidates, falling back to the sidecar")
    except Exception as exc:
        log("ocr", f"tesseract unavailable ({type(exc).__name__}), using the sidecar")

    bill = json.loads((SITE / "bill.json").read_text(encoding="utf-8"))
    return (
        {"bill_no": bill["bill_no"], "date": bill["date"], "patient": bill["patient"]},
        [{**l, "checks": True, "recovered": False} for l in bill["lines"]],
        "sidecar-json",
    )


def to_rows(header: dict, lines: list[dict]) -> list[list[str]]:
    """One flat row per line item, in HEADERS order, all strings ready to type."""
    return [
        [
            header.get("bill_no", ""),
            header.get("date", ""),
            header.get("patient", ""),
            l["description"],
            str(l["qty"]),
            # No thousands separator: Excel should store a number, and a comma
            # in some locales is a decimal point.
            str(l["amount"]),
        ]
        for l in lines
    ]


# --------------------------------------------------------------------------
# 5. Excel, by keyboard
# --------------------------------------------------------------------------
def blank_workbook() -> Path:
    """A genuinely empty single-sheet workbook, named for this run.

    A fresh name every time, so a copy left open from the last run cannot
    trigger Excel's "already open, open read-only?" dialog mid-demo.
    """
    from openpyxl import Workbook

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"bills_{datetime.now():%H%M%S}.xlsx"
    wb = Workbook()
    wb.active.title = "Extracted"
    wb.save(path)
    return path


def focus_excel(path: Path, timeout: float = 45.0) -> bool:
    """Bring the workbook's window to the front and keep it there."""
    import pygetwindow as gw

    stem = path.stem
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in gw.getAllWindows():
            title = w.title or ""
            if stem in title and "Excel" in title:
                try:
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                except Exception:
                    # activate() raises on Windows when the foreground lock is
                    # held by another process. Minimise/restore steals it back.
                    try:
                        w.minimize()
                        w.restore()
                    except Exception:
                        pass
                time.sleep(1.0)
                return True
        time.sleep(0.6)
    return False


def type_cell(value: str, interval: float) -> None:
    """Type one cell and move right.

    The Delete before Tab is not decoration. Excel's AutoComplete offers the
    rest of a matching entry from the same column as selected text, and Tab
    accepts it; Delete clears the selection first. With nothing suggested the
    caret is at the end of the line and Delete does nothing.
    """
    pyautogui.write(value, interval=interval)
    pyautogui.press("delete")
    pyautogui.press("tab")


def type_into_excel(rows: list[list[str]], interval: float = 0.035) -> Path | None:
    path = blank_workbook()
    log("excel", f"opening a clean workbook: {path.name}")
    os.startfile(path)  # noqa: S606  - Windows only, this is the point of the demo

    if not focus_excel(path):
        log("excel", "could not find the Excel window; typing would go somewhere else")
        return path

    # Start from a known cell. Everything after this is relative, so one
    # wrong assumption about where the cursor is wrecks the whole sheet.
    pyautogui.hotkey("ctrl", "home")
    time.sleep(0.4)

    log("type", f"headers: {', '.join(HEADERS)}")
    for h in HEADERS:
        type_cell(h, interval)
    # Enter after a run of Tabs returns to the column the run started in, one
    # row down. That is why the whole table can be typed without ever naming
    # a cell reference.
    pyautogui.press("enter")

    for n, row in enumerate(rows, start=1):
        log("type", f"row {n}: " + " | ".join(row))
        for value in row:
            type_cell(value, interval)
        pyautogui.press("enter")

    last = len(rows) + 1                      # header is row 1
    log("type", f"total row with =SUM(F2:F{last})")
    for _ in range(4):                        # A -> E, by arrow key
        pyautogui.press("right")
    type_cell("Total", interval)
    pyautogui.write(f"=SUM(F2:F{last})", interval=interval)
    pyautogui.press("enter")

    # Formatting, still by keyboard. Shift+Right extends the selection one
    # cell at a time, which is visible on a recording in a way that a named
    # range is not.
    log("format", "bold the header, autofit the columns, save")
    pyautogui.hotkey("ctrl", "home")
    for _ in range(len(HEADERS) - 1):
        pyautogui.hotkey("shift", "right")
    pyautogui.hotkey("ctrl", "b")

    pyautogui.hotkey("ctrl", "home")
    pyautogui.hotkey("ctrl", "shift", "end")
    # Alt, H, O, I is Home > Format > AutoFit Column Width. Sent as separate
    # presses because it is a ribbon key sequence, not a chord.
    for key in ("alt", "h", "o", "i"):
        pyautogui.press(key)
        time.sleep(0.15)

    pyautogui.hotkey("ctrl", "home")
    pyautogui.hotkey("ctrl", "s")
    time.sleep(1.2)
    log("excel", f"saved {path}")
    return path


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def publish_own(path: Path) -> tuple[dict, Path]:
    """Put a real document into the portal instead of a generated one.

    The page still needs a thumbnail, so a PDF gets its first page rendered
    for the preview. The extractor does not care either way.
    """
    import shutil
    from make_bill import write_page

    SITE.mkdir(parents=True, exist_ok=True)
    dest = SITE / path.name
    if dest.resolve() != path.resolve():
        shutil.copy2(path, dest)

    preview = dest
    if dest.suffix.lower() == ".pdf":
        preview = dest.with_suffix(".preview.png")
        rasterise(dest, dpi=110).save(preview)

    bill = {
        "bill_no": path.stem, "date": "", "patient": "", "doctor": "",
        "hospital": "Uploaded document", "total": 0, "lines": [],
    }
    write_page(bill, preview.name, dest.name)
    (SITE / "bill.json").write_text(json.dumps(bill), encoding="utf-8")
    return bill, dest


def one_run(port: int, index: int, open_browser: bool, own: Path | None = None) -> list[list[str]]:
    if own:
        bill, doc = publish_own(own)
        log("input", f"using your document: {own.name}")
    else:
        bill, doc = generate(seed=None)
        log("generate", f"invoice {bill['bill_no']}, {len(bill['lines'])} lines, "
                        f"total INR {bill['total']:,}")
    url = f"http://127.0.0.1:{port}/?r={index}"

    if open_browser:
        webbrowser.open(url)
        log("browser", "opened the billing portal, waiting for the page to paint")
        time.sleep(3.5)

    hit = scroll_to_anchor(ANCHOR)
    if not hit:
        raise RuntimeError(
            "Could not find the download button anywhere on the page. Make sure "
            "the browser window is visible and not minimised."
        )
    x, y, px = hit
    log("locate", f"download button at ({x}, {y}) from {px:,} matching pixels")

    started = time.time()
    pyautogui.moveTo(x, y, duration=0.5)
    pyautogui.click()
    log("click", "clicked, waiting for the browser to save the PDF")

    saved = wait_for_download(doc.name, started)
    if saved:
        log("download", f"{saved.name} landed in {saved.parent}")
    else:
        saved = doc
        log("download", "nothing in Downloads within 30s, reading the served copy instead")

    header, lines, engine = read_bill(saved)
    log("extract", f"{engine}: {header.get('bill_no','?')} / {header.get('patient','?')}, "
                   f"{len(lines)} line items")
    return to_rows(header, lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=1, help="how many invoices to process")
    ap.add_argument("--no-open", action="store_true", help="skip launching the browser")
    ap.add_argument("--no-excel", action="store_true", help="stop after extraction")
    ap.add_argument("--bill", metavar="FILE", help="use your own PDF or image")
    ap.add_argument("--speed", type=float, default=0.035,
                    help="seconds between keystrokes; raise it for a slower recording")
    args = ap.parse_args()

    own = None
    if args.bill:
        own = Path(args.bill).expanduser()
        if not own.exists():
            print(f"  No such file: {own}")
            return 1
        args.runs = 1

    port = free_port()
    httpd = serve(port)
    print(f"\n  Billing portal running at http://127.0.0.1:{port}\n")

    rows: list[list[str]] = []
    try:
        for i in range(args.runs):
            print(f"  --- invoice {i + 1} of {args.runs} " + "-" * 34)
            try:
                rows.extend(one_run(port, i, not args.no_open, own))
            except Exception as exc:
                print(f"  ! {exc}")
                return 1
            print()
    finally:
        httpd.shutdown()

    if rows and not args.no_excel:
        type_into_excel(rows, interval=args.speed)
    elif rows:
        print("  --no-excel, so here is the table instead:\n")
        widths = [max(len(str(r[i])) for r in [HEADERS] + rows) for i in range(len(HEADERS))]
        for r in [HEADERS] + rows:
            print("   " + "  ".join(str(v).ljust(w) for v, w in zip(r, widths)))

    print("\n  Done.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
