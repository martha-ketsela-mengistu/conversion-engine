"""Fetch recently-funded US companies from SEC EDGAR Form D filings.

Form D is filed within 15 days of a private equity raise (Series A, B, seed).
This gives us real companies that closed rounds in the last 180 days.

Usage:
    uv run python agent/scripts/scrape_sec_companies.py
    uv run python agent/scripts/scrape_sec_companies.py --days 180 --max 40

Output: agent/data/sec_companies.csv  (Crunchbase-compatible schema)
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent.parent
OUTPUT = ROOT / "agent" / "data" / "sec_companies.csv"

_EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_HEADERS = {"User-Agent": "martha@10academy.org conversion-engine-demo"}

# Target US states (proxy for ICP geography)
_US_STATES = {
    "CA", "NY", "TX", "WA", "MA", "CO", "GA", "IL",
    "FL", "VA", "NC", "OR", "MN", "AZ", "UT", "OH",
}

FIELDNAMES = [
    "name", "website", "num_employees", "country_code",
    "industries", "funding_rounds_list", "about", "sec_cik",
]


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _search_form_d(start_date: str, end_date: str, round_type: str, max_results: int) -> list[dict]:
    """Query EDGAR full-text search for Form D filings mentioning a round type."""
    params = {
        "q": f'"{round_type}"',
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "forms": "D",
        "_source": "display_names,biz_locations,biz_states,file_date,adsh,ciks",
        "from": 0,
        "size": min(max_results, 100),
    }
    try:
        r = httpx.get(_EDGAR_SEARCH, params=params, headers=_HEADERS, timeout=20)
        r.raise_for_status()
        return r.json().get("hits", {}).get("hits", [])
    except Exception as e:
        _log(f"  EDGAR search error: {e}")
        return []


def _fetch_company_details(cik: str) -> dict:
    """Fetch company metadata from EDGAR submissions API."""
    cik_padded = cik.lstrip("0").zfill(10)
    try:
        r = httpx.get(
            _EDGAR_SUBMISSIONS.format(cik=cik_padded),
            headers=_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def _guess_website(name: str) -> str:
    """Best-effort domain guess from company name."""
    clean = re.sub(r"\s+(inc\.?|corp\.?|llc\.?|ltd\.?|co\.?|technologies|tech|solutions|systems|group)$",
                   "", name.strip(), flags=re.IGNORECASE)
    clean = re.sub(r"[^a-z0-9]", "", clean.lower())
    return f"https://www.{clean}.com" if clean else ""


def _industry_from_sic(sic: str) -> list[dict]:
    _SIC_MAP = {
        "7372": "Software", "7371": "Software", "7374": "Data Services",
        "6770": "Finance", "6199": "Finance", "6159": "Finance",
        "8099": "Healthcare", "8000": "Healthcare", "5040": "Healthcare",
        "3825": "Hardware", "3674": "Semiconductors", "3669": "Hardware",
        "7389": "Business Services", "7374": "Data Services",
    }
    label = _SIC_MAP.get(str(sic), "Technology")
    return [{"id": label.lower().replace(" ", "_"), "value": label}]


_OPERATING_SUFFIXES = re.compile(
    r"\b(inc\.?|corp\.?|co\.?|ltd\.?|plc|technologies|labs|health|systems|software|ai)\s*$",
    re.IGNORECASE,
)
_VEHICLE_PHRASES = re.compile(
    r"\b(a\s+series\s+of|series\s+[ab]\s+(lp|llc|fund|qp|mar|nov|sep|aug|dec|jan)|"
    r"spv|co-invest|capital partners|commodity desk|qp partners|"
    r"supervest|cgf20|flywheel cap|what if ventur|hb-win|harbright|"
    r"rnn ventures|iron private)\b",
    re.IGNORECASE,
)

def _is_investment_vehicle(name: str) -> bool:
    """Return True if the entity is an SPV or investment vehicle, not an operating company."""
    if _VEHICLE_PHRASES.search(name):
        return True
    # If "Series A" or "Series B" appears in the name, it's likely an SPV
    # (real companies don't put their funding round in their legal name)
    if re.search(r"series\s+[ab]", name, re.IGNORECASE) and not _OPERATING_SUFFIXES.search(name):
        return True
    return False


def _build_row(hit: dict, details: dict, round_label: str, file_date: str) -> dict | None:
    src = hit.get("_source", {})
    display_names = src.get("display_names", [])
    name = display_names[0].split("(CIK")[0].strip() if display_names else details.get("name", "")
    if not name:
        return None

    biz_states = src.get("biz_states", []) or []
    biz_location = (src.get("biz_locations") or [""])[0]
    state = biz_states[0] if biz_states else ""
    if state not in _US_STATES and not details:
        return None  # skip non-target states without further data

    website = details.get("website", "") or _guess_website(name)
    sic = details.get("sic", "7372")
    industries = json.dumps(_industry_from_sic(sic))

    funding_rounds = json.dumps([
        {
            "title": f"{round_label} - {name}",
            "announced_on": file_date,
            "uuid": f"sec-{src.get('adsh', '').replace('-', '')}",
            "raised_usd": None,
        }
    ])

    # Headcount: unknown for private companies — use "11-50" as default for small startups
    num_employees = details.get("employeeCount") or "11-50"
    if isinstance(num_employees, int):
        if num_employees <= 10:
            num_employees = "1-10"
        elif num_employees <= 50:
            num_employees = "11-50"
        elif num_employees <= 200:
            num_employees = "51-200"
        else:
            num_employees = "201-500"

    about = details.get("description", "") or f"{round_label} company based in {biz_location}"

    ciks = src.get("ciks", [])

    return {
        "name": name,
        "website": website,
        "num_employees": str(num_employees),
        "country_code": "US",
        "industries": industries,
        "funding_rounds_list": funding_rounds,
        "about": about[:200],
        "sec_cik": ciks[0] if ciks else "",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=180, help="Lookback window in days (default: 180)")
    parser.add_argument("--max", type=int, default=40, help="Max companies to fetch (default: 40)")
    args = parser.parse_args()

    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=args.days)).isoformat()

    _log(f"SEC EDGAR Form D: {start_date} to {end_date}  (last {args.days} days)")

    rows: list[dict] = []
    seen_names: set[str] = set()

    for round_label, query in [("Series A", "series a"), ("Series B", "series b")]:
        _log(f"\nSearching Form D for '{query}'...")
        hits = _search_form_d(start_date, end_date, query, args.max)
        _log(f"  {len(hits)} hits returned")

        for i, hit in enumerate(hits):
            if len(rows) >= args.max:
                break
            src = hit.get("_source", {})
            file_date = src.get("file_date", "")
            ciks = src.get("ciks", [])

            display_names = src.get("display_names", [])
            name_raw = display_names[0].split("(CIK")[0].strip() if display_names else ""
            if not name_raw or name_raw.lower() in seen_names:
                continue
            if _is_investment_vehicle(name_raw):
                continue

            # Fetch company details (rate-limited to respect EDGAR fair use)
            details = {}
            if ciks:
                details = _fetch_company_details(ciks[0])
                time.sleep(0.15)  # EDGAR asks for max 10 req/s

            row = _build_row(hit, details, round_label, file_date)
            if row:
                seen_names.add(row["name"].lower())
                rows.append(row)
                _log(f"  [{len(rows):02d}] {row['name'][:40]:40} {file_date}  {row['website'][:35]}")

    if not rows:
        _log("No results found. Check network connection.")
        sys.exit(1)

    OUTPUT.parent.mkdir(exist_ok=True)
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    _log(f"\nSaved {len(rows)} companies -> {OUTPUT}")
    _log("Run the outbound pipeline:")
    _log("  uv run python agent/scripts/run_outbound.py --source sec")


if __name__ == "__main__":
    main()
