"""
Scrape layoffs.fyi data from its embedded Airtable view.

Run once:
    uv run python scripts/scrape_layoffs.py

Requires Playwright browser:
    uv run playwright install chromium
"""

import asyncio
import csv
import re
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright


OUTPUT_PATH = Path(__file__).parent.parent / "data" / "layoffs.csv"
FIELDNAMES = ["company", "date", "headcount_affected", "percentage",
              "location", "industry", "stage", "source", "country", "funds_raised_mm"]

AIRTABLE_EMBED = (
    "https://airtable.com/embed/app1PaujS9zxVGUZ4/shroKsHx3SdYYOzeh"
    "?backgroundColor=green&viewControls=on"
)
SEPARATOR   = "Drag to adjust the number of frozen columns"
COL_HEADERS = ["Location HQ", "# Laid Off", "Date", "%", "Industry",
               "Source", "Stage", "$ Raised (mm)", "Country", "Date Added"]

_DATE_PAT   = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_URL_PAT    = re.compile(r"^https?://")
_RAISED_PAT = re.compile(r"^\$[\d,]+$")
_PCT_PAT    = re.compile(r"^\d+(\.\d+)?%$")
_COUNT_PAT  = re.compile(r"^[\d,]+$")


async def scrape() -> list[dict]:
    collected: dict[str, dict] = {}   # dedup by "company|date"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Loading Airtable embed...")
        await page.goto(AIRTABLE_EMBED, timeout=30000)
        await page.wait_for_timeout(7000)

        # Click into the grid so keyboard events reach it
        try:
            await page.click("text=Acko", timeout=5000)
        except Exception:
            await page.mouse.click(400, 300)
        await page.wait_for_timeout(500)

        stale_passes = 0
        for page_num in range(200):          # up to ~4 000 rows
            text = await page.evaluate("() => document.body.innerText")
            batch = _parse_body(text)

            before = len(collected)
            for row in batch:
                key = f"{row['company']}|{row['date']}"
                collected[key] = row

            if len(collected) == before:
                stale_passes += 1
                if stale_passes >= 4:
                    print(f"No new rows for 4 passes — stopping at {len(collected)} rows")
                    break
            else:
                stale_passes = 0

            if page_num % 20 == 0:
                print(f"Pass {page_num}: {len(collected)} unique rows")

            await page.keyboard.press("PageDown")
            await page.wait_for_timeout(400)

        await browser.close()

    return list(collected.values())


# ── Parser ─────────────────────────────────────────────────────────────────

def _parse_body(text: str) -> list[dict]:
    if SEPARATOR not in text:
        return []
    left, right = text.split(SEPARATOR, 1)

    companies = _extract_companies(left)

    # Strip column headers from right section
    for h in COL_HEADERS:
        if h in right:
            right = right[right.index(h) + len(h):]

    lines = [l.strip() for l in right.split("\n") if l.strip()]
    return _parse_rows(companies, lines)


def _extract_companies(left: str) -> list[str]:
    skip = {"Company", "Hide fields", "Filter", "Group", "Sort", ""}
    out = []
    for line in left.split("\n"):
        line = line.strip()
        if not line or line in skip or _DATE_PAT.match(line):
            continue
        if re.match(r"^\d+$", line):   # row number
            continue
        out.append(line)
    return out


def _parse_rows(companies: list[str], lines: list[str]) -> list[dict]:
    """
    Each row: ...before_fields... SOURCE_URL ...after_fields... DATE_ADDED
    Row boundary = date_added (M/D/YYYY immediately after stage/raised/country).
    Strategy: find each URL, then scan forward for date_added.
    """
    url_positions = [i for i, l in enumerate(lines) if _URL_PAT.match(l)]
    rows = []

    for idx, url_pos in enumerate(url_positions):
        url = lines[url_pos]

        # ── before fields: from end of previous row to this URL ──
        prev_end = _row_end(lines, url_positions[idx - 1]) + 1 if idx > 0 else 0
        before   = lines[prev_end:url_pos]

        # ── after fields: from URL+1 until (and including) date_added ──
        row_end  = _row_end(lines, url_pos)
        after    = lines[url_pos + 1 : row_end + 1]

        company = companies[idx] if idx < len(companies) else ""
        if not company:
            continue
        row = _map(company, before, url, after)
        if row:
            rows.append(row)

    return rows


def _row_end(lines: list[str], url_pos: int) -> int:
    """
    Find the date_added position for a row whose URL is at url_pos.
    After the URL we expect: stage, [raised], country, date_added
    date_added is a M/D/YYYY date that is NOT the event date (event date
    is always BEFORE the URL).  We scan forward for the first date that
    follows at least one non-date, non-URL field.
    """
    non_date_seen = 0
    for i in range(url_pos + 1, min(url_pos + 8, len(lines))):
        v = lines[i]
        if _URL_PAT.match(v):          # next row's URL — stop
            return i - 1
        if _DATE_PAT.match(v):
            if non_date_seen >= 1:     # this is date_added
                return i
        else:
            non_date_seen += 1
    return url_pos + min(4, len(lines) - url_pos - 1)


def _map(company: str, before: list[str], url: str, after: list[str]) -> dict | None:
    # ── before: location lines, [headcount], date, [%], industry ──
    location_parts, headcount, date_raw, pct, industry = [], "", "", "", ""
    for v in before:
        if _DATE_PAT.match(v):
            date_raw = v
        elif _PCT_PAT.match(v):
            pct = v
        elif _COUNT_PAT.match(v) and not date_raw:
            headcount = v.replace(",", "")
        elif not date_raw:
            location_parts.append(v)
        else:
            industry = v

    date_iso = _parse_date(date_raw)
    if not date_iso:
        return None

    location = " | ".join(p for p in location_parts if p and p != "Non-U.S.")
    if not location and location_parts:
        location = location_parts[0]

    # ── after: stage, [raised], country, [date_added] ──
    stage, raised, country = "", "", ""
    non_dates = [v for v in after if not _DATE_PAT.match(v)]
    for v in non_dates:
        if _RAISED_PAT.match(v):
            raised = v
        elif not stage:
            stage = v
        else:
            country = v

    headcount_clean = headcount if headcount and headcount.lower() not in ("?", "unknown") else ""

    return {
        "company":            company,
        "date":               date_iso,
        "headcount_affected": headcount_clean,
        "percentage":         pct,
        "location":           location,
        "industry":           industry,
        "stage":              stage,
        "source":             url,
        "country":            country,
        "funds_raised_mm":    raised,
    }


def _parse_date(raw: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def save(rows: list[dict]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} layoff records to {OUTPUT_PATH}")


if __name__ == "__main__":
    rows = asyncio.run(scrape())
    if rows:
        save(rows)
        print("Sample rows:")
        for r in rows[:5]:
            print(f"  {r['company']:<25} | {r['date']} | {r['headcount_affected']:>6} | {r['country']}")
    else:
        print("\nNo rows extracted.")
