"""
Layout-preserving OCR studio.

    python app.py            then open http://127.0.0.1:8050

Drop an image or a PDF in and watch two reconstructions of the same page
appear side by side: the flattened one that ordinary OCR gives you, and the
one that keeps the geometry. On a multi-column page they are not the same
document. Tables come out as real grids you can export.

    POST /api/ocr                   image or PDF -> boxes, text, tables
    GET  /api/page/<doc>/<n>        OCR page n of an already uploaded PDF
    GET  /api/pages/<doc>.zip       every PDF page rendered to PNG
    GET  /api/sample                a deliberately awkward A4 page
    GET  /api/export/<token>        the preserved text as .txt
    GET  /api/tables/<token>.csv    every detected table
    GET  /api/tables/<token>.xlsx   one worksheet per table

PDFs are rasterised with pypdfium2: a pip wheel with no external binary, so
there is no Poppler install to go wrong.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import time
import uuid
import zipfile
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import layout as L

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

HERE = Path(__file__).parent
WEB = HERE / "web"
WORK = HERE / "uploads"
WORK.mkdir(exist_ok=True)

PDF_DPI = int(os.environ.get("PDF_DPI") or 200)    # 200 is the sweet spot for OCR
MAX_UPLOAD = 25 * 1024 * 1024

app = FastAPI(title="OCR layout studio")

_engine = None
_engine_note = "not loaded"
_last: dict[str, dict] = {}        # token  -> {"text":..., "tables":[...]}
_docs: dict[str, dict] = {}        # doc id -> {"path":..., "pages":..., "name":...}


def engine():
    """Loaded on first use: Paddle takes a few seconds to spin up its models
    and there is no reason to pay that before someone uploads something."""
    global _engine, _engine_note
    if _engine is None:
        t0 = time.time()
        _engine, _ = L.load_engine(prefer=os.environ.get("OCR_ENGINE") or "tesseract")
        _engine_note = f"{_engine.name} (ready in {time.time() - t0:.1f}s)"
        print(f"  engine: {_engine_note}")
    return _engine


# ==========================================================================
# PDF
# ==========================================================================
def pdf_page_count(path: Path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def rasterise(path: Path, index: int, dpi: int = PDF_DPI):
    """Render one PDF page to a PIL image. render() takes a scale relative
    to 72 dpi, so 200 dpi is scale 200/72."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        if not 0 <= index < len(pdf):
            raise HTTPException(404, f"page {index + 1} does not exist")
        return pdf[index].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        pdf.close()


def save_image(im, stem: str) -> tuple[Path, int, int]:
    path = WORK / f"{stem}.png"
    im.save(path)
    return path, im.width, im.height


# ==========================================================================
# shared pipeline
# ==========================================================================
def process(image_path: Path, width: int, height: int, *,
            doc: str | None = None, page: int = 0, pages: int = 1,
            pdf_path: Path | None = None) -> dict:
    # One extraction path: the OCR engine. A PDF text-layer shortcut was
    # tried here and reverted: it produced different boxes from the OCR
    # path, so the layout, the tables and the figures all shifted depending
    # on how the file happened to be produced. One path, one behaviour.
    t0 = time.time()
    try:
        boxes = engine()(str(image_path))
        source = _engine.name
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"OCR failed: {exc}")
    elapsed = round((time.time() - t0) * 1000)

    common = {
        "url": f"/uploads/{image_path.name}",
        "width": width, "height": height,
        "engine": source, "ms": elapsed,
        "doc": doc, "page": page, "pages": pages,
    }

    if not boxes:
        return {**common, "boxes": [], "preserved": "", "flattened": "", "tables": [],
                "figures": [],
                "analysis": {**L.analyse([]), "tables": 0, "table_rows": 0, "figures": 0},
                "token": "", "verdict": "Nothing detected on this page."}

    preserved = L.preserve(boxes)
    flattened = L.flatten(boxes)
    analysis = L.analyse(boxes)
    tables = L.detect_tables(boxes)
    figures = L.detect_figures(str(image_path), boxes, tables)   # tables first: a table is not a figure
    analysis["tables"] = len(tables)
    analysis["table_rows"] = sum(len(t["rows"]) for t in tables)
    analysis["figures"] = len(figures)

    token = uuid.uuid4().hex[:8]
    _last[token] = {"text": preserved, "tables": tables,
                    "figures": figures, "image": str(image_path)}

    cols = analysis["columns"]
    verdict = (
        f"{cols} column bands detected. Flattening this page would interleave them."
        if cols > 1 else
        "Single column. Flattening would have been safe here, which is exactly why "
        "you cannot decide per document by eye."
    )

    return {**common, "boxes": L.to_payload(boxes), "preserved": preserved,
            "flattened": flattened, "tables": tables, "figures": figures,
            "analysis": analysis, "token": token, "verdict": verdict}


# ==========================================================================
# routes
# ==========================================================================
@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health():
    return {"engine": _engine.name if _engine else "not loaded",
            "note": _engine_note, "pdf_dpi": PDF_DPI}


@app.get("/api/sample")
async def sample():
    from make_sample import build

    path = WORK / f"sample_{uuid.uuid4().hex[:8]}.png"
    build(path)
    return {"url": f"/uploads/{path.name}", "name": path.name}


@app.post("/api/ocr")
async def ocr(file: UploadFile = File(...), page: int = Form(0)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "keep it under 25 MB")

    name = file.filename or "page.png"
    # Trust the magic bytes over the extension: a PDF saved as .png is still a PDF.
    is_pdf = raw[:5] == b"%PDF-" or name.lower().endswith(".pdf")

    if is_pdf:
        doc = uuid.uuid4().hex[:10]
        src = WORK / f"{doc}.pdf"
        src.write_bytes(raw)
        try:
            total = pdf_page_count(src)
        except Exception as exc:
            raise HTTPException(400, f"could not read that PDF: {exc}")
        _docs[doc] = {"path": src, "pages": total, "name": name}

        n = max(0, min(page, total - 1))
        img_path, w, h = save_image(rasterise(src, n), f"{doc}_p{n}")
        return JSONResponse(process(img_path, w, h, doc=doc, page=n,
                                    pages=total, pdf_path=src))

    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as im:
            img_path, w, h = save_image(im.convert("RGB"), uuid.uuid4().hex[:10])
    except Exception as exc:
        raise HTTPException(400, f"could not read that file: {exc}")

    return JSONResponse(process(img_path, w, h))


@app.get("/api/page/{doc}/{n}")
async def page_of(doc: str, n: int):
    """Page through an already uploaded PDF without re-sending the bytes."""
    got = _docs.get(doc)
    if not got:
        raise HTTPException(404, "that document is no longer loaded, upload it again")

    n = max(0, min(n, got["pages"] - 1))
    cached = WORK / f"{doc}_p{n}.png"
    if cached.exists():
        from PIL import Image
        with Image.open(cached) as im:
            w, h = im.size
    else:
        cached, w, h = save_image(rasterise(got["path"], n), f"{doc}_p{n}")

    return JSONResponse(process(cached, w, h, doc=doc, page=n,
                                pages=got["pages"], pdf_path=got["path"]))


@app.get("/api/pages/{doc}.zip")
async def pages_zip(doc: str):
    """Every page as a PNG. The other thing people want a PDF step for."""
    got = _docs.get(doc)
    if not got:
        raise HTTPException(404, "that document is no longer loaded")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(got["pages"]):
            png = io.BytesIO()
            rasterise(got["path"], n).save(png, "PNG")
            z.writestr(f"page_{n + 1:03d}.png", png.getvalue())

    stem = Path(got["name"]).stem
    return Response(
        buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}_pages.zip"'},
    )


@app.get("/api/figure/{token}/{n}.png")
async def figure_crop(token: str, n: int):
    """Crop one detected figure out of the page at full resolution."""
    got = _last.get(token)
    if got is None or n >= len(got.get("figures", [])):
        raise HTTPException(404, "no such figure")

    from PIL import Image
    x, y, w, h = got["figures"][n]["bbox"]
    pad = 8
    with Image.open(got["image"]) as im:
        crop = im.crop((max(0, x - pad), max(0, y - pad),
                        min(im.width, x + w + pad), min(im.height, y + h + pad)))
        buf = io.BytesIO()
        crop.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.get("/api/export/{token}")
async def export(token: str):
    got = _last.get(token)
    if got is None:
        raise HTTPException(404, "nothing to export")
    return PlainTextResponse(
        got["text"], headers={"Content-Disposition": 'attachment; filename="layout.txt"'}
    )


@app.get("/api/tables/{token}.csv")
async def tables_csv(token: str):
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
            longest = max((len(str(r[c - 1])) for r in t["rows"] if c - 1 < len(r)), default=10)
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

    print(f"\n  OCR layout studio at http://{args.host}:{args.port}")
    print(f"  accepts images and PDFs; PDFs rasterised at {PDF_DPI} dpi\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
