"""
Layout-preserving OCR studio.

    python app.py            then open http://127.0.0.1:8050

Drop a document in and watch two reconstructions of the same page appear side
by side: the flattened one that ordinary OCR gives you, and the one that keeps
the geometry. On a multi-column page they are not the same document.

    POST /api/ocr      an image -> boxes, both reconstructions, page analysis
    GET  /api/sample   generate a deliberately awkward multi-column page
    GET  /api/export   the preserved text as .txt
"""

from __future__ import annotations

import argparse
import io
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import layout as L

HERE = Path(__file__).parent
WEB = HERE / "web"
WORK = HERE / "uploads"
WORK.mkdir(exist_ok=True)

app = FastAPI(title="OCR layout studio")

_engine = None
_engine_note = "not loaded"
_last_text: dict[str, str] = {}


def engine():
    """Loaded on first use: Paddle takes a few seconds to spin up its models
    and there is no reason to pay that before someone uploads something."""
    global _engine, _engine_note
    if _engine is None:
        t0 = time.time()
        _engine, _ = L.load_engine(prefer="paddle")
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
            "preserved": "", "flattened": "", "analysis": L.analyse([]),
            "token": "", "verdict": "Nothing detected on this page.",
        })

    preserved = L.preserve(boxes)
    flattened = L.flatten(boxes)
    analysis = L.analyse(boxes)

    token = uuid.uuid4().hex[:8]
    _last_text[token] = preserved

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
        "preserved": preserved, "flattened": flattened,
        "analysis": analysis, "token": token, "verdict": verdict,
    })


@app.get("/api/export/{token}")
async def export(token: str):
    text = _last_text.get(token)
    if text is None:
        raise HTTPException(404, "nothing to export")
    return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="layout.txt"'})


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
