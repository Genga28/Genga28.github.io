"""
Web automation: drive a real browser through a drug reference, pull the
structured facts out of each article, enrich them from the openFDA adverse
event API, and write a formatted Excel workbook.

    python drug_table.py
    python drug_table.py --drugs Metformin Atorvastatin Amoxicillin
    python drug_table.py --headless --no-fda

Why not Google: scraping the results page trips CAPTCHAs within a handful of
queries and is against their terms, which makes for a broken screen recording
and a bad habit. Wikipedia's drugbox is a stable, permissively licensed source
with the same structure on every article, and openFDA is a public API. Both
are the right call for a demo you want to run twice.
"""

from __future__ import annotations

import argparse
import os
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from pathlib import Path

import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OUT = Path(__file__).parent / "output"

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


def log(step: str, msg: str) -> None:
    print(f"  [{step:^8}] {msg}", flush=True)


def clean(text: str, limit: int = 220) -> str:
    """Wikipedia values carry footnote markers and hard line breaks."""
    import re
    text = re.sub(r"\[\d+\]|\[[a-z]\]", "", text)
    text = " ".join(text.split())
    return text[:limit].rstrip(" ,;") if len(text) > limit else text


def make_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,950")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    # Selenium 4.6+ ships Selenium Manager, which resolves chromedriver itself.
    return webdriver.Chrome(options=opts)


def search(driver: webdriver.Chrome, wait: WebDriverWait, name: str) -> bool:
    """Type into Wikipedia's search box so the recording shows real interaction.
    Falls back to the canonical article URL if the search UI moves."""
    try:
        driver.get("https://en.wikipedia.org/wiki/Main_Page")
        box = wait.until(EC.element_to_be_clickable((By.NAME, "search")))
        box.clear()
        for ch in name:                       # typed, not pasted, so it reads on camera
            box.send_keys(ch)
            time.sleep(0.04)
        box.send_keys(Keys.ENTER)
        wait.until(EC.presence_of_element_located((By.ID, "firstHeading")))
        if "search" in driver.current_url.lower() and "Special:Search" in driver.current_url:
            raise TimeoutException("landed on results, not an article")
        return True
    except (TimeoutException, NoSuchElementException):
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

    # First substantive paragraph
    for p in driver.find_elements(By.CSS_SELECTOR, ".mw-parser-output > p")[:4]:
        txt = p.text.strip()
        if len(txt) > 80:
            d.summary = clean(txt, 400)
            break

    # Drugbox / infobox rows
    try:
        box = driver.find_element(By.CSS_SELECTOR, "table.infobox")
    except NoSuchElementException:
        log("scrape", f"{name}: no infobox on this article")
        return d

    for row in box.find_elements(By.TAG_NAME, "tr"):
        try:
            label = row.find_element(By.TAG_NAME, "th").text.strip().lower()
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


def write_excel(drugs: list[Drug], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    cols = [
        ("name", "Drug", 18), ("drug_class", "Class", 26), ("trade_names", "Trade names", 30),
        ("routes", "Routes", 22), ("atc_code", "ATC", 14), ("formula", "Formula", 18),
        ("molar_mass", "Molar mass", 16), ("bioavailability", "Bioavailability", 18),
        ("half_life", "Half-life", 20), ("metabolism", "Metabolism", 22),
        ("fda_reports", "FDA reports", 14), ("top_reaction", "Top reported reaction", 28),
        ("summary", "Summary", 70), ("url", "Source", 42),
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Drug reference"

    ws["A1"] = "Drug reference table"
    ws["A1"].font = Font(size=15, bold=True, color="16324F")
    ws["A2"] = f"Wikipedia drugbox + openFDA adverse events  |  collected {time.strftime('%Y-%m-%d %H:%M')}"
    ws["A2"].font = Font(size=10, color="6B7684")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))

    thin = Side(style="thin", color="D9E1EA")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head = PatternFill("solid", fgColor="16324F")

    for i, (_, title, width) in enumerate(cols, start=1):
        c = ws.cell(row=4, column=i, value=title)
        c.font = Font(bold=True, color="FFFFFF", size=11)
        c.fill = head
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[4].height = 24

    for r, drug in enumerate(drugs, start=5):
        data = asdict(drug)
        for i, (key, _, _) in enumerate(cols, start=1):
            c = ws.cell(row=r, column=i, value=data.get(key, ""))
            c.border = border
            c.alignment = Alignment(vertical="top", wrap_text=key in ("summary", "trade_names", "metabolism"))
            if key == "name":
                c.font = Font(bold=True)
        ws.row_dimensions[r].height = 46
        if r % 2 == 1:
            for i in range(1, len(cols) + 1):
                ws.cell(row=r, column=i).fill = PatternFill("solid", fgColor="F4F7FB")

    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(cols))}{4 + len(drugs)}"

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drugs", nargs="+", default=DEFAULT_DRUGS)
    ap.add_argument("--headless", action="store_true",
                    default=bool(os.environ.get("HEADLESS")),
                    help="no visible window (not great for recording)")
    ap.add_argument("--no-fda", action="store_true", help="skip the openFDA enrichment")
    args = ap.parse_args()

    print(f"\n  Collecting {len(args.drugs)} drugs\n")
    driver = make_driver(args.headless)
    wait = WebDriverWait(driver, 15)
    session = requests.Session()
    session.headers["User-Agent"] = "genga-portfolio-demo/1.0 (github.com/Genga28)"

    rows: list[Drug] = []
    try:
        for i, name in enumerate(args.drugs, start=1):
            log("search", f"{i}/{len(args.drugs)}  {name}")
            if not search(driver, wait, name):
                log("skip", f"{name}: no article found")
                continue
            d = scrape(driver, name)
            if not args.no_fda:
                enrich_openfda(d, session)
            rows.append(d)
            log("ok", f"{d.name}: class={d.drug_class or '-'} atc={d.atc_code or '-'} fda={d.fda_reports or '-'}")
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\n  interrupted")
    finally:
        driver.quit()

    if not rows:
        print("\n  Nothing collected.\n")
        return 1

    xlsx = OUT / "drug_reference.xlsx"
    write_excel(rows, xlsx)
    log("excel", f"wrote {len(rows)} rows to {xlsx}")
    try:
        import os
        os.startfile(xlsx)  # noqa: S606
    except Exception:
        pass

    print("\n  Done.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
