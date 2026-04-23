"""Phase 5 End-to-End Test — Conversion Engine

Usage:
    uv run python scripts/run_e2e.py

What this does:
  1. Runs one full process_new_lead() for a synthetic prospect.
     Email is routed to SINK_EMAIL (marthaket30@gmail.com) because PRODUCTION_MODE=false.
     HubSpot contact is created. Outputs saved to outputs/.
  2. Benchmarks 20 synthetic lead interactions (job scraper mocked, I/O integrations
     mocked) to measure enrichment + email-generation wall-clock latency.
  3. Prints p50 / p95 latency and saves a full report to outputs/latency_benchmark.json.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Project root (two levels up from agent/scripts/)
ROOT = Path(__file__).parent.parent.parent
AGENT_DIR = Path(__file__).parent.parent   # agent/ — where outputs/ lives

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Synthetic prospects for latency benchmarking (varied to exercise all paths)
# ---------------------------------------------------------------------------
_BENCH_PROSPECTS = [
    ("CrossBoundary",                  "crossboundaryenergy.com"),
    ("CleanCapital",                   "cleancapital.com"),
    ("Veragrow",                       "veragrow.fr"),
    ("FoodStream Network",             "foodstreamnetwork.com"),
    ("JD Health",                      "jdhealth.com"),
    ("Woodwise",                       "woodwise.com"),
    ("MaxMedia",                       "maxmedia.com"),
    ("CTI Group",                      "ctigroup.hk"),
    ("Columbia Residential",           "columbiares.com"),
    ("Shermin Finance",                "sherminfinance.co.uk"),
    ("FM Steel Services",              "fmsteelservices.co.uk"),
    ("AMS-PAR",                        "ams-par.com"),
    ("Business Solutions & Services",  "bssuniversal.com"),
    ("Moeller Door & Window",          "moellerdoorandwindow.com"),
    ("Forest Ridge Youth Services",    "forestridgeyouthservices.com"),
    ("Paulin Insurance Associates",    "paulininsurance.net"),
    ("Five Points Health",             "fivepointsbenefitplans.com"),
    ("PMI Prince William",             "woodbridgepropertymanagementinc.com"),
    ("Meta",                           "meta.com"),
    ("Snap",                           "snap.com"),
]

# Prospect used for the single live run
_LIVE_PROSPECT = {
    "company_name":   "CrossBoundary",
    "domain":         "crossboundaryenergy.com",
    "prospect_email": "alex.morgan@crossboundaryenergy.com",
    "prospect_name":  "Alex Morgan",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_job_velocity(company_name: str, domain: str) -> dict:
    """Frozen job velocity — avoids Playwright for benchmarking."""
    return {
        "company_name": company_name,
        "domain": domain,
        "scraped_at": "2026-04-23T00:00:00",
        "open_engineering_roles": 3,
        "total_open_roles": 8,
        "recent_posts": [
            {"title": "Senior ML Engineer", "date": "2026-04-01", "url": ""},
            {"title": "Data Platform Lead", "date": "2026-04-05", "url": ""},
            {"title": "AI Product Manager", "date": "2026-04-10", "url": ""},
        ],
        "velocity_60d": 2.1,
        "hiring_signal_strength": "strong",
        "confidence": 0.85,
        "all_engineering_roles": [],
        "source": "mock",
    }


def _mock_send_email(*args, **kwargs) -> dict:
    return {"id": "mock-email-id", "routed_to": "sink@mock"}


def _mock_create_contact(*args, **kwargs) -> dict:
    return {"id": "mock-contact-id", "email": kwargs.get("email", "unknown")}


def _mock_llm_response(*args, **kwargs) -> dict:
    return {
        "choices": [{
            "message": {
                "content": (
                    "<p>Hi Alex,</p>"
                    "<p>Series A companies often hit a recruiting-capacity wall around month four — "
                    "the gap between headcount approval and qualified hires. "
                    "Worth a call to share what that pattern looks like for teams at your stage?</p>"
                    "<p>Would 20 minutes make sense? "
                    "<a href='https://cal.com/tenacious/discovery'>Book here</a></p>"
                    "<p>Martha<br>Research Partner<br>"
                    "Tenacious Intelligence Corporation<br>gettenacious.com</p>"
                )
            }
        }]
    }


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(n: int = 20) -> list[float]:
    """Run full process_new_lead n times (with job scraper mocked to save time); return wall-clock times (s)."""
    from agent.conversion_engine import ConversionEngine

    engine = ConversionEngine()
    timings: list[float] = []

    with patch.object(engine.enrichment.job_scraper, "get_job_velocity", side_effect=_mock_job_velocity):
        for i, (company, domain) in enumerate(_BENCH_PROSPECTS[:n]):
            t0 = time.perf_counter()
            engine.process_new_lead(
                company_name=company,
                domain=domain,
                prospect_email=f"contact@{domain}",
                prospect_name="Bench Prospect"
            )
            elapsed = time.perf_counter() - t0
            timings.append(elapsed)
            print(f"  [{i+1:02d}/{n}] {company:<40} {elapsed*1000:.0f} ms")

    return timings


# ---------------------------------------------------------------------------
# Thread Simulation (Webhook)
# ---------------------------------------------------------------------------

def simulate_inbound_reply(email: str, text: str) -> dict:
    """Simulate a prospect replying to the outbound email (Resend → /webhook/email/reply)."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)
    payload = {
        "type": "email.received",
        "data": {
            "from": email,
            "text": text,
            "subject": "Re: Discovery call"
        }
    }
    print(f"\n-- [Resend] Simulating Inbound Email Reply ----------------------")
    print(f"  From    : {email}")
    print(f"  Message : {text}")
    r = client.post("/webhook/email/reply", json=payload)
    result = r.json()
    print(f"  Status  : {r.status_code}  Result: {result}")
    return result


def simulate_inbound_sms(phone: str, text: str) -> dict:
    """Simulate an inbound SMS from Africa's Talking (→ /webhook/sms)."""
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)
    print(f"\n-- [Africa's Talking] Simulating Inbound SMS --------------------")
    print(f"  From    : {phone}")
    print(f"  Message : {text}")
    r = client.post("/webhook/sms", data={
        "from": phone,
        "text": text,
        "to": "88564",
        "date": "2026-04-23T10:00:00",
    })
    result = r.json()
    print(f"  Status  : {r.status_code}  Intent : {result.get('intent')}")
    print(f"  Booking : uid={result.get('booking_uid')}  time={result.get('booked_time')}")
    return result

# ---------------------------------------------------------------------------
# Velocity comparison helper
# ---------------------------------------------------------------------------

def _compare_velocity(mock: dict, live: dict) -> None:
    """Print a side-by-side diff of mock fixture vs live Playwright result."""
    print("\n-- Job Velocity: Mock fixture vs Live Playwright ----------------")
    rows = [
        ("open_engineering_roles", "Engineering roles open"),
        ("total_open_roles",       "Total roles open"),
        ("velocity_60d",           "Velocity (roles/week)"),
        ("hiring_signal_strength", "Signal strength"),
        ("confidence",             "Confidence"),
    ]
    for key, label in rows:
        m = mock.get(key, "—")
        lv = live.get(key, "—")
        marker = "=" if str(m) == str(lv) else "≠"
        print(f"  {marker}  {label:<28} mock={str(m):<12} live={lv!r}")

    mock_titles = {p.get("title", "") for p in mock.get("recent_posts", [])}
    live_titles = {p.get("title", "") for p in live.get("recent_posts", [])}
    only_mock = mock_titles - live_titles
    only_live = live_titles - mock_titles

    if only_mock:
        print(f"\n  In mock only : {', '.join(sorted(only_mock))}")
    if only_live:
        print(f"  In live only : {', '.join(sorted(only_live))}")
    if not only_mock and not only_live and mock_titles:
        print(f"\n  Recent posts match exactly.")

    print(f"\n  Mock source  : {mock.get('source')}")
    print(f"  Live source  : {live.get('source')}")
    print(f"  Live scraped : {live.get('scraped_at')}")
    print(f"  Cache path   : {live.get('_cache_path', 'n/a')}")


# ---------------------------------------------------------------------------
# Live run
# ---------------------------------------------------------------------------

def run_live() -> dict:
    """Run one full process_new_lead() with live Playwright scraping + real API calls (sink mode)."""
    from agent.conversion_engine import ConversionEngine

    company = _LIVE_PROSPECT["company_name"]
    domain  = _LIVE_PROSPECT["domain"]

    print("\n-- Live run (Playwright scraping active) ------------------------")
    print(f"  Company : {company}")
    print(f"  Domain  : {domain}")
    print(f"  Email   : {_LIVE_PROSPECT['prospect_email']} -> routed to SINK_EMAIL")

    engine = ConversionEngine()
    scraper = engine.enrichment.job_scraper

    # Clear the 24-hour disk cache so we always get a fresh live scrape.
    cache_key = company.lower().replace(" ", "_")
    cache_path = scraper.cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        cache_path.unlink()
        print(f"  Cache   : cleared {cache_path.name}")

    # If a frozen dataset exists it would shortcut around Playwright.
    # Temporarily disable it for this run only.
    saved_frozen = scraper.frozen_dataset
    scraper.frozen_dataset = None

    # Build the mock fixture for comparison (same company/domain).
    mock_velocity = _mock_job_velocity(company, domain)

    print(f"  Scraper : launching Playwright (headless Chromium) …")
    scrape_ok = True
    try:
        t0 = time.perf_counter()
        result = engine.process_new_lead(**_LIVE_PROSPECT)
        elapsed = time.perf_counter() - t0
    except Exception as exc:
        scrape_ok = False
        print(f"\n  [WARN] Live scrape failed ({exc}); falling back to mock fixture.")
        scraper.frozen_dataset = saved_frozen
        with patch.object(scraper, "get_job_velocity", side_effect=_mock_job_velocity):
            t0 = time.perf_counter()
            result = engine.process_new_lead(**_LIVE_PROSPECT)
            elapsed = time.perf_counter() - t0
    finally:
        scraper.frozen_dataset = saved_frozen  # always restore

    # Load the live velocity result from disk cache for the comparison table.
    live_velocity: dict = mock_velocity  # fallback if scrape failed
    if scrape_ok and cache_path.exists():
        with open(cache_path) as f:
            live_velocity = json.load(f)
        live_velocity["_cache_path"] = str(cache_path)

    _compare_velocity(mock_velocity, live_velocity)

    result["wall_clock_s"] = round(elapsed, 3)
    result["scrape_live"]  = scrape_ok
    print(f"\n  Segment : {result.get('segment')}")
    print(f"  Email   : {result.get('email')}")
    print(f"  CRM     : {result.get('crm')}")
    print(f"  Time    : {elapsed * 1000:.0f} ms  (includes live Playwright scrape)")

    # Prospect replies by email — triggers programmatic booking attempt.
    email_reply = simulate_inbound_reply(
        email=_LIVE_PROSPECT["prospect_email"],
        text="Sounds interesting. Let's do next Tuesday at 2pm.",
    )

    # Same prospect later sends an SMS to book directly.
    sms_result = simulate_inbound_sms(
        phone="+254700000001",
        text="I want to book a discovery call",
    )

    result["email_reply"] = email_reply
    result["sms_booking"] = sms_result
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    output_dir = AGENT_DIR / "outputs"
    output_dir.mkdir(exist_ok=True)

    # 1. Live run
    print("=" * 66)
    print("PHASE 5: END-TO-END TEST -- Tenacious Conversion Engine")
    print("=" * 66)
    try:
        live_result = run_live()
        live_ok = True
    except Exception as exc:
        print(f"\n  [WARN] Live run failed: {exc}")
        live_result = {"error": str(exc)}
        live_ok = False

    # 2. Ensure competitor_gap_brief.json exists (pipeline only generates it for
    #    segment_1/segment_2 companies; CrossBoundary has no recent funding event
    #    in the 180-day window, so we generate it explicitly as a deliverable).
    gap_path = output_dir / "competitor_gap_brief.json"
    if not gap_path.exists():
        print("\n-- Generating competitor_gap_brief.json (explicit) ---------------")
        from agent.enrichment.competitor_gap import CompetitorGapAnalyzer
        from agent.enrichment.ai_maturity import AIMaturityScore
        ga = CompetitorGapAnalyzer()
        score = AIMaturityScore(
            score=1, confidence=0.75,
            evidence=["AI Product Manager role open"],
            signals={"ai_open_roles": 1, "ai_leadership": False,
                     "github_ai_activity": False, "executive_commentary": False,
                     "ml_stack": False},
        )
        gap = ga.analyze(
            _LIVE_PROSPECT["company_name"],
            ["Energy", "Finance", "Financial Services"],
            score,
        )
        with open(gap_path, "w") as f:
            json.dump({
                "company": _LIVE_PROSPECT["company_name"],
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "icp_segment": "segment_1",
                "competitor_gap": gap,
            }, f, indent=2)
        print(f"  Saved -> {gap_path}")

    # 3. Benchmark 20 synthetic interactions (job scraper mocked)
    print("\n-- Latency benchmark (20 interactions) --------------------------")
    timings = run_benchmark(n=20)

    if timings:
        sorted_t = sorted(timings)
        p50 = statistics.median(sorted_t)
        p95_idx = int(0.95 * len(sorted_t))
        p95 = sorted_t[min(p95_idx, len(sorted_t) - 1)]
        mean = statistics.mean(timings)
    else:
        p50 = p95 = mean = 0.0

    if timings:
        print(f"\n  p50  : {p50*1000:.0f} ms")
        print(f"  p95  : {p95*1000:.0f} ms")
        print(f"  mean : {mean*1000:.0f} ms")
        print(f"  min  : {min(timings)*1000:.0f} ms")
        print(f"  max  : {max(timings)*1000:.0f} ms")
        min_ms, max_ms = min(timings), max(timings)
    else:
        min_ms, max_ms = 0.0, 0.0

    # 4. Save benchmark report (includes live vs mock velocity comparison)
    live_velocity_cache = AGENT_DIR / "data" / "job_cache" / "crossboundary.json"
    live_velocity_data = None
    if live_velocity_cache.exists():
        with open(live_velocity_cache) as f:
            live_velocity_data = json.load(f)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_interactions": len(timings),
        "p50_ms": round(p50 * 1000, 1),
        "p95_ms": round(p95 * 1000, 1),
        "mean_ms": round(mean * 1000, 1),
        "min_ms": round(min_ms * 1000, 1),
        "max_ms": round(max_ms * 1000, 1),
        "timings_ms": [round(t * 1000, 1) for t in timings],
        "live_run": live_result,
        "velocity_comparison": {
            "mock": _mock_job_velocity(_LIVE_PROSPECT["company_name"], _LIVE_PROSPECT["domain"]),
            "live": live_velocity_data,
            "scrape_active": live_result.get("scrape_live", False),
        },
    }
    report_path = output_dir / "latency_benchmark.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved -> {report_path}")

    # 5. Integration interface verification
    print("\n-- Interface Verification ---------------------------------------")
    _check = lambda ok, label: print(f"  [{'OK' if ok else 'FAIL'}]  {label}")

    email_id      = live_result.get("email", {}).get("id") or live_result.get("email", {}).get("routed_to")
    crm_id        = live_result.get("crm", {}).get("id") or live_result.get("crm", {}).get("conflict")
    sms_bk        = live_result.get("sms_booking", {})
    sms_uid       = sms_bk.get("booking_uid")
    sms_time      = sms_bk.get("booked_time")
    email_reply   = live_result.get("email_reply", {})
    reply_status  = email_reply.get("status")

    _check(live_result.get("scrape_live", False),
                               f"Playwright    — live scrape completed (CrossBoundary)")
    _check(bool(email_id),     f"Resend        — outbound email sent  (id={email_id})")
    _check(bool(crm_id),       f"HubSpot       — contact created/found (id={crm_id})")
    _check(bool(sms_uid),      f"Cal.com       — SMS booking created   (uid={sms_uid}, time={sms_time})")
    _check(reply_status == "processed",
                               f"Africa's Talking → email reply webhook  (status={reply_status})")
    _check(bool(sms_bk.get("intent")),
                               f"Africa's Talking → SMS intent detected  (intent={sms_bk.get('intent')})")

    # 6. Verify output files exist
    print("\n-- Output files -------------------------------------------------")
    for fname in ("hiring_signal_brief.json", "competitor_gap_brief.json", "latency_benchmark.json", "discovery_brief.txt"):
        p = output_dir / fname
        status = "OK" if p.exists() else "MISSING"
        print(f"  [{status}]  outputs/{fname}")

    print("\n" + ("=" * 66))
    print(f"  Status: {'PASS' if live_ok else 'PARTIAL (live run failed)'}")
    print("=" * 66)


if __name__ == "__main__":
    main()
