"""
Layout-preserving OCR studio.

    python app.py            then open http://127.0.0.1:8050

Drop a document in and watch two reconstructions of the same page appear side
by side: the flattened one that ordinary OCR gives you, and the one that keeps
the geometry. On a multi-column page they are not the same document.

    POST /api/ocr      an image -> boxes, both reconstructions, page analysis
    GET  /api/sample   generate a deliberately awkward multi-column page
    GET  /api/export   the preserved text as .txt
    GET  /api/tables/<token>.csv   every detected table
    GET  /api/tables/<token>.xlsx  one worksheet per table
"""

from __future__ import annotations

import argparse
import csv
import io
import time
import uuid
from pathlib import Path

import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import layout as L

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

HERE = Path(__file__).parent
WEB = HERE / "web"
WORK = HERE / "uploads"
WORK.mkdir(exist_ok=True)

app = FastAPI(title="OCR layout studio")

_engine = None
_engine_note = "not loaded"
_last: dict[str, dict] = {}        # token -> {"text":..., "tables":[...]}


def engine():
    """Loaded on first use: Paddle takes a few seconds to spin up its models
    and there is no reason to pay that before someone uploads something."""
    global _engine, _engine_note
    if _engine is None:
        t0 = time.time()
        _engine, _ = L.load_engine(prefer=os.environ.get("OCR_ENGINE") or "paddle")
        _engine_note = f"{_engine.name} (ready in {time.time() - t0:.1f}s)"
        print(f"  engine: {_engine_note}")
    return _engine


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health():
    return {"engine": _engine.name if _engine else "not loaded", "note": _engine_note}


@app.get("/api/sample")
async def sample():
    from make_sample import build

    path = WORK / f"sample_{uuid.uuid4().hex[:8]}.png"
    build(path)
    return {"url": f"/uploads/{path.name}", "name": path.name}


@app.post("/api/ocr")
async def ocr(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(413, "keep it under 12 MB")

    suffix = Path(file.filename or "page.png").suffix.lower() or ".png"
    if suffix == ".pdf":
        raise HTTPException(
            415, "PDF is not wired up here. Export the page as PNG, or add pdf2image."
        )

    path = WORK / f"{uuid.uuid4().hex[:10]}{suffix}"
    path.write_bytes(raw)

    # Normalise odd formats and get the pixel size for the overlay.
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            width, height = im.size
            im.save(path)
    except Exception as exc:
        raise HTTPException(400, f"could not read that image: {exc}")

    t0 = time.time()
    try:
        boxes = engine()(str(path))
    except Exception as exc:
        raise HTTPException(500, f"OCR failed: {exc}")
    elapsed = round((time.time() - t0) * 1000)

    if not boxes:
        return JSONResponse({
            "url": f"/uploads/{path.name}", "width": width, "height": height,
            "engine": _engine.name, "ms": elapsed, "boxes": [],
            "preserved": "", "flattened": "", "tables": [], "analysis": L.analyse([]),
            "token": "", "verdict": "Nothing detected on this page.",
        })

    preserved = L.preserve(boxes)
    flattened = L.flatten(boxes)
    analysis = L.analyse(boxes)
    tables = L.detect_tables(boxes)
    analysis["tables"] = len(tables)
    analysis["table_rows"] = sum(len(t["rows"]) for t in tables)

    token = uuid.uuid4().hex[:8]
    _last[token] = {"text": preserved, "tables": tables}

    cols = analysis["columns"]
    verdict = (
        f"{cols} column bands detected. Flattening this page would interleave them."
        if cols > 1 else
        "Single column. Flattening would have been safe here, which is exactly why "
        "you cannot decide per document by eye."
    )

    return JSONResponse({
        "url": f"/uploads/{path.name}",
        "width": width, "height": height,
        "engine": _engine.name, "ms": elapsed,
        "boxes": L.to_payload(boxes),
        "preserved": preserved, "flattened": flattened, "tables": tables,
        "analysis": analysis, "token": token, "verdict": verdict,
    })


@app.get("/api/export/{token}")
async def export(token: str):
    got = _last.get(token)
    if got is None:
        raise HTTPException(404, "nothing to export")
    return PlainTextResponse(got["text"], headers={"Content-Disposition": 'attachment; filename="layout.txt"'})


@app.get("/api/tables/{token}.csv")
async def tables_csv(token: str):
    """Every detected table, blank line between them."""
    got = _last.get(token)
    if got is None or not got["tables"]:
        raise HTTPException(404, "no tables detected on that page")
    buf = io.StringIO()
    writer = csv.writer(buf)
    for n, t in enumerate(got["tables"], 1):
        writer.writerow([f"# table {n}"])
        writer.writerows(t["rows"])
        writer.writerow([])
    return PlainTextResponse(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tables.csv"'},
    )


@app.get("/api/tables/{token}.xlsx")
async def tables_xlsx(token: str):
    """One worksheet per table, first row styled as a header."""
    got = _last.get(token)
    if got is None or not got["tables"]:
        raise HTTPException(404, "no tables detected on that page")

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for n, t in enumerate(got["tables"], 1):
        ws = wb.create_sheet(f"Table {n}")
        for r, row in enumerate(t["rows"], 1):
            for c, value in enumerate(row, 1):
                cell = ws.cell(row=r, column=c, value=value)
                if r == 1:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="16324F")
                    cell.alignment = Alignment(horizontal="center")
        for c in range(1, t["cols"] + 1):
            longest = max((len(str(r[c-1])) for r in t["rows"] if c-1 < len(r)), default=10)
            ws.column_dimensions[get_column_letter(c)].width = min(max(longest + 3, 12), 48)
        ws.freeze_panes = "A2"

    out = io.BytesIO()
    wb.save(out)
    return Response(
        out.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tables.xlsx"'},
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--warm", action="store_true", help="load the OCR engine at boot")
    args = ap.parse_args()

    app.mount("/uploads", StaticFiles(directory=WORK), name="uploads")
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    if args.warm:
        try:
            engine()
        except Exception as exc:
            print(f"  ! no OCR engine: {exc}")

    print(f"\n  OCR layout studio at http://{args.host}:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
