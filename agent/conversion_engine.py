"""Conversion Engine — main orchestrator for the outreach pipeline.

Flow per lead:
  1. Enrich (Crunchbase + layoffs + job velocity + AI maturity + competitor gap)
  2. Generate personalised email via OpenRouter LLM (falls back to static template)
  3. Send email via Resend (routed to sink unless PRODUCTION_MODE=true)
  4. Create / update contact in HubSpot
  5. Save competitor_gap_brief.json to outputs/
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from observability.tracing import observe
from enrichment.pipeline import EnrichmentPipeline, HiringSignalBrief
from integrations.resend_client import send_email
from integrations.hubspot_client import create_contact
from integrations.africas_talking import send_sms
from .prompts import build_subject, build_email_prompt, build_fallback_html

load_dotenv()


class ConversionEngine:
    """Orchestrate enrichment → email generation → CRM logging for a single lead."""

    def __init__(self) -> None:
        self.enrichment = EnrichmentPipeline()
        self._llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        # Strip "openrouter/" prefix if present (OpenRouter API uses bare model IDs)
        raw_model = os.getenv("DEFAULT_MODEL", "qwen/qwen-3-235b-a22b")
        self._llm_model = raw_model.removeprefix("openrouter/")
        self._llm_key = os.environ["OPENROUTER_API_KEY"]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @observe(name="conversion_engine.process_lead")
    def process_new_lead(
        self,
        company_name: str,
        domain: str,
        prospect_email: str,
        prospect_name: str = "",
        prospect_phone: Optional[str] = None,
    ) -> dict:
        """Run the full pipeline for a single prospect.

        Returns a summary dict with keys: company, segment, email, crm, brief_path.
        """
        # 1. Enrich
        brief = self.enrichment.run(company_name, domain)

        # 2. Generate email (LLM with static fallback)
        subject = build_subject(brief)
        email_html = self._generate_email(brief, prospect_name)

        # 3. Send via Resend
        email_result = send_email(
            to=prospect_email,
            subject=subject,
            html=email_html,
        )

        # 4. Log to HubSpot
        crm_result = create_contact(
            email=prospect_email,
            properties={
                "firstname": prospect_name.split()[0] if prospect_name else "",
                "lastname": " ".join(prospect_name.split()[1:]) if prospect_name else "",
                "company": company_name,
                "icp_segment": brief.icp_segment or "none",
                "ai_maturity_score": str(brief.ai_maturity.get("score", 0)),
                "outreach_sent_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        # 5. Persist competitor gap brief
        gap_path = self._save_competitor_gap_brief(brief)

        return {
            "company": company_name,
            "segment": brief.icp_segment,
            "email": email_result,
            "crm": crm_result,
            "brief_path": str(Path("outputs/hiring_signal_brief.json").resolve()),
            "gap_brief_path": str(gap_path) if gap_path else None,
        }

    @observe(name="conversion_engine.sms_followup")
    def send_sms_followup(
        self,
        phone: str,
        company_name: str,
        booking_url: str = "https://cal.com/tenacious/discovery",
    ) -> dict:
        message = (
            f"Hi! Following up re Tenacious intro for {company_name}. "
            f"Book a quick 20-min discovery call: {booking_url}"
        )
        return send_sms(to=phone, message=message)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @observe(name="conversion_engine.generate_email")
    def _generate_email(self, brief: HiringSignalBrief, prospect_name: str) -> str:
        """Call the LLM to write the email; fall back to static template on error."""
        prompt = build_email_prompt(brief, prospect_name)
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(
                    f"{self._llm_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._llm_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._llm_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a senior SDR at Tenacious, an AI-first sales enablement firm. "
                                    "Write concise, signal-grounded cold outreach emails in plain HTML. "
                                    "Be specific — reference the prospect's actual signals. "
                                    "No fluff, no generic phrases. 3-4 short paragraphs maximum."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 600,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            print(f"[ConversionEngine] LLM call failed ({exc}), using static template.")
            return build_fallback_html(brief, prospect_name)

    def _save_competitor_gap_brief(self, brief: HiringSignalBrief) -> Optional[Path]:
        if not brief.competitor_gap:
            return None
        output_dir = Path(__file__).parent.parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        path = output_dir / "competitor_gap_brief.json"
        with open(path, "w") as f:
            json.dump(
                {
                    "company": brief.company_name,
                    "generated_at": brief.generated_at,
                    "icp_segment": brief.icp_segment,
                    "competitor_gap": brief.competitor_gap,
                },
                f,
                indent=2,
            )
        print(f"Saved competitor gap brief to {path}")
        return path
