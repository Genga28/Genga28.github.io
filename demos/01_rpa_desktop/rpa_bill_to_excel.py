"""
Desktop RPA: open a billing portal in the browser, find and click the download
button by looking at the screen, wait for the file to land, read the invoice
with OCR, and write the fields into a formatted Excel workbook.

    python rpa_bill_to_excel.py
    python rpa_bill_to_excel.py --runs 3 --no-open

Nothing here talks to the page's DOM. The bot sees pixels and moves the real
cursor, which is the point: it is the same technique you need when the target
is a legacy desktop app with no API.

Safety: PyAutoGUI's failsafe is on. Slam the pointer into the top-left corner
of the screen to abort a run.
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import socket
import socketserver
import sys
import threading
import time
import webbrowser
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
pyautogui.PAUSE = 0.35


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
# 2. find the button on screen, by colour
# --------------------------------------------------------------------------
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def find_anchor(colour: str, tol: int = 26, min_px: int = 900):
    """Return the centre of the largest on-screen blob of `colour`, or None.

    Screenshot -> per-channel distance mask -> largest row/column run. Scale
    and DPI independent, unlike template matching, because a flat colour block
    stays the same colour at any zoom level.
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


def wait_for_anchor(colour: str, timeout: float = 25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hit = find_anchor(colour)
        if hit:
            return hit
        time.sleep(0.4)
    return None


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
# 4. read the invoice
# --------------------------------------------------------------------------
FIELDS = {
    "bill_no": r"Bill\s*No\.?\s*:?\s*([A-Z]{2}-\d{4,8})",
    "date": r"Date\s*:?\s*(\d{4}-\d{2}-\d{2})",
    "patient": r"Patient\s*:?\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
    "doctor": r"Doctor\s*:?\s*(Dr\.?\s*[A-Z][a-z]+\s+[A-Z][a-z]+)",
    "total": r"Total\s*:?\s*INR\s*([\d,]+)",
}


def ocr(path: Path) -> tuple[dict, str]:
    """OCR the invoice. Returns (fields, engine-used)."""
    try:
        import pytesseract
        from shutil import which

        exe = which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if Path(exe).exists():
            pytesseract.pytesseract.tesseract_cmd = exe
        text = pytesseract.image_to_string(Image.open(path))

        found = {}
        for key, pattern in FIELDS.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                found[key] = m.group(1).strip()
        if len(found) >= 3:
            return found, "tesseract"
        log("ocr", f"only matched {len(found)}/5 fields, using sidecar instead")
    except Exception as exc:
        log("ocr", f"tesseract unavailable ({type(exc).__name__}), using sidecar")

    sidecar = json.loads((SITE / "bill.json").read_text(encoding="utf-8"))
    return (
        {
            "bill_no": sidecar["bill_no"],
            "date": sidecar["date"],
            "patient": sidecar["patient"],
            "doctor": sidecar["doctor"],
            "total": f"{sidecar['total']:,}",
        },
        "sidecar-json",
    )


# --------------------------------------------------------------------------
# 5. Excel
# --------------------------------------------------------------------------
def write_excel(rows: list[dict], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted bills"

    headers = ["Bill No", "Date", "Patient", "Doctor", "Total (INR)", "Source", "Captured at"]
    widths = [16, 14, 24, 28, 15, 15, 20]

    ws["A1"] = "Medical billing - automated extraction"
    ws["A1"].font = Font(size=14, bold=True, color="0F2B46")
    ws.merge_cells("A1:G1")
    ws.row_dimensions[1].height = 26

    head_fill = PatternFill("solid", fgColor="0F62FE")
    thin = Side(style="thin", color="D5DCE6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[3].height = 20

    for r, row in enumerate(rows, start=4):
        values = [
            row.get("bill_no", ""),
            row.get("date", ""),
            row.get("patient", ""),
            row.get("doctor", ""),
            int(str(row.get("total", "0")).replace(",", "") or 0),
            row.get("source", ""),
            row.get("captured", ""),
        ]
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.border = border
            if i == 5:
                c.number_format = '#,##0'
                c.alignment = Alignment(horizontal="right")
        if r % 2 == 0:
            for i in range(1, len(headers) + 1):
                ws.cell(row=r, column=i).fill = PatternFill("solid", fgColor="F5F8FC")

    last = 3 + len(rows)
    ws.cell(row=last + 1, column=4, value="Total").font = Font(bold=True)
    t = ws.cell(row=last + 1, column=5, value=f"=SUM(E4:E{last})")
    t.font = Font(bold=True)
    t.number_format = '#,##0'
    ws.freeze_panes = "A4"

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def one_run(port: int, index: int, open_browser: bool) -> dict:
    bill, png = generate(seed=None)
    url = f"http://127.0.0.1:{port}/?r={index}"
    log("generate", f"invoice {bill['bill_no']}, total INR {bill['total']:,}")

    if open_browser:
        webbrowser.open(url)
        log("browser", "opened the billing portal, waiting for the page to paint")
        time.sleep(3.5)

    hit = wait_for_anchor(ANCHOR)
    if not hit:
        raise RuntimeError(
            "Could not find the download button on screen. Make sure the browser "
            "window is visible and not minimised or scrolled past the button."
        )
    x, y, px = hit
    log("locate", f"found the download button at ({x}, {y}) from {px:,} matching pixels")

    started = time.time()
    pyautogui.moveTo(x, y, duration=0.5)
    pyautogui.click()
    log("click", "clicked, waiting for the browser to save the file")

    saved = wait_for_download(png.name, started)
    if saved:
        log("download", f"{saved.name} landed in {saved.parent}")
    else:
        saved = png
        log("download", "nothing in Downloads within 30s, reading the served copy instead")

    fields, engine = ocr(saved)
    log("extract", f"{engine}: " + ", ".join(f"{k}={v}" for k, v in fields.items()))

    fields["source"] = engine
    fields["captured"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return fields


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=1, help="how many invoices to process")
    ap.add_argument("--no-open", action="store_true", help="skip launching the browser")
    args = ap.parse_args()

    port = free_port()
    httpd = serve(port)
    print(f"\n  Billing portal running at http://127.0.0.1:{port}\n")

    rows = []
    try:
        for i in range(args.runs):
            print(f"  --- invoice {i + 1} of {args.runs} " + "-" * 34)
            try:
                rows.append(one_run(port, i, not args.no_open))
            except Exception as exc:
                print(f"  ! {exc}")
                return 1
            print()
    finally:
        httpd.shutdown()

    if rows:
        xlsx = OUT / "medical_bills.xlsx"
        write_excel(rows, xlsx)
        log("excel", f"wrote {len(rows)} row(s) to {xlsx}")
        try:
            import os
            os.startfile(xlsx)  # noqa: S606  - Windows only, opens in Excel for the recording
            log("excel", "opened in Excel")
        except Exception:
            pass

    print("\n  Done.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
