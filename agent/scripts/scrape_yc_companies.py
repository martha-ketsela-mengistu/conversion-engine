"""Scrape YC company directory for recent batches and save as ICP seed data.

Intercepts the Algolia search API calls YC makes when rendering the page —
gives clean structured JSON without fragile DOM selectors.

Usage:
    uv run python agent/scripts/scrape_yc_companies.py
    uv run python agent/scripts/scrape_yc_companies.py --batches W25 S25
    uv run python agent/scripts/scrape_yc_companies.py --batches S25 --max 50

Output: agent/data/yc_companies.csv  (Crunchbase-compatible schema)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Route, async_playwright

ROOT = Path(__file__).parent.parent.parent
OUTPUT = ROOT / "agent" / "data" / "yc_companies.csv"

# YC batch → approximate Demo Day date (used as funding proxy)
_BATCH_DATES = {
    "W25": "2025-03-25",
    "S25": "2025-09-15",
    "W24": "2024-03-19",
    "S24": "2024-09-17",
    "W23": "2023-03-29",
    "S23": "2023-09-12",
}

# YC seed amount: $500K standard + avg additional checks ~$1-3M
_YC_SEED_USD = 2_000_000

FIELDNAMES = [
    "name", "website", "num_employees", "country_code",
    "industries", "funding_rounds_list", "about", "yc_batch",
]


def _batch_to_funding_round(batch: str, company_name: str) -> list[dict]:
    """Represent the YC seed round in Crunchbase funding_rounds_list format."""
    date = _BATCH_DATES.get(batch, "2025-01-01")
    return [
        {
            "title": f"Seed Round - {company_name}",
            "announced_on": date,
            "uuid": f"yc-{batch.lower()}-{re.sub(r'[^a-z0-9]', '-', company_name.lower())}",
            "raised_usd": _YC_SEED_USD,
        }
    ]


def _parse_algolia_hits(hits: list[dict]) -> list[dict]:
    """Map Algolia hit fields → Crunchbase-compatible row."""
    rows = []
    for h in hits:
        name = h.get("name", "").strip()
        if not name:
            continue

        website = h.get("website") or h.get("url") or ""
        website = website.strip()

        batch = h.get("batch", "")
        country = "US"  # YC is overwhelmingly US; override if location gives a clue
        location = h.get("location", "")
        if any(x in location for x in ["London", "UK", "England"]):
            country = "GB"
        elif any(x in location for x in ["Berlin", "Munich", "Germany"]):
            country = "DE"
        elif any(x in location for x in ["Paris", "France"]):
            country = "FR"
        elif any(x in location for x in ["Canada", "Toronto", "Vancouver"]):
            country = "CA"

        tags = h.get("tags", []) or []
        industries = json.dumps([{"id": t.lower().replace(" ", "_"), "value": t} for t in tags])

        rows.append({
            "name": name,
            "website": website,
            "num_employees": "1-20",   # typical early YC company
            "country_code": country,
            "industries": industries,
            "funding_rounds_list": json.dumps(_batch_to_funding_round(batch, name)),
            "about": (h.get("one_liner") or h.get("long_description") or "")[:200],
            "yc_batch": batch,
        })
    return rows


async def scrape(batches: list[str], max_per_batch: int) -> list[dict]:
    all_rows: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # Intercept Algolia API responses
        captured_hits: list[dict] = []

        async def handle_response(response):
            url = response.url
            if "algolia" in url and response.status == 200:
                try:
                    body = await response.json()
                    # Algolia returns {"results": [{"hits": [...]}]}
                    for result in body.get("results", [body]):
                        hits = result.get("hits", [])
                        if hits:
                            captured_hits.extend(hits)
                            print(f"  [Algolia] captured {len(hits)} hits from {url[:80]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        for batch in batches:
            print(f"\nScraping batch {batch}...")
            captured_hits.clear()
            url = f"https://www.ycombinator.com/companies?batch={batch}"

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                await page.goto(url, timeout=30000)

            await page.wait_for_timeout(4000)

            # Scroll to trigger lazy loads
            for _ in range(8):
                await page.evaluate("window.scrollBy(0, 1200)")
                await page.wait_for_timeout(800)

            # If Algolia interception worked, use those hits
            if captured_hits:
                print(f"  Algolia hits: {len(captured_hits)}")
                batch_rows = _parse_algolia_hits(captured_hits)
            else:
                # DOM fallback
                print("  Algolia intercept empty — falling back to DOM scraping")
                batch_rows = await _dom_scrape(page, batch)

            # Filter to requested batch and cap
            batch_rows = [r for r in batch_rows if not r["yc_batch"] or r["yc_batch"] == batch]
            batch_rows = batch_rows[:max_per_batch]
            print(f"  {batch}: {len(batch_rows)} companies extracted")
            all_rows.extend(batch_rows)

        await browser.close()

    return all_rows


async def _dom_scrape(page, batch: str) -> list[dict]:
    """Fallback: extract company data directly from rendered DOM."""
    rows = []
    try:
        # Try to find company card links — YC uses /companies/{slug} hrefs
        cards = await page.query_selector_all("a[href*='/companies/']")
        seen = set()
        for card in cards[:100]:
            href = await card.get_attribute("href") or ""
            if not href or href in seen or href == "/companies":
                continue
            seen.add(href)

            name_el = await card.query_selector("h3, h2, [class*='name'], [class*='companyName']")
            name = (await name_el.inner_text()).strip() if name_el else ""
            if not name:
                # Try text of the card itself
                text = (await card.inner_text()).strip()
                name = text.split("\n")[0].strip()[:80]
            if not name:
                continue

            desc_el = await card.query_selector("p, [class*='tagline'], [class*='description']")
            desc = (await desc_el.inner_text()).strip() if desc_el else ""

            rows.append({
                "name": name,
                "website": f"https://www.ycombinator.com{href}",
                "num_employees": "1-20",
                "country_code": "US",
                "industries": "[]",
                "funding_rounds_list": json.dumps(_batch_to_funding_round(batch, name)),
                "about": desc[:200],
                "yc_batch": batch,
            })
    except Exception as e:
        print(f"  DOM fallback error: {e}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", nargs="+", default=["S25", "W25"],
                        help="YC batches to scrape (default: S25 W25)")
    parser.add_argument("--max", type=int, default=60,
                        help="Max companies per batch (default: 60)")
    args = parser.parse_args()

    print(f"Scraping YC batches: {args.batches}  (max {args.max} per batch)")
    rows = asyncio.run(scrape(args.batches, args.max))

    if not rows:
        print("No companies found. Check internet connection or try with --batches W24.")
        sys.exit(1)

    OUTPUT.parent.mkdir(exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} companies -> {OUTPUT}")
    print("Sample:")
    for r in rows[:3]:
        print(f"  {r['name']:35} batch={r['yc_batch']}  {r['website'][:40]}")

    print(f"\nRun outbound pipeline:")
    print(f"  uv run python agent/scripts/run_outbound.py --source yc --demo --dry-run")


if __name__ == "__main__":
    main()
