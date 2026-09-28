"""
Layout-preserving OCR.

Ordinary OCR returns reading order and throws the geometry away. On a
single-column letter that is fine. On a bank statement, a lab report or a
multi-column invoice it is destructive: a number ends up attached to the wrong
label, and something downstream underwrites a loan on it.

This module keeps the geometry. Detected boxes are quantised back onto a
character grid derived from the document's own metrics, so columns stay
columns, indentation survives, and a table still looks like a table in plain
text.

    boxes -> character width estimate -> line clustering -> column placement

Engines, in preference order:
    PaddleOCR   better detection on dense multi-column pages
    Tesseract   fallback, via image_to_data which also returns boxes
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import numpy as np


@dataclass
class Box:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def w(self) -> float:
        return self.x1 - self.x0


# ==========================================================================
# engines
# ==========================================================================
class PaddleEngine:
    name = "paddleocr"

    def __init__(self, lang: str = "en") -> None:
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)

    def __call__(self, image_path: str) -> list[Box]:
        raw = self._ocr.ocr(image_path, cls=True)
        if not raw:
            return []
        page = raw[0] if isinstance(raw[0], list) else raw
        out: list[Box] = []
        for item in page or []:
            try:
                quad, (text, conf) = item[0], item[1]
            except (TypeError, ValueError, IndexError):
                continue
            xs = [float(p[0]) for p in quad]
            ys = [float(p[1]) for p in quad]
            text = (text or "").strip()
            if text:
                out.append(Box(text, min(xs), min(ys), max(xs), max(ys), float(conf)))
        return out


class TesseractEngine:
    name = "tesseract"

    def __init__(self, lang: str = "eng") -> None:
        import pytesseract
        from shutil import which

        exe = which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if Path(exe).exists():
            pytesseract.pytesseract.tesseract_cmd = exe
        self._pt = pytesseract
        self._lang = lang
        self._pt.get_tesseract_version()          # raises if the binary is missing

    def __call__(self, image_path: str) -> list[Box]:
        from PIL import Image

        data = self._pt.image_to_data(
            Image.open(image_path), lang=self._lang, output_type=self._pt.Output.DICT
        )
        out: list[Box] = []
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            out.append(Box(text, x, y, x + w, y + h, conf / 100.0))
        return out


def load_engine(prefer: str = "paddle"):
    """Returns (engine, note). Never raises: falls through to whatever exists."""
    order = ["paddle", "tesseract"] if prefer == "paddle" else ["tesseract", "paddle"]
    errors = []
    for name in order:
        try:
            return (PaddleEngine() if name == "paddle" else TesseractEngine()), ""
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    raise RuntimeError("no OCR engine available (" + "; ".join(errors) + ")")


# ==========================================================================
# layout reconstruction
# ==========================================================================
def cluster_lines(boxes: list[Box], tolerance: float = 0.6) -> list[list[Box]]:
    """Group boxes into text lines by vertical overlap.

    Threshold is a fraction of the median glyph height rather than a fixed
    pixel count, so this holds at any scan resolution.
    """
    if not boxes:
        return []
    median_h = statistics.median(b.h for b in boxes) or 1.0
    limit = median_h * tolerance

    lines: list[list[Box]] = []
    for box in sorted(boxes, key=lambda b: b.cy):
        for line in lines:
            if abs(statistics.mean(b.cy for b in line) - box.cy) <= limit:
                line.append(box)
                break
        else:
            lines.append([box])

    for line in lines:
        line.sort(key=lambda b: b.x0)
    lines.sort(key=lambda line: min(b.y0 for b in line))
    return lines


def char_width(boxes: list[Box]) -> float:
    """Median per-character advance across the page.

    Taken from boxes of 3+ characters: short boxes are dominated by padding
    and skew the estimate, which then shears every column on the page.
    """
    widths = [b.w / len(b.text) for b in boxes if len(b.text) >= 3 and b.w > 0]
    if not widths:
        widths = [b.w / max(len(b.text), 1) for b in boxes if b.w > 0] or [8.0]
    return max(statistics.median(widths), 1.0)


def preserve(boxes: list[Box], max_cols: int = 220) -> str:
    """Boxes -> monospace text with the page geometry intact."""
    lines = cluster_lines(boxes)
    if not lines:
        return ""

    cw = char_width(boxes)
    left = min(b.x0 for b in boxes)

    # Blank lines between rows that sit further apart than one line height,
    # so paragraph breaks and table gutters survive.
    heights = [statistics.median(b.h for b in line) for line in lines]
    line_h = statistics.median(heights) or 12.0

    out: list[str] = []
    prev_bottom: float | None = None

    for line in lines:
        top = min(b.y0 for b in line)
        if prev_bottom is not None:
            gap = top - prev_bottom
            for _ in range(min(int(gap / max(line_h, 1.0)), 3)):
                out.append("")

        row = ""
        for box in line:
            col = int(round((box.x0 - left) / cw))
            col = max(col, len(row) + (1 if row else 0))
            if col > max_cols:
                col = min(col, max_cols)
            row = row.ljust(col) + box.text
        out.append(row.rstrip())
        prev_bottom = max(b.y1 for b in line)

    return "\n".join(out)


def flatten(boxes: list[Box]) -> str:
    """What you get without the geometry: reading order, spaces between words.
    Included so the demo can show both side by side."""
    return "\n".join(" ".join(b.text for b in line) for line in cluster_lines(boxes))


def columns(boxes: list[Box], gap_ratio: float = 2.5) -> list[tuple[float, float]]:
    """Detect vertical column bands from gaps in the horizontal projection.

    A multi-column page has whitespace corridors running its full height; a
    single-column page has none. Useful as a signal on its own: it tells you
    whether flattening would have been safe.
    """
    if not boxes:
        return []
    cw = char_width(boxes)
    page_l = min(b.x0 for b in boxes)
    page_r = max(b.x1 for b in boxes)
    width = int(page_r - page_l) + 1
    if width <= 1:
        return []

    occupancy = np.zeros(width, dtype=np.int32)
    for b in boxes:
        occupancy[int(b.x0 - page_l): int(b.x1 - page_l)] += 1

    min_gap = cw * gap_ratio
    bands, run_start = [], None
    for x in range(width):
        if occupancy[x] == 0:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None and (x - run_start) >= min_gap:
                bands.append((run_start, x))
            run_start = None

    if not bands:
        return [(page_l, page_r)]

    cols, cursor = [], page_l
    for g0, g1 in bands:
        if g0 + page_l > cursor:
            cols.append((cursor, g0 + page_l))
        cursor = g1 + page_l
    if cursor < page_r:
        cols.append((cursor, page_r))
    return [c for c in cols if c[1] - c[0] > cw * 4]


def analyse(boxes: list[Box]) -> dict:
    confs = [b.conf for b in boxes] or [0.0]
    lines = cluster_lines(boxes)
    cols = columns(boxes)
    return {
        "boxes": len(boxes),
        "lines": len(lines),
        "columns": len(cols),
        "column_bands": [[round(a, 1), round(b, 1)] for a, b in cols],
        "char_width": round(char_width(boxes), 2) if boxes else 0,
        "mean_conf": round(float(np.mean(confs)), 4),
        "low_conf": sum(1 for c in confs if c < 0.80),
        "words": sum(len(b.text.split()) for b in boxes),
    }


def to_payload(boxes: Iterable[Box]) -> list[dict]:
    return [asdict(b) for b in boxes]
