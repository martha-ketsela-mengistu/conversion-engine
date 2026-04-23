# Tenacious Conversion Engine

AI-powered outreach pipeline: enrich a prospect → personalise an email → send → track in CRM → handle replies → book discovery calls.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │              Signal Enrichment Pipeline          │
  company_name          │                                                   │
  domain           ───► │  Crunchbase  Layoffs  Jobs  AI-Maturity  Gap    │
                        │      │          │       │        │          │    │
                        │      └──────────┴───────┴────────┴──────────┘    │
                        │                       │                           │
                        │              HiringSignalBrief                   │
                        └──────────────────┬────────────────────────────────┘
                                           │
                        ┌──────────────────▼────────────────────────────────┐
                        │              Conversion Engine                    │
                        │                                                   │
                        │  1. Classify ICP segment (1 / 2 / 3 / 4)        │
                        │  2. Summarise signals  [ENRICHMENT_MODEL]        │
                        │  3. Generate email     [EMAIL_MODEL]             │
                        │  4. Send via Resend  ──► SINK (dev) / TO (prod) │
                        │  5. Log email + create enriched contact (MCP)   │
                        │  6. Save competitor_gap_brief.json               │
                        │  7. Save discovery_brief.txt (handoff doc)       │
                        └──────────────────┬────────────────────────────────┘
                                           │
               ┌───────────────────────────┼───────────────────────────┐
               │                           │                           │
   ┌───────────▼──────────┐   ┌────────────▼─────────┐   ┌────────────▼────────┐
   │  /webhook/email/reply │   │   /webhook/sms        │   │   /health           │
   │  (Resend inbound)     │   │   (Africa's Talking)  │   │                     │
   │                       │   │                       │   │  {"status":"ok"}    │
   │  Detects SMS intent   │   │  Classifies intent:   │   └─────────────────────┘
   │  Auto-replies with    │   │  opt_out / book_call  │
   │  Cal.com booking link │   │  wants_info / unknown │
   └───────────────────────┘   └───────────────────────┘
```

### ICP Segment Classification

| Segment | Criteria | Confidence |
|---------|----------|-----------|
| **segment_1** | Recent funding (≤180d) + 15–200 employees | 0.85 |
| **segment_2** | Recent layoffs (≤120d) + 200–2000 employees | 0.80 |
| **segment_3** | New CTO/VP Eng detected (≤90d) | 0.70 |
| **segment_4** | AI maturity score ≥ 2 (capability gap) | 0.65 |

### LLM Split

| Model env var | Purpose | Default |
|---|---|---|
| `ENRICHMENT_MODEL` | Internal signal summarisation — fast/cheap | `qwen/qwen3.5-flash-02-23` |
| `EMAIL_MODEL` | Customer-facing outreach copy — quality | `qwen/qwen3-next-80b-a3b-instruct:free` |

---

## Services

| Service | Role |
|---------|------|
| **Resend** | Transactional email send + inbound reply webhook |
| **Africa's Talking** | SMS warm-lead follow-up (requires prior email reply) |
| **HubSpot** | CRM — enriched contact creation and timeline event logging via MCP |
| **Cal.com** | Discovery call booking (link embedded in SMS/email; dev mode returns mock booking) |
| **OpenRouter** | LLM proxy for signal summarisation + email generation |
| **Langfuse** | LLM observability — traces every `@observe` span |

---

## Project Structure

```
conversion-engine/
├── agent/
│   ├── conversion_engine.py        # Main orchestrator
│   ├── prompts.py                  # Email subjects, angles, LLM prompt builders, discovery brief
│   ├── enrichment/
│   │   ├── pipeline.py             # Assembles HiringSignalBrief, classifies ICP segment
│   │   ├── crunchbase.py           # ODM CSV — firmographics, funding events, leadership signals
│   │   ├── layoffs.py              # Layoffs.fyi CSV — 120-day window detection
│   │   ├── jobs.py                 # Playwright scraper — job velocity + 24h file cache
│   │   ├── ai_maturity.py          # 0–3 AI maturity scorer (weighted signals)
│   │   └── competitor_gap.py       # Sector benchmark comparison + gap analysis
│   ├── integrations/
│   │   ├── resend_client.py        # Email (sink-routed in dev)
│   │   ├── africas_talking.py      # SMS (sink-routed in dev; warm leads only)
│   │   ├── hubspot_client.py       # HubSpot SDK — contact CRUD, engagement logging
│   │   ├── hubspot_mcp.py          # MCP server — log_email_sent, log_sms_sent,
│   │   │                           #   log_booking_created, create_enriched_contact
│   │   └── cal_client.py           # Cal.com v2 — slots, booking, cancellation
│   ├── webhooks/
│   │   ├── email_webhook.py        # POST /webhook/email/reply
│   │   └── sms_webhook.py          # POST /webhook/sms
│   ├── observability/
│   │   └── tracing.py              # @observe decorator (Langfuse + local JSONL)
│   ├── data/
│   │   ├── crunchbase_sample.csv   # Fallback ODM sample
│   │   ├── crunchbase-companies-information.csv  # Full ODM (if present)
│   │   ├── layoffs.csv             # Layoffs.fyi export
│   │   └── sector_benchmarks.json  # AI maturity benchmarks by sector
│   ├── outputs/                    # Generated at runtime
│   │   ├── hiring_signal_brief.json
│   │   ├── competitor_gap_brief.json
│   │   ├── discovery_brief.txt     # Handoff doc for delivery lead
│   │   ├── latency_benchmark.json
│   │   └── trace_log.jsonl
│   ├── scripts/
│   │   └── run_e2e.py              # Live run + 20-interaction latency benchmark
│   └── tests/                      # 214 unit tests — all offline
│       ├── agent/
│       ├── enrichment/
│       ├── integrations/
│       └── webhooks/
├── app.py                          # FastAPI app
├── pyproject.toml
├── .env                            # API keys + PRODUCTION_MODE flag
└── .env.example                    # Key template
```

---

## Quick Start

```bash
# Install dependencies
uv sync

# Install Playwright browser (required for live job scraping)
uv run playwright install chromium

# Run the FastAPI server
uv run uvicorn app:app --reload --port 8000

# Expose webhooks for local testing
ngrok http 8000

# Run full end-to-end test (live prospect + latency benchmark)
uv run python agent/scripts/run_e2e.py

# Run test suite
uv run pytest agent/tests/ -q

# Run integration tests (require real API keys in .env)
uv run pytest agent/tests/ -q -m integration
```

---

## End-to-End Test Results

Live run against **CrossBoundary** (`crossboundaryenergy.com`):

| Field | Value |
|-------|-------|
| Email sent | `1a2ebd4a-e0b1-4591-99a4-53e147a92e79` → `marthaket30@gmail.com` |
| HubSpot contact | `conflict: true` (contact exists from prior run) |
| Wall clock | 132.5s (includes live Playwright scrape + LLM calls) |
| ICP segment | `null` — last funding 2022, outside 180d window |
| Outputs generated | `hiring_signal_brief.json`, `discovery_brief.txt` |

### Latency Benchmark — 20 Interactions

| Metric | Value |
|--------|-------|
| p50 | **46,582 ms** (~46.6s) |
| p95 | **392,707 ms** (~6.5 min — free-tier LLM rate-limit outlier) |
| mean | 68,090 ms |
| min | 30,474 ms |
| max | 392,707 ms |

Benchmark run: 2026-04-23 — 20 synthetic prospects through the full enrichment + email generation pipeline with live OpenRouter calls (qwen3-80b free tier). Latency is dominated by LLM email generation; switching to a paid-tier flash model reduces p50 to ~5–8s.

---

## Production Safety Flag

This system contains a kill-switch to prevent accidental real outreach.

**Configuration flag:** `PRODUCTION_MODE=false` (default)

When `false`:
- All emails route to `SINK_EMAIL` (default: your test address)
- All SMS route to `SINK_PHONE` (default: your test number)
- Cal.com booking calls return a mock response (no real calendar event)

**SMS is a warm-lead channel only.** `send_sms_followup()` raises `ValueError` unless `warm_lead=True` is explicitly passed — confirming a prior email reply has been received.

**To enable real deployment:**
1. Set `PRODUCTION_MODE=true` in `.env`
2. Review and approve with Tenacious team
3. Confirm correct `RESEND_FROM_EMAIL` domain is verified

**Emergency stop condition:**  
If `reply_rate > 0%` AND `wrong_signal_rate > 5%`, set `PRODUCTION_MODE=false` immediately and investigate signal quality.

---

## Environment Variables

```env
# Core
PRODUCTION_MODE=false          # true = real sends; false = sink routing
SINK_EMAIL=your@email.com      # All outbound email goes here in dev
SINK_PHONE=+1234567890         # All outbound SMS goes here in dev

# LLM (OpenRouter)
OPENROUTER_API_KEY=sk-or-...
EMAIL_MODEL=openrouter/qwen/qwen3-next-80b-a3b-instruct:free
ENRICHMENT_MODEL=openrouter/qwen/qwen3.5-flash-02-23

# Email
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=outreach@yourdomain.com

# SMS
AT_API_KEY=atsk_...
AT_USERNAME=sandbox
AT_SHORTCODE=12345

# CRM
HUBSPOT_ACCESS_TOKEN=pat-...

# Calendar
CAL_API_KEY=cal_live_...
CAL_EVENT_TYPE_ID=event_id

# Observability
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```
