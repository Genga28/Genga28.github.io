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

import os
import re
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


# Where Tesseract actually installs on Windows, in the order worth trying.
# PATH first, then the two paths the UB-Mannheim installer uses, then the
# Chocolatey and Scoop locations. TESSERACT_CMD in .env overrides all of it.
TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\ProgramData\chocolatey\bin\tesseract.exe",
    str(Path.home() / "scoop" / "apps" / "tesseract" / "current" / "tesseract.exe"),
    str(Path.home() / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe"),
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]


def find_tesseract() -> str | None:
    """First Tesseract binary that actually exists, or None."""
    from shutil import which

    for candidate in [os.environ.get("TESSERACT_CMD"), which("tesseract"), *TESSERACT_PATHS]:
        if candidate and Path(candidate).exists():
            return candidate
    return None


class TesseractEngine:
    name = "tesseract"

    def __init__(self, lang: str = "eng") -> None:
        import pytesseract

        exe = find_tesseract()
        if not exe:
            raise RuntimeError(
                "Tesseract binary not found. Install it from "
                "https://github.com/UB-Mannheim/tesseract/wiki, or set TESSERACT_CMD "
                "in demos/.env to its full path."
            )
        pytesseract.pytesseract.tesseract_cmd = exe
        self._pt = pytesseract
        self._lang = lang
        self._pt.get_tesseract_version()          # raises if the binary is broken

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


# ==========================================================================
# table extraction
# ==========================================================================
def split_cells(line: list[Box], cw: float, gap: float = 2.2) -> list[tuple[float, str]]:
    """Split one line into cells wherever the horizontal gap gets wide.

    Words inside a cell sit about one space apart. A column gutter is several
    characters wide, so `gap` character-advances is a reliable separator and
    scales with the page's own type size.
    """
    if not line:
        return []
    cells, start, parts = [], line[0].x0, [line[0].text]
    for prev, box in zip(line, line[1:]):
        if (box.x0 - prev.x1) > cw * gap:
            cells.append((start, " ".join(parts)))
            start, parts = box.x0, [box.text]
        else:
            parts.append(box.text)
    cells.append((start, " ".join(parts)))
    return cells


_NUMERIC = re.compile(r"^[\s$£€₹]*[-+]?[\d,]+(?:\.\d+)?\s*%?$")


def is_tabular(grid: list[list[str]]) -> bool:
    """Separate a real table from anything else that happens to line up.

    Geometry alone cannot do it: two columns of prose, a label/value block
    and a list of short headings all sit on the same anchors a table does.
    Four structural tests, and a candidate has to earn its way through.
    """
    cells = [c for row in grid for c in row if c.strip()]
    if not cells:
        return False

    rows, cols = len(grid), len(grid[0])

    # 1. Prose. Table cells are terse; sentences are not.
    median_len = statistics.median(len(c) for c in cells)
    if median_len > 24:
        return False

    # 2. Mostly-empty grids are an alignment coincidence, not a table.
    fill = len(cells) / float(rows * cols)
    if fill < 0.55:
        return False

    # 3. A table has a consistent row shape. Rows that each hold a different
    #    number of cells are stray text that happened to align.
    per_row = [sum(1 for c in row if c.strip()) for row in grid]
    regular = len(set(per_row)) <= 2 and min(per_row) >= 2

    # 4. A column counts as numeric if most of its filled cells parse as one.
    #    This is the strongest single signal that a grid carries data.
    numeric_cols = 0
    for k in range(cols):
        vals = [row[k].strip() for row in grid if k < len(row) and row[k].strip()]
        if len(vals) >= 2 and sum(bool(_NUMERIC.match(v)) for v in vals) / len(vals) >= 0.6:
            numeric_cols += 1

    if numeric_cols >= 1 and regular:
        return True                      # a data table
    if cols >= 3 and regular and median_len <= 16:
        return True                      # a text-only table: name / role / team
    return False


def preserve(boxes: list[Box], gutter: int = 3) -> str:
    """Boxes -> monospace text with the page's column structure intact.

    The obvious approach, dividing every x by one character advance, keeps
    the geometry but wastes the page: a 378px gutter becomes 37 blank
    characters and the result is 160 columns wide and unreadable.

    So this snaps instead. Every cell on the page is assigned to a shared
    column anchor, each anchor is given only as much width as its widest
    cell needs, and anchors are separated by a fixed gutter. Columns still
    line up down the page, because two cells at the same anchor always land
    in the same output column, but dead space is gone.
    """
    lines = cluster_lines(boxes)
    if not lines:
        return ""

    cw = char_width(boxes)
    per_line = [split_cells(line, cw) for line in lines]

    # Cluster every cell start into a small set of page-wide anchors.
    anchors: list[float] = []
    tol = cw * 2.5
    for row in per_line:
        for x, _ in row:
            for i, a in enumerate(anchors):
                if abs(a - x) <= tol:
                    anchors[i] = (a + x) / 2
                    break
            else:
                anchors.append(x)
    anchors.sort()

    assigned: list[list[tuple[int, str]]] = []
    for row in per_line:
        assigned.append([
            (min(range(len(anchors)), key=lambda n: abs(anchors[n] - x)), text)
            for x, text in row
        ])

    # Place anchors by constraint, not by accumulation.
    #
    # Summing every anchor's width makes the page as wide as the total of all
    # columns that appear anywhere on it, even though no single line uses
    # them all: a page with a 4-column table and 2-column prose ends up
    # 6 columns wide. Instead each anchor only has to clear whatever actually
    # precedes it on the lines where it appears.
    starts = [0] * len(anchors)
    for k in range(len(anchors)):
        need = 0
        for row in assigned:
            for pos, (idx, text) in enumerate(row):
                if idx != k or pos == 0:
                    continue
                prev_idx, prev_text = row[pos - 1]
                need = max(need, starts[prev_idx] + len(prev_text) + gutter)
        starts[k] = max(need, starts[k - 1] + gutter if k else 0)

    # Vertical gaps survive, so paragraph breaks and table gutters read.
    heights = [statistics.median(b.h for b in line) for line in lines]
    line_h = statistics.median(heights) or 12.0

    out: list[str] = []
    prev_bottom: float | None = None
    for row, line in zip(assigned, lines):
        top = min(b.y0 for b in line)
        if prev_bottom is not None:
            for _ in range(min(int((top - prev_bottom) / max(line_h, 1.0)), 3)):
                out.append("")

        text_row = ""
        for k, text in row:
            col = max(starts[k], len(text_row) + (1 if text_row else 0))
            text_row = text_row.ljust(col) + text
        out.append(text_row.rstrip())
        prev_bottom = max(b.y1 for b in line)

    return "\n".join(out)


def preserve_grid(boxes: list[Box], max_cols: int = 220) -> str:
    """The raw pixel grid, kept for comparison. True to the page geometry,
    but wide and full of dead space on anything with a big gutter."""
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
        prev: Box | None = None

        for box in line:
            # Each box's own advance. A 28px heading and 11px body text do not
            # share a character width, and dividing a heading's pixel gaps by
            # the page-wide body advance is what blows "Annual Report & Accounts"
            # apart into "Annual      Report      &      Accounts".
            local = box.w / max(len(box.text), 1)

            if prev is not None:
                gap = box.x0 - prev.x1
                if gap < local * 1.8:
                    # Words inside one phrase: space them in their own type
                    # size, not on the page grid.
                    row += " " * max(1, int(round(gap / local))) + box.text
                    prev = box
                    continue

            # A real gutter, so fall back to the page grid and keep the column.
            col = min(int(round((box.x0 - left) / cw)), max_cols)
            col = max(col, len(row) + (1 if row else 0))
            row = row.ljust(col) + box.text
            prev = box

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


def detect_tables(boxes: list[Box], min_rows: int = 3, min_cols: int = 2) -> list[dict]:
    """Find tabular regions and return them as real grids.

    A table is a run of consecutive lines whose cells land on the same
    vertical anchors. That is what separates a table from a paragraph: prose
    starts every line at the left margin, a table repeats the same column
    positions down the page.

    Returns [{rows: [[str, ...], ...], bbox: [x0,y0,x1,y1], cols: int}].
    """
    lines = cluster_lines(boxes)
    if len(lines) < min_rows:
        return []

    cw = char_width(boxes)
    tol = cw * 3.5                     # how far a cell may drift and still count
    per_line = [split_cells(line, cw) for line in lines]

    def aligns(a, b) -> bool:
        """Do two lines share at least min_cols anchors in common?"""
        if len(a) < min_cols or len(b) < min_cols:
            return False
        hits = sum(1 for xa, _ in a if any(abs(xa - xb) <= tol for xb, _ in b))
        return hits >= min_cols and hits >= min(len(a), len(b)) - 1

    tables, i = [], 0
    while i < len(per_line):
        j = i
        while j + 1 < len(per_line) and aligns(per_line[j], per_line[j + 1]):
            j += 1

        if j - i + 1 >= min_rows:
            block = per_line[i:j + 1]

            # Column anchors: cluster every cell x across the block.
            anchors: list[float] = []
            for row in block:
                for x, _ in row:
                    for k, a in enumerate(anchors):
                        if abs(a - x) <= tol:
                            anchors[k] = (a + x) / 2       # drift toward the mean
                            break
                    else:
                        anchors.append(x)
            anchors.sort()

            grid = []
            for row in block:
                cells = [""] * len(anchors)
                for x, text in row:
                    k = min(range(len(anchors)), key=lambda n: abs(anchors[n] - x))
                    cells[k] = (cells[k] + " " + text).strip() if cells[k] else text
                grid.append(cells)

            # Drop columns that ended up empty everywhere.
            keep = [k for k in range(len(anchors)) if any(r[k] for r in grid)]
            grid = [[r[k] for k in keep] for r in grid]

            if grid and len(grid[0]) >= min_cols and is_tabular(grid):
                flat = [b for line in lines[i:j + 1] for b in line]
                tables.append({
                    "rows": grid,
                    "cols": len(grid[0]),
                    "bbox": [
                        round(min(b.x0 for b in flat), 1), round(min(b.y0 for b in flat), 1),
                        round(max(b.x1 for b in flat), 1), round(max(b.y1 for b in flat), 1),
                    ],
                })
        i = j + 1

    return tables


# ==========================================================================
# figures: charts, logos, stamps, signatures
# ==========================================================================
def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Fraction of box `a` that lies inside box `b`."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    area = (ax1 - ax0) * (ay1 - ay0)
    return (ix * iy / area) if area > 0 else 0.0


def detect_figures(image_path: str, boxes: list[Box], tables: list[dict] | None = None,
                   min_area_frac: float = 0.003) -> list[dict]:
    """Find the non-text graphics on the page.

    The trick is subtractive rather than clever: threshold the page to an ink
    mask, paint out every box the OCR engine already claimed, and whatever
    ink survives is by definition not text. Close it up, take connected
    components, and the leftovers are charts, logos, stamps and signatures.

    Each figure reports the OCR text that falls inside it, which for a chart
    is its title, axis labels and legend. That is the metadata, not the
    series data: see the note in the README about why reading values off a
    plot is a different problem.
    """
    try:
        import cv2
    except ImportError:
        return []

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    H, W = img.shape

    ink = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                cv2.THRESH_BINARY_INV, 41, 18)

    # Erase everything the recogniser already read, with a small cushion so
    # antialiased glyph edges do not survive as speckle.
    pad = max(2, int(char_width(boxes) * 0.4)) if boxes else 2
    for b in boxes:
        cv2.rectangle(ink, (int(b.x0) - pad, int(b.y0) - pad),
                      (int(b.x1) + pad, int(b.y1) + pad), 0, -1)

    k = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17))
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, k, iterations=2)

    count, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    min_box = W * H * min_area_frac

    figures = []
    for i in range(1, count):
        x, y, w, h, ink_px = stats[i]

        # Gate on the bounding box, not the ink count. A line chart is mostly
        # whitespace by design: a 470x300 plot can carry under 8k ink pixels
        # and would be thrown away by an ink threshold that a solid logo of a
        # tenth the size sails through.
        if w * h < min_box or w < W * 0.04 or h < H * 0.015 or h < 20:
            continue
        if ink_px < 400:                     # speckle and scanner dust
            continue
        if w > W * 0.97 and h < 40:          # a full-width rule, not a figure
            continue

        # Axis labels and captions sit just outside the plotted area, so look
        # a little wider than the box when deciding whether this is a chart.
        mx, my = w * 0.10 + 12, h * 0.10 + 12
        near = [b for b in boxes
                if x - mx <= b.cx <= x + w + mx and y - my <= b.cy <= y + h + my]
        within = [b for b in boxes
                  if x <= b.cx <= x + w and y <= b.cy <= y + h]
        density = ink_px / float(w * h)

        # A filled header band is not a figure, it is a background. The band's
        # fill survives the text-erase above because only the glyphs were
        # painted out, so a navy bar with white text lands here looking like a
        # solid image. Dense fill with text sitting on top of it is a text
        # background, every time.
        if density > 0.5 and len(within) >= 2:
            continue

        # Likewise a wide, short solid bar with nothing in it is a rule.
        if density > 0.5 and h < 70 and w > W * 0.25 and not within:
            continue

        if len(near) >= 3 and density < 0.45:
            kind = "chart"                   # sparse ink, surrounded by labels
        elif density > 0.55:
            kind = "image"                   # solid block: photo or stamp
        else:
            kind = "graphic"                 # a rule, a scrawl, a signature
        inside = near

        figures.append({
            "bbox": [int(x), int(y), int(w), int(h)],
            "kind": kind,
            "area_pct": round(100 * (w * h) / (W * H), 2),
            "ink": round(density, 3),
            "labels": [b.text for b in sorted(inside, key=lambda b: (b.y0, b.x0))][:24],
        })

    # 1. Anything already reported as a table is not a figure. A ruled table
    #    is mostly non-text ink, so it lands here otherwise, and the same
    #    region showing up twice under two different names is just wrong.
    table_boxes = [(t["bbox"][0], t["bbox"][1], t["bbox"][2], t["bbox"][3])
                   for t in (tables or [])]
    kept = []
    for f in figures:
        x, y, w, h = f["bbox"]
        rect = (x, y, x + w, y + h)
        if any(_overlap(rect, tb) > 0.45 or _overlap(tb, rect) > 0.65 for tb in table_boxes):
            continue
        kept.append(f)

    # 2. Drop fragments sitting inside a bigger figure. A chart's axis or a
    #    detached gridline would otherwise be listed as its own graphic.
    kept.sort(key=lambda f: f["bbox"][2] * f["bbox"][3], reverse=True)
    final: list[dict] = []
    for f in kept:
        x, y, w, h = f["bbox"]
        rect = (x, y, x + w, y + h)
        if any(_overlap(rect, (g["bbox"][0], g["bbox"][1],
                               g["bbox"][0] + g["bbox"][2],
                               g["bbox"][1] + g["bbox"][3])) > 0.7 for g in final):
            continue
        final.append(f)

    final.sort(key=lambda f: (f["bbox"][1], f["bbox"][0]))
    return final


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
