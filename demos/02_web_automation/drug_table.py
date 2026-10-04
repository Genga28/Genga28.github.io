"""
Web automation: drive a real browser through a drug reference, pull the
structured facts out of each article, download each article as a PDF through
the browser's own download path, enrich from the openFDA adverse event API,
and write a three-sheet Excel workbook.

    python drug_table.py
    python drug_table.py --drugs Metformin Atorvastatin Amoxicillin
    python drug_table.py --pdfs 0 --no-fda        skip the slow parts
    python drug_table.py --headless

The workbook has three sheets, because a scrape is only worth as much as the
record of how it was taken:

    Drug reference   one row per drug, the scraped fields and the openFDA counts
    Browser session  what browser, what driver, what user agent, what window,
                     and the navigation timing of every page that was visited
    Downloads        every PDF the browser saved, with its size and page count

Why not Google: scraping the results page trips CAPTCHAs within a handful of
queries and is against their terms, which makes for a broken screen recording
and a bad habit. Wikipedia's drugbox is a stable, permissively licensed source
with the same structure on every article, its REST API renders any article to
PDF, and openFDA is a public API. All three are the right call for a demo you
want to run twice.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
import selenium
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# resolve(), not just parent. Chrome silently ignores a relative
# download.default_directory and keeps using the profile's Downloads folder,
# so a relative path here means the files land somewhere real while the wait
# loop watches an empty directory and reports a timeout.
HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DL = OUT / "pdfs"

DEFAULT_DRUGS = [
    "Metformin", "Atorvastatin", "Amoxicillin", "Omeprazole",
    "Salbutamol", "Paracetamol", "Losartan", "Sertraline",
]

# Infobox label -> our column. Wikipedia's drugbox uses these exact labels.
WANTED = {
    "trade names": "trade_names",
    "other names": "trade_names",
    "pronunciation": None,
    "routes of administration": "routes",
    "atc code": "atc_code",
    "drug class": "drug_class",
    "class": "drug_class",
    "legal status": "legal_status",
    "bioavailability": "bioavailability",
    "elimination half-life": "half_life",
    "biological half-life": "half_life",
    "chemical formula": "formula",
    "formula": "formula",
    "molar mass": "molar_mass",
    "metabolism": "metabolism",
    "excretion": "excretion",
}


@dataclass
class Drug:
    name: str
    url: str = ""
    summary: str = ""
    trade_names: str = ""
    drug_class: str = ""
    routes: str = ""
    atc_code: str = ""
    formula: str = ""
    molar_mass: str = ""
    bioavailability: str = ""
    half_life: str = ""
    metabolism: str = ""
    excretion: str = ""
    legal_status: str = ""
    fda_reports: str = ""
    top_reaction: str = ""
    load_ms: str = ""
    pdf_file: str = ""
    pdf_pages: str = ""
    pdf_mb: str = ""


# Drug classes carry Greek ("beta-lactam" is written with a real B) and the
# Windows console is cp1252, so an unguarded print raises UnicodeEncodeError
# and takes the whole run down between two successful scrapes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def log(step: str, msg: str) -> None:
    print(f"  [{step:^8}] {msg}", flush=True)


def clean(text: str, limit: int = 220) -> str:
    """Wikipedia values carry footnote markers and hard line breaks."""
    text = re.sub(r"\[\d+\]|\[[a-z]\]", "", text)
    text = " ".join(text.split())
    return text[:limit].rstrip(" ,;") if len(text) > limit else text


# --------------------------------------------------------------------------
# browser
# --------------------------------------------------------------------------
def make_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,950")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    DL.mkdir(parents=True, exist_ok=True)
    # always_open_pdf_externally is the setting that matters. Without it Chrome
    # renders the PDF in its own viewer and nothing is ever written to disk, so
    # the download wait times out on a page that looks, to a human, like it
    # worked.
    opts.add_experimental_option("prefs", {
        "download.default_directory": str(DL),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    })

    # Selenium 4.6+ ships Selenium Manager, which resolves chromedriver itself.
    return webdriver.Chrome(options=opts)


def browser_info(driver: webdriver.Chrome, headless: bool) -> list[tuple[str, str]]:
    """What the automation is actually driving.

    Worth recording with the data. A scrape that cannot say which browser and
    which driver produced it cannot be reproduced, and "it worked on my
    machine" is the usual shape of a scraping bug report.
    """
    caps = driver.capabilities or {}
    chrome = caps.get("chrome", {})
    size = driver.get_window_size()

    js = driver.execute_script("""
        return {
          ua: navigator.userAgent,
          lang: (navigator.languages || []).join(', '),
          cores: navigator.hardwareConcurrency || null,
          memory: navigator.deviceMemory || null,
          screen: screen.width + ' x ' + screen.height,
          dpr: window.devicePixelRatio,
          webdriver: navigator.webdriver,
          tz: Intl.DateTimeFormat().resolvedOptions().timeZone
        };
    """)

    rows = [
        ("Browser", f"{caps.get('browserName', '?')} {caps.get('browserVersion', '?')}"),
        ("Driver", (chrome.get("chromedriverVersion") or "?").split(" ")[0]),
        ("Selenium", selenium.__version__),
        ("Platform", str(caps.get("platformName", "?"))),
        ("Page load strategy", str(caps.get("pageLoadStrategy", "?"))),
        ("Headless", "yes" if headless else "no"),
        ("User agent", js["ua"]),
        ("Languages", js["lang"]),
        ("Timezone", js["tz"]),
        ("Window", f"{size['width']} x {size['height']}"),
        ("Screen", f"{js['screen']}  @{js['dpr']}x"),
        ("CPU cores", str(js["cores"] or "n/a")),
        ("Device memory", f"{js['memory']} GB" if js["memory"] else "n/a"),
        # True means the page can see it is being automated. The
        # excludeSwitches option above is what keeps most sites from caring.
        ("navigator.webdriver", str(js["webdriver"])),
        ("Download directory", str(DL)),
    ]
    return rows


def page_timing(driver: webdriver.Chrome) -> dict:
    """Navigation Timing for the page currently loaded.

    PerformanceNavigationTiming is the supported API; the old
    performance.timing is deprecated and returns epoch milliseconds that have
    to be differenced by hand.
    """
    try:
        t = driver.execute_script(
            "const e = performance.getEntriesByType('navigation')[0];"
            "return e ? {dom: e.domContentLoadedEventEnd, load: e.loadEventEnd,"
            " ttfb: e.responseStart, bytes: e.transferSize} : null;"
        )
    except Exception:
        return {}
    return {k: round(v) for k, v in (t or {}).items() if isinstance(v, (int, float))}


# --------------------------------------------------------------------------
# navigate and scrape
# --------------------------------------------------------------------------
# Two elements on the page answer to name="search": the visible box and a
# hidden duplicate inside the collapsed mobile form. By.NAME returns whichever
# comes first in the DOM and that is not reliably the usable one, which is why
# this is a CSS selector that gets filtered by visibility below.
SEARCH_BOX = (By.CSS_SELECTOR, "#searchInput, form#searchform input[name='search']")


def _visible_search_box(driver):
    for e in driver.find_elements(*SEARCH_BOX):
        try:
            if e.is_displayed() and e.is_enabled():
                return e
        except StaleElementReferenceException:
            continue
    return None


# Mark the node and look again. If the mark is gone the element was replaced
# since the last check, which is the only observable difference the remount
# leaves behind.
_TAG_JS = """
const e = document.querySelector('#searchInput');
if (!e) return 'none';
if (e.dataset.rpaSeen) return 'same';
e.dataset.rpaSeen = '1';
return 'new';
"""


def _stable_search_box(driver, timeout: float = 12.0, settled: int = 3):
    """Wait for a search box that will still be there when it is typed into.

    Vector server-renders the search markup, so the selector matches
    immediately and every readiness condition Selenium offers passes on the
    spot. Then Vue mounts over the same markup and swaps the node out.
    Nothing observable changes across the swap: same id, same classes, same
    enclosing form, both visible and enabled. Waiting on appearance therefore
    hands back a node that is about to be discarded, and the error arrives
    later as ElementNotInteractableException, pointing at the wrong thing.

    So mark the node from JavaScript and watch whether the mark survives.
    Three consecutive hits is about a second of the same element being in
    place, which is past the mount on any connection worth demoing.
    """
    deadline = time.time() + timeout
    same = 0
    while time.time() < deadline:
        try:
            state = driver.execute_script(_TAG_JS)
        except WebDriverException:
            state = "none"
        same = same + 1 if state == "same" else 0
        if same >= settled:
            return _visible_search_box(driver)
        time.sleep(0.35)
    return _visible_search_box(driver)


def _send(driver, keys, tries: int = 4) -> None:
    """Send keys to the search box, re-locating it each time."""
    last: Exception | None = None
    for _ in range(tries):
        box = _visible_search_box(driver)
        if box is not None:
            try:
                box.send_keys(keys)
                return
            except WebDriverException as exc:
                last = exc
        time.sleep(0.2)
    raise last or TimeoutException("search box never became writable")


def search(driver: webdriver.Chrome, wait: WebDriverWait, name: str) -> bool:
    """Type into Wikipedia's search box so the recording shows real interaction.

    Vector 2022 serves a plain input and then, once its JavaScript runs,
    replaces it with a Codex typeahead. An element located before that swap is
    detached by the time anything is sent to it, which surfaces as
    ElementNotInteractableException rather than as a stale-element error. So
    the box is re-found immediately before use and the whole thing is retried
    once, and any WebDriver error at all drops through to the canonical URL.
    """
    driver.get("https://en.wikipedia.org/wiki/Main_Page")
    for attempt in (1, 2):
        try:
            if _stable_search_box(driver) is None:
                raise TimeoutException("no usable search box")
            # Re-find before every keystroke, and never click or clear.
            # The typeahead renders a suggestion list from the third
            # character or so, and that render replaces the input node, so a
            # handle grabbed once is stale by the middle of the word. Holding
            # nothing costs one extra lookup per character and removes the
            # whole class of failure. Vue carries the value across its own
            # re-render, so the text already typed survives.
            for ch in name:                   # typed, not pasted, so it reads on camera
                _send(driver, ch)
                time.sleep(0.04)
            _send(driver, Keys.ENTER)
            wait.until(EC.presence_of_element_located((By.ID, "firstHeading")))
            if "Special:Search" in driver.current_url:
                raise TimeoutException("landed on results, not an article")
            return True
        except WebDriverException as exc:
            if attempt == 1:
                log("search", f"{name}: {type(exc).__name__}, re-finding the box")
                driver.get("https://en.wikipedia.org/wiki/Main_Page")
                continue
            log("search", f"{name}: search UI not usable, going to the article URL")

    driver.get("https://en.wikipedia.org/wiki/" + urllib.parse.quote(name))
    try:
        wait.until(EC.presence_of_element_located((By.ID, "firstHeading")))
        return True
    except TimeoutException:
        return False


def scrape(driver: webdriver.Chrome, name: str) -> Drug:
    d = Drug(name=name, url=driver.current_url)

    try:
        d.name = driver.find_element(By.ID, "firstHeading").text.strip() or name
    except NoSuchElementException:
        pass

    # First substantive paragraph.
    #
    # ".mw-parser-output > p" used to be right and now matches nothing:
    # Vector 2022 wraps the body in section divs, so no paragraph is a direct
    # child any more. The selector still resolves, still throws nothing, and
    # silently yields an empty summary column, which is the worst way for a
    # scraper to break. Walking all the paragraphs and skipping the ones
    # inside tables does not depend on the wrapper layout at all.
    d.summary = clean(driver.execute_script("""
        for (const p of document.querySelectorAll('#mw-content-text p')) {
          if (p.closest('table')) continue;
          const t = p.innerText.trim();
          if (t.length > 80) return t;
        }
        return '';
    """) or "", 400)

    # Drugbox / infobox rows
    try:
        box = driver.find_element(By.CSS_SELECTOR, "table.infobox")
    except NoSuchElementException:
        log("scrape", f"{name}: no infobox on this article")
        return d

    for row in box.find_elements(By.TAG_NAME, "tr"):
        try:
            # The drugbox breaks long labels across two lines, so the th text
            # arrives with a newline in the middle of "Routes of
            # administration" and the lookup misses it without a word of
            # complaint. Collapse the whitespace before matching.
            label = " ".join(row.find_element(By.TAG_NAME, "th").text.split()).lower()
        except NoSuchElementException:
            continue
        attr = WANTED.get(label)
        if not attr:
            continue
        try:
            value = clean(row.find_element(By.TAG_NAME, "td").text)
        except NoSuchElementException:
            continue
        if value and not getattr(d, attr):
            setattr(d, attr, value)

    return d


# --------------------------------------------------------------------------
# download the article as a PDF, through the browser
# --------------------------------------------------------------------------
def settled_downloads() -> set[Path]:
    """PDFs in the download directory that Chrome has finished writing."""
    partial = {p.with_suffix("").name for p in DL.glob("*.crdownload")}
    return {p for p in DL.glob("*.pdf") if p.name not in partial}


def download_pdf(driver: webdriver.Chrome, title: str, timeout: float = 90.0) -> Path | None:
    """Click a link to the REST render endpoint and wait for the file.

    An injected anchor rather than driver.get(): navigating straight to a URL
    that downloads leaves Chrome with no document to hand back, and the
    command either aborts or blocks until the page load timeout. A click is
    also the gesture a person would make, which is what the recording is for.
    """
    before = settled_downloads()
    url = "https://en.wikipedia.org/api/rest_v1/page/pdf/" + urllib.parse.quote(title)

    driver.execute_script("""
        const a = document.createElement('a');
        a.href = arguments[0];
        a.download = '';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        a.remove();
    """, url)

    deadline = time.time() + timeout
    while time.time() < deadline:
        new = settled_downloads() - before
        if new:
            path = max(new, key=lambda p: p.stat().st_mtime)
            size = path.stat().st_size
            time.sleep(0.8)
            if path.stat().st_size == size and size > 0:
                return path
        time.sleep(0.6)
    return None


def pdf_pages(path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return None


# --------------------------------------------------------------------------
# openFDA
# --------------------------------------------------------------------------
def enrich_openfda(d: Drug, session: requests.Session) -> None:
    """Adverse event report count and the most reported reaction. Public API,
    no key, rate limited to 240/min per IP."""
    base = "https://api.fda.gov/drug/event.json"
    q = f'patient.drug.medicinalproduct:"{d.name}"'
    try:
        r = session.get(base, params={"search": q, "limit": 1}, timeout=12)
        if r.status_code == 404:
            d.fda_reports = "0"
            return
        r.raise_for_status()
        d.fda_reports = f"{r.json()['meta']['results']['total']:,}"
    except Exception as exc:
        d.fda_reports = "n/a"
        log("openfda", f"{d.name}: {type(exc).__name__}")
        return

    try:
        r = session.get(
            base,
            params={"search": q, "count": "patient.reaction.reactionmeddrapt.exact", "limit": 1},
            timeout=12,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        if results:
            d.top_reaction = f"{results[0]['term'].title()} ({results[0]['count']:,})"
    except Exception:
        pass


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------
HEAD_FILL = "16324F"
ZEBRA = "F4F7FB"


def _style():
    from openpyxl.styles import Border, Side

    thin = Side(style="thin", color="D9E1EA")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _sheet_title(ws, text: str, sub: str, span: int) -> None:
    from openpyxl.styles import Font

    ws["A1"] = text
    ws["A1"].font = Font(size=15, bold=True, color=HEAD_FILL)
    ws["A2"] = sub
    ws["A2"].font = Font(size=10, color="6B7684")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)


def _header_row(ws, titles: list[str], widths: list[int], row: int = 4) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    border = _style()
    for i, (title, width) in enumerate(zip(titles, widths), start=1):
        c = ws.cell(row=row, column=i, value=title)
        c.font = Font(bold=True, color="FFFFFF", size=11)
        c.fill = PatternFill("solid", fgColor=HEAD_FILL)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[row].height = 24


def write_excel(drugs: list[Drug], info: list[tuple[str, str]],
                visits: list[dict], downloads: list[dict], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    border = _style()
    wb = Workbook()

    # ---- sheet 1: the data -------------------------------------------------
    cols = [
        ("name", "Drug", 18), ("drug_class", "Class", 26), ("trade_names", "Trade names", 30),
        ("routes", "Routes", 22), ("atc_code", "ATC", 14), ("formula", "Formula", 18),
        ("molar_mass", "Molar mass", 16), ("bioavailability", "Bioavailability", 18),
        ("half_life", "Half-life", 20), ("metabolism", "Metabolism", 22),
        ("fda_reports", "FDA reports", 14), ("top_reaction", "Top reported reaction", 28),
        ("pdf_pages", "PDF pages", 11), ("pdf_mb", "PDF MB", 10),
        ("load_ms", "Load ms", 10),
        ("summary", "Summary", 70), ("url", "Source", 42),
    ]
    ws = wb.active
    ws.title = "Drug reference"
    _sheet_title(ws, "Drug reference table",
                 "Wikipedia drugbox + openFDA adverse events  |  collected "
                 + time.strftime("%Y-%m-%d %H:%M"), len(cols))
    _header_row(ws, [t for _, t, _ in cols], [w for _, _, w in cols])

    wrap = ("summary", "trade_names", "metabolism")
    for r, drug in enumerate(drugs, start=5):
        data = asdict(drug)
        for i, (key, _, _) in enumerate(cols, start=1):
            value = data.get(key, "")
            # Numeric columns go in as numbers, so they sort and total.
            if key in ("pdf_pages", "load_ms") and str(value).isdigit():
                value = int(value)
            elif key == "pdf_mb" and value:
                try:
                    value = float(value)
                except ValueError:
                    pass
            c = ws.cell(row=r, column=i, value=value)
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=key in wrap)
            if key == "name":
                c.font = Font(bold=True)
            if key == "pdf_mb":
                c.number_format = "0.00"
        ws.row_dimensions[r].height = 46
        if r % 2 == 1:
            for i in range(1, len(cols) + 1):
                ws.cell(row=r, column=i).fill = PatternFill("solid", fgColor=ZEBRA)

    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{4 + len(drugs)}"

    # ---- sheet 2: what collected it ---------------------------------------
    ws2 = wb.create_sheet("Browser session")
    _sheet_title(ws2, "Browser session",
                 "The environment this run was collected in, read back off the live driver", 2)
    _header_row(ws2, ["Property", "Value"], [26, 110])
    for r, (k, v) in enumerate(info, start=5):
        a = ws2.cell(row=r, column=1, value=k)
        a.font = Font(bold=True)
        a.border = border
        b = ws2.cell(row=r, column=2, value=v)
        b.border = border
        b.alignment = Alignment(wrap_text=True, vertical="top")
        if r % 2 == 1:
            for i in (1, 2):
                ws2.cell(row=r, column=i).fill = PatternFill("solid", fgColor=ZEBRA)

    # Navigation timing, under the environment block
    start = 5 + len(info) + 2
    ws2.cell(row=start - 1, column=1, value="Navigation timing (ms)").font = Font(
        bold=True, size=12, color=HEAD_FILL)
    _header_row(ws2, ["Page", "TTFB", "DOM ready", "Load", "Transfer bytes"],
                [38, 12, 14, 12, 16], row=start)
    for r, v in enumerate(visits, start=start + 1):
        for i, key in enumerate(["page", "ttfb", "dom", "load", "bytes"], start=1):
            c = ws2.cell(row=r, column=i, value=v.get(key, ""))
            c.border = border
            if i > 1:
                c.number_format = "#,##0"

    # ---- sheet 3: what it saved -------------------------------------------
    ws3 = wb.create_sheet("Downloads")
    titles = ["Drug", "File", "Pages", "Size (MB)", "Saved at", "Folder"]
    _sheet_title(ws3, "Downloads",
                 "PDFs written by the browser itself, not fetched behind its back", len(titles))
    _header_row(ws3, titles, [18, 42, 10, 12, 20, 60])
    for r, dl in enumerate(downloads, start=5):
        for i, key in enumerate(["drug", "file", "pages", "mb", "at", "folder"], start=1):
            c = ws3.cell(row=r, column=i, value=dl.get(key, ""))
            c.border = border
            if key == "mb":
                c.number_format = "0.00"
        if r % 2 == 1:
            for i in range(1, len(titles) + 1):
                ws3.cell(row=r, column=i).fill = PatternFill("solid", fgColor=ZEBRA)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drugs", nargs="+", default=DEFAULT_DRUGS)
    ap.add_argument("--headless", action="store_true",
                    default=bool(os.environ.get("HEADLESS")),
                    help="no visible window (not great for recording)")
    ap.add_argument("--no-fda", action="store_true", help="skip the openFDA enrichment")
    ap.add_argument("--pdfs", type=int, default=3, metavar="N",
                    help="download the first N articles as PDF (0 to skip). "
                         "Wikipedia renders each one on demand, about 7 to 11 seconds")
    args = ap.parse_args()

    print(f"\n  Collecting {len(args.drugs)} drugs, {args.pdfs} as PDF\n")
    driver = make_driver(args.headless)
    wait = WebDriverWait(driver, 15)
    session = requests.Session()
    session.headers["User-Agent"] = "genga-portfolio-demo/1.0 (github.com/Genga28)"

    rows: list[Drug] = []
    visits: list[dict] = []
    downloads: list[dict] = []
    info: list[tuple[str, str]] = []

    try:
        info = browser_info(driver, args.headless)
        log("browser", f"{info[0][1]}  ·  driver {info[1][1]}  ·  {info[3][1]}")

        for i, name in enumerate(args.drugs, start=1):
            log("search", f"{i}/{len(args.drugs)}  {name}")
            if not search(driver, wait, name):
                log("skip", f"{name}: no article found")
                continue

            d = scrape(driver, name)

            t = page_timing(driver)
            if t:
                d.load_ms = str(t.get("load", ""))
                visits.append({"page": d.name, "ttfb": t.get("ttfb"), "dom": t.get("dom"),
                               "load": t.get("load"), "bytes": t.get("bytes")})

            if i <= args.pdfs:
                log("pdf", f"{d.name}: asking the browser to download the article")
                saved = download_pdf(driver, d.name)
                if saved:
                    pages = pdf_pages(saved)
                    mb = saved.stat().st_size / 1_048_576
                    d.pdf_file, d.pdf_pages, d.pdf_mb = saved.name, str(pages or ""), f"{mb:.2f}"
                    downloads.append({
                        "drug": d.name, "file": saved.name, "pages": pages,
                        "mb": round(mb, 2), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "folder": str(saved.parent),
                    })
                    log("pdf", f"{saved.name}  {pages} pages  {mb:.2f} MB")
                else:
                    log("pdf", f"{d.name}: no file appeared within 90s")

            if not args.no_fda:
                enrich_openfda(d, session)

            rows.append(d)
            log("ok", f"{d.name}: class={d.drug_class or '-'} atc={d.atc_code or '-'} "
                      f"fda={d.fda_reports or '-'} load={d.load_ms or '-'}ms")
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\n  interrupted")
    finally:
        driver.quit()

    if not rows:
        print("\n  Nothing collected.\n")
        return 1

    xlsx = OUT / "drug_reference.xlsx"
    write_excel(rows, info, visits, downloads, xlsx)
    log("excel", f"{len(rows)} drugs, {len(visits)} page timings, "
                 f"{len(downloads)} PDFs -> {xlsx}")
    try:
        os.startfile(xlsx)  # noqa: S606  - Windows only, for the recording
    except Exception:
        pass

    print("\n  Done.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
