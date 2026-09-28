# Demo 5 — OCR layout studio

Ordinary OCR returns reading order and throws the geometry away. On a
single-column letter that is fine. On a bank statement, a lab report or a
two-column invoice it is destructive: a number ends up attached to the wrong
label, and something downstream underwrites a loan on it.

This studio shows both reconstructions of the same page side by side, so the
failure is visible rather than theoretical.

```powershell
pip install -r requirements.txt
python app.py                 # http://127.0.0.1:8050
python app.py --warm          # load the OCR models at boot instead of on first upload
```

Press **Generate a hard page** for a synthetic two-column discharge summary
with a right-aligned charges table and a floating sidebar — the shape that
breaks reading-order OCR — or drop in your own scan.

## How the layout is rebuilt

```
boxes  ->  character-advance estimate  ->  line clustering  ->  column placement
```

1. **Character advance.** Median of `box_width / len(text)` across boxes of
   three or more characters. Short boxes are mostly padding and skew the
   estimate, which then shears every column on the page.
2. **Line clustering.** Boxes group by vertical overlap, with the threshold set
   as a fraction of the page's own median glyph height rather than a pixel
   count — so it holds at any scan resolution.
3. **Column placement.** Each box lands at `round((x0 − page_left) / advance)`
   in a monospace grid. Columns stay columns, indentation survives, and a table
   still reads as a table in plain text.
4. **Vertical gaps.** Rows further apart than one line height get blank lines,
   so paragraph breaks and table gutters survive too.

There's also a column detector: gaps in the horizontal projection wider than
2.5 character advances are whitespace corridors. It reports how many column
bands the page has, which is the signal that tells you whether flattening would
have been safe — and the answer is per-page, which is why you cannot decide it
by eye at scale.

## Engines

| Engine | When |
|---|---|
| PaddleOCR | primary, better detection on dense multi-column pages |
| Tesseract | fallback via `image_to_data`, which also returns boxes |

`load_engine()` tries Paddle, falls through to Tesseract, and only raises if
neither exists. PaddleOCR is a ~700 MB install with `paddlepaddle`, which is
why it sits in this folder's `requirements.txt` rather than the repo-wide one.

## The UI

Boxes animate in reading order so you watch the detector sweep the page rather
than having four hundred rectangles appear at once. Box colour is confidence —
blue above 0.80, amber below, red below 0.60 — and hovering one shows its text
and score. Violet dashed bands are the detected columns. Stats count up; the
text pane types in line by line.

## Recording it

Generate the hard page, let the boxes sweep in, then toggle between **Layout
preserved** and **Flattened**. The flattened tab is the moment that lands:
the left column's clinical notes interleaved with the right column's
medication list, one line each, producing a document that parses cleanly and
says something that was never written.

## Limits

- Images only. PDF needs `pdf2image` plus Poppler; export the page as PNG instead.
- The grid assumes roughly horizontal text. Skewed scans need deskewing first.
- Proportional fonts reconstruct approximately — the advance is a page-wide
  median, so a line of all-caps or all-italics drifts by a character or two.
- Everything runs locally and nothing is uploaded anywhere. The sample page is
  generated, and every name and figure on it is fabricated.
