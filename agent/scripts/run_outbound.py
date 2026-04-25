"""Outbound pipeline entry point — reads Crunchbase ODM data, applies ICP filters,
and runs the full conversion engine for the best-matching prospect.

Usage:
    uv run python agent/scripts/run_outbound.py                   # strict ICP (180-day window)
    uv run python agent/scripts/run_outbound.py --demo            # relaxed window for demo
    uv run python agent/scripts/run_outbound.py --all             # process all qualifying leads
    uv run python agent/scripts/run_outbound.py --dry-run         # filter only, no email send
    uv run python agent/scripts/run_outbound.py --demo --dry-run  # inspect candidates, no send
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from agent.conversion_engine import ConversionEngine  # noqa: E402

# Data sources
_CRUNCHBASE = ROOT / "agent" / "data" / "crunchbase-companies-information.csv"
_YC_COMPANIES = ROOT / "agent" / "data" / "yc_companies.csv"
_SEC_COMPANIES = ROOT / "agent" / "data" / "sec_companies.csv"
_LAYOFFS = ROOT / "agent" / "data" / "layoffs.csv"
_TODAY = date.today()

# ICP-eligible country codes per spec (North America, UK, Germany, France, Nordics, Ireland)
_TARGET_CC = {"US", "CA", "GB", "DE", "FR", "NL", "SE", "DK", "NO", "FI", "IE"}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _days_since(date_str: str) -> int | None:
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            d = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
            return (_TODAY - d).days
        except ValueError:
            pass
    return None


def _parse_employees(s: str) -> tuple[int, int]:
    """Parse employee range string like '11-50' or '501+' to (lo, hi)."""
    if not s:
        return 0, 0
    s = s.strip().replace(",", "")
    if s.endswith("+"):
        lo = int(s[:-1])
        return lo, lo * 2
    parts = s.split("-")
    try:
        lo = int(parts[0])
        hi = int(parts[1]) if len(parts) > 1 else lo
        return lo, hi
    except (ValueError, IndexError):
        return 0, 0


def _latest_series_ab(frl_raw: str) -> tuple[str | None, str | None]:
    """Return (round_type, announced_on) for the most recent qualifying round.

    Accepts Series A/B plus seed rounds (YC-backed companies are Segment 1 targets).
    """
    try:
        rounds = json.loads(frl_raw)
        for r in sorted(rounds, key=lambda x: x.get("announced_on", ""), reverse=True):
            title = r.get("title", "").lower()
            if "series a" in title or "series_a" in title:
                return "series_a", r.get("announced_on")
            if "series b" in title or "series_b" in title:
                return "series_b", r.get("announced_on")
            if "seed" in title or "yc" in title or "y combinator" in title:
                return "seed", r.get("announced_on")
    except (json.JSONDecodeError, TypeError):
        pass
    return None, None


def _domain(website: str) -> str:
    return website.replace("https://", "").replace("http://", "").rstrip("/").lstrip("www.")


def _has_recent_layoff(company_name: str, days: int = 120) -> bool:
    if not _LAYOFFS.exists():
        return False
    try:
        with open(_LAYOFFS, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if company_name.lower() in row.get("company", "").lower():
                    age = _days_since(row.get("date", ""))
                    if age is not None and age <= days:
                        return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# ICP classifier
# ---------------------------------------------------------------------------

def _classify(row: dict, demo_mode: bool) -> tuple[str | None, float, list[str]]:
    """Return (segment, confidence, reasons). segment=None means abstain."""
    reasons: list[str] = []
    name = row["name"]

    rtype, announced = _latest_series_ab(row.get("funding_rounds_list", ""))
    funding_days = _days_since(announced) if announced else None
    lo, hi = _parse_employees(row.get("num_employees", ""))
    cc = row.get("country_code", "")
    website = row.get("website", "")
    recent_layoff = _has_recent_layoff(name, 120)
    recent_layoff_90 = _has_recent_layoff(name, 90)

    # Hard requirements regardless of mode
    if cc not in _TARGET_CC:
        return None, 0.0, [f"country {cc} outside ICP regions"]
    if not website:
        return None, 0.0, ["no website — cannot enrich"]

    # Funding window: strict in production, relaxed in demo
    window = 180 if not demo_mode else 99999
    fresh_funding = rtype in ("series_a", "series_b") and funding_days is not None and funding_days <= window

    # Rule: layoff + fresh funding → Segment 2
    if recent_layoff and fresh_funding:
        reasons.append(f"layoff <=120d AND {rtype} funding ({funding_days}d ago) -> cost-pressure window")
        return "segment_2_mid_market_restructure", 0.75, reasons

    # Segment 1: recently-funded Series A/B or YC seed (headcount range overlaps 15–80)
    if fresh_funding and hi >= 15 and lo <= 80:
        if recent_layoff_90:
            reasons.append("DISQUALIFIED: layoff >15% in 90d -> shifts to Segment 2")
            return None, 0.0, reasons
        filters = sum([rtype == "series_a" or rtype == "series_b", fresh_funding, 15 <= lo and hi <= 80])
        confidence = round(0.5 + 0.12 * filters, 2)
        if demo_mode and funding_days > 180:
            reasons.append(f"DEMO MODE: 180-day window relaxed (actual: {funding_days}d ago)")
            confidence = min(confidence, 0.70)  # cap confidence for older data
        reasons.append(f"{rtype.replace('_',' ').title()} announced {announced}")
        reasons.append(f"headcount {row.get('num_employees','?')} (15-80 band)")
        reasons.append(f"country {cc} in ICP regions")
        return "segment_1_series_a_b", confidence, reasons

    # Segment 2: mid-market restructure
    if lo >= 200 and recent_layoff:
        reasons.append(f"headcount {lo}+ and layoff <=120d")
        return "segment_2_mid_market_restructure", 0.65, reasons

    return None, 0.0, [f"no qualifying filter fired (rtype={rtype}, days={funding_days}, hc={lo}-{hi})"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["crunchbase", "yc", "sec"], default="crunchbase",
                        help="Data source: crunchbase (default), yc, or sec (EDGAR Form D)")
    parser.add_argument("--demo", action="store_true",
                        help="Relax 180-day funding window to find best ICP match in historical data")
    parser.add_argument("--all", action="store_true", help="Process all qualifying leads")
    parser.add_argument("--dry-run", action="store_true", help="Filter only, skip email send")
    args = parser.parse_args()

    source_file = {"yc": _YC_COMPANIES, "sec": _SEC_COMPANIES}.get(args.source, _CRUNCHBASE)
    if not source_file.exists():
        if args.source == "yc":
            _log(f"YC data not found. Run first:")
            _log(f"  uv run python agent/scripts/scrape_yc_companies.py")
        elif args.source == "sec":
            _log(f"SEC data not found. Run first:")
            _log(f"  uv run python agent/scripts/scrape_sec_companies.py")
            sys.exit(1)
        _log(f"Data file not found: {source_file}")
        sys.exit(1)

    _log(f"Source: {source_file.name} ({source_file.stat().st_size // 1024}KB)")
    if args.demo:
        _log("DEMO MODE: 180-day funding window relaxed — using best historical ICP match")

    with open(source_file, encoding="utf-8") as f:
        companies = list(csv.DictReader(f))
    _log(f"  {len(companies)} companies loaded")

    # ICP filter pass
    _log("\nApplying ICP filters...")
    qualified: list[tuple[dict, str, float, list[str]]] = []
    abstained = 0
    for row in companies:
        segment, confidence, reasons = _classify(row, demo_mode=args.demo)
        if segment and confidence >= 0.60:
            qualified.append((row, segment, confidence, reasons))
        else:
            abstained += 1

    _log(f"  Qualified: {len(qualified)}  |  Abstained/skipped: {abstained}")

    if not qualified:
        _log("No qualifying leads. Try --demo to relax the funding window.")
        sys.exit(0)

    # Sort by confidence desc, then by most recent funding
    qualified.sort(key=lambda x: x[2], reverse=True)

    to_process = qualified if args.all else qualified[:1]

    _log(f"\nTop candidates:")
    for row, seg, conf, reasons in qualified[:5]:
        domain = _domain(row.get("website", ""))
        _log(f"  {row['name'][:35]:35} {seg[:20]:22} conf={conf:.0%}  {domain}")

    if args.dry_run:
        _log("\n[DRY RUN] Skipping ConversionEngine.")
        return

    engine = ConversionEngine()

    for row, segment, confidence, reasons in to_process:
        company = row["name"]
        website = row.get("website", "")
        domain = _domain(website)
        # Synthetic contact — spec: all prospects are synthetic during challenge week
        email = f"cto@{domain}"
        prospect_name = f"CTO, {company}"
        industries = row.get("industries", "")

        _log(f"\n{'='*62}")
        _log(f"Prospect  : {company}")
        _log(f"Domain    : {domain}  (website: {website})")
        _log(f"Segment   : {segment}")
        _log(f"Confidence: {confidence:.0%}")
        _log(f"Employees : {row.get('num_employees','?')}  |  Country: {row.get('country_code','?')}")
        _log(f"Industries: {industries[:80]}")
        _log(f"Signals   :")
        for r in reasons:
            _log(f"    {r}")
        _log(f"Contact   : {email}  [synthetic — routes to SINK_EMAIL in dev mode]")
        _log(f"{'='*62}")
        _log("Running enrichment pipeline...")

        result = engine.process_new_lead(
            company_name=company,
            domain=domain,
            prospect_email=email,
            prospect_name=prospect_name,
            segment_override=segment,
            confidence_override=confidence,
        )

        _log("\nPipeline result:")
        print(json.dumps(result, indent=2, default=str))

        brief_path = Path(result.get("brief_path", "."))
        if brief_path.is_file():
            _log(f"\nHiring Signal Brief ({brief_path.name}):")
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            for key in ("ai_maturity_score", "segment", "segment_confidence",
                        "has_recent_funding", "has_recent_layoffs",
                        "hiring_signal_strength", "competitor_gap_summary"):
                if key in brief:
                    val = brief[key]
                    if isinstance(val, dict):
                        _log(f"  {key}: [present]")
                    else:
                        _log(f"  {key}: {val}")

        _log("\nDone. Check SINK_EMAIL for outbound email.")


if __name__ == "__main__":
    main()
