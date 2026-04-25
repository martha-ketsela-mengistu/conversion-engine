"""Auto-generate invoice_summary.json from eval/score_log.json and .env.

Usage:
    uv run python build_invoice_summary.py
"""

import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).parent


def _load_json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _read_env_model(key: str, fallback: str) -> str:
    """Parse .env for a model key; strip the openrouter/ prefix if present."""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].strip()
                return value.removeprefix("openrouter/")
    return fallback


def build() -> dict:
    score = _load_json("eval/score_log.json")

    avg_cost = score["avg_agent_cost"]
    n_tasks = score["evaluated_simulations"]
    total_usd = round(avg_cost * n_tasks, 2)

    # Qualification rate comes from the 20-interaction production benchmark run
    # (11/20 interactions produced a classified ICP segment). Not derivable from
    # score_log — update manually if re-run on a larger production sample.
    qualification_rate = 0.55
    cost_per_ql = round(avg_cost / qualification_rate, 4)

    email_model = _read_env_model("EMAIL_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free")
    enrichment_model = _read_env_model("ENRICHMENT_MODEL", "qwen/qwen3.5-flash-02-23")

    return {
        "period": "2026-04-19 to 2026-04-25",
        "currency": "USD",
        "line_items": [
            {
                "service": "OpenRouter (LLM)",
                "purpose": f"tau2-bench retail evaluation — {n_tasks} simulations x {score['num_trials']} trials",
                "amount_usd": total_usd,
                "basis": f"{n_tasks} tasks x ${avg_cost} avg agent cost (eval/score_log.json .avg_agent_cost)",
                "tier": "paid",
            },
            {
                "service": "OpenRouter (LLM)",
                "purpose": "Production pipeline — enrichment + email generation (20 benchmark interactions)",
                "amount_usd": 0.0,
                "basis": (
                    f"EMAIL_MODEL={email_model}; ENRICHMENT_MODEL={enrichment_model}. "
                    "Production cost not metered during challenge week — no OpenRouter invoice line generated."
                ),
                "tier": "unmetered",
            },
            {
                "service": "Resend",
                "purpose": "Transactional email send (dev mode — all routed to SINK_EMAIL)",
                "amount_usd": 0.0,
                "basis": "Free tier (3,000 emails/month). 0 real recipient emails sent.",
                "tier": "free",
            },
            {
                "service": "Africa's Talking",
                "purpose": "SMS warm-lead follow-up (sandbox)",
                "amount_usd": 0.0,
                "basis": "Sandbox environment — no charge",
                "tier": "sandbox",
            },
            {
                "service": "HubSpot",
                "purpose": "CRM contact creation and timeline events via MCP",
                "amount_usd": 0.0,
                "basis": "Developer sandbox — no charge",
                "tier": "developer_sandbox",
            },
            {
                "service": "Cal.com",
                "purpose": "Discovery call booking (dev mode returns mock booking)",
                "amount_usd": 0.0,
                "basis": "Self-hosted Docker Compose — no charge",
                "tier": "self_hosted",
            },
            {
                "service": "Langfuse",
                "purpose": "LLM observability — traces for all enrichment + email generation spans",
                "amount_usd": 0.0,
                "basis": "Cloud free tier — no charge",
                "tier": "free",
            },
        ],
        "total_usd": total_usd,
        "cost_per_task_tau2bench": avg_cost,
        "cost_per_production_interaction_usd": 0.0,
        "note_on_production_cost": (
            f"Production pipeline ran {email_model} (email) and {enrichment_model} (enrichment). "
            "No OpenRouter invoice was generated for production interactions during the challenge week. "
            "Switching to a paid flash-class model (Claude Haiku 4.5 or equivalent) would cost "
            "approximately $0.01–$0.03 per lead at current token volumes."
        ),
        "qualification_rate_observed": qualification_rate,
        "qualification_rate_basis": (
            "11 of 20 benchmark interactions produced a classified ICP segment; "
            "remainder classified as abstain (insufficient signals) or skipped by bench gate"
        ),
        "cost_per_qualified_lead_usd": cost_per_ql,
        "cost_per_qualified_lead_basis": (
            f"tau2-bench proxy: ${avg_cost} / {qualification_rate} qualification rate = ${cost_per_ql}. "
            "Rounds to <$0.05 on free tier. Challenge target: <$5."
        ),
    }


if __name__ == "__main__":
    out = ROOT / "invoice_summary.json"
    data = build()
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Written -> {out}")
    print(f"  total_usd:                  ${data['total_usd']}")
    print(f"  cost_per_qualified_lead:    ${data['cost_per_qualified_lead_usd']}")
    print(f"  qualification_rate:         {data['qualification_rate_observed']:.0%}")
    print(f"  email_model:                {data['line_items'][1]['basis'].split(';')[0].replace('EMAIL_MODEL=', '')}")
