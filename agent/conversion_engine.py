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
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

from agent.observability.tracing import observe
from agent.enrichment.pipeline import EnrichmentPipeline, HiringSignalBrief
from agent.integrations.resend_client import send_email
from agent.integrations.hubspot_mcp import log_email_sent, create_enriched_contact
from agent.integrations.africas_talking import send_sms
from .prompts import build_subject, build_email_prompt, build_fallback_html, build_discovery_brief

load_dotenv()

logger = logging.getLogger(__name__)


class ConversionEngine:
    """Orchestrate enrichment -> email generation -> CRM logging for a single lead."""

    def __init__(self) -> None:
        self.enrichment = EnrichmentPipeline()
        self._llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self._llm_key = os.environ["OPENROUTER_API_KEY"]
        # EMAIL_MODEL: higher quality, customer-facing outreach copy
        raw_email = os.getenv("EMAIL_MODEL", "qwen/qwen3-next-80b-a3b-thinking")
        self._email_model = raw_email.removeprefix("openrouter/")

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
        segment_override: Optional[str] = None,
        confidence_override: Optional[float] = None,
    ) -> dict:
        """Run the full pipeline for a single prospect.

        Returns a summary dict with keys: company, segment, email, crm, brief_path.
        """
        logger.info("process_lead.start company=%s domain=%s email=%s", company_name, domain, prospect_email)

        # 1. Enrich
        logger.info("step=enrich company=%s", company_name)
        brief = self.enrichment.run(company_name, domain)
        # Allow the outbound ICP classifier to override enrichment-derived segment
        if segment_override:
            brief.primary_segment_match = segment_override
        if confidence_override is not None:
            brief.segment_confidence = confidence_override

        logger.info(
            "step=enrich.done company=%s segment=%s ai_maturity=%s/3 confidence=%.2f",
            company_name, brief.primary_segment_match, brief.ai_maturity.get("score", 0), brief.segment_confidence,
        )

        # GATING: Skip if unclassified or capacity gap detected
        if brief.primary_segment_match == "abstain" or brief.segment_confidence < 0.6:
            logger.warning("step=skip reason=unclassified company=%s", company_name)
            return {"company": company_name, "status": "skipped", "reason": "insufficient_signal"}
        
        if not brief.bench_to_brief_match.get("bench_available"):
            logger.warning("step=skip reason=bench_gap company=%s gaps=%s", company_name, brief.bench_to_brief_match.get("gaps"))
            return {"company": company_name, "status": "skipped", "reason": "bench_capacity_gap"}

        # 2. Generate email (Composer phase)
        logger.info("step=generate_email prospect=%s model=%s", prospect_name or "unknown", self._email_model)
        subject = build_subject(brief)
        email_html = self._generate_email(brief, prospect_name)
        logger.info("step=generate_email.done subject=%r length=%d chars", subject, len(email_html))

        # 3. Send via Resend
        logger.info("step=send_email to=%s subject=%r", prospect_email, subject)
        email_result = send_email(
            to=prospect_email,
            subject=subject,
            html=email_html,
        )
        logger.info("step=send_email.done id=%s routed_to=%s", email_result.get("id"), email_result.get("routed_to"))

        # 3b. Log the outbound email event via HubSpot MCP
        try:
            log_email_sent(prospect_email, subject, email_html)
            logger.info("step=mcp_log_email.done email=%s", prospect_email)
        except Exception as mcp_err:
            logger.warning("step=mcp_log_email.failed exc=%s", mcp_err)

        # 4. Create HubSpot contact via MCP with ICP classification and enrichment metadata.
        logger.info("step=create_contact email=%s company=%s", prospect_email, company_name)
        crm_result_raw = create_enriched_contact(
            email=prospect_email,
            firstname=prospect_name.split()[0] if prospect_name else "",
            lastname=" ".join(prospect_name.split()[1:]) if prospect_name else "",
            company=company_name,
            domain=domain,
            icp_segment=brief.primary_segment_match or "abstain",
            enrichment_timestamp=brief.generated_at,
            ai_maturity_score=brief.ai_maturity.get("score", 0),
            segment_confidence=brief.segment_confidence,
            has_recent_funding=brief.buying_window_signals.get("funding_event", {}).get("detected", False),
            has_recent_layoffs=brief.buying_window_signals.get("layoff_event", {}).get("detected", False),
            hiring_signal_strength=brief.hiring_velocity.get("velocity_label", "none"),
        )
        crm_result = json.loads(crm_result_raw) if isinstance(crm_result_raw, str) else crm_result_raw
        logger.info("step=create_contact.done id=%s conflict=%s", crm_result.get("id"), crm_result.get("conflict"))

        # 5. Persist competitor gap brief and discovery call context brief
        gap_path = self._save_competitor_gap_brief(brief)
        discovery_path = self._save_discovery_brief(
            brief, prospect_name, prospect_email, prospect_phone
        )

        logger.info(
            "process_lead.done company=%s segment=%s email_id=%s crm_id=%s",
            company_name, brief.primary_segment_match, email_result.get("id"), crm_result.get("id"),
        )
        return {
            "company": company_name,
            "segment": brief.primary_segment_match,
            "email": email_result,
            "crm": crm_result,
            "brief_path": str(Path(__file__).parent / "outputs" / "hiring_signal_brief.json"),
            "gap_brief_path": str(gap_path) if gap_path else None,
            "discovery_brief_path": str(discovery_path) if discovery_path else None,
        }

    @observe(name="conversion_engine.sms_followup")
    def send_sms_followup(
        self,
        phone: str,
        company_name: str,
        warm_lead: bool = False,
        booking_url: str = "https://cal.com/tenacious/discovery",
    ) -> dict:
        """Send an SMS follow-up. SMS is a warm-lead channel only — must not be used for cold outreach.

        Args:
            warm_lead: Must be True (confirming prior email reply) before SMS is sent.
        """
        if not warm_lead:
            raise ValueError(
                "SMS is a warm-lead channel. Set warm_lead=True only after a confirmed email reply."
            )
        logger.info("sms_followup phone=%s company=%s", phone, company_name)
        message = (
            f"Hi! Following up re Tenacious intro for {company_name}. "
            f"Book a quick 20-min discovery call: {booking_url}"
        )
        result = send_sms(to=phone, message=message)
        logger.info("sms_followup.done routed_to=%s", result.get("routed_to"))
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @observe(name="conversion_engine.generate_email")
    def _generate_email(self, brief: HiringSignalBrief, prospect_name: str) -> str:
        """Call EMAIL_MODEL to write outreach email; fall back to static template on error."""
        prompt = build_email_prompt(brief, prospect_name)
        # Prepend the enrichment-generated signal summary if available
        if brief.signal_summary:
            prompt = f"Enrichment summary: {brief.signal_summary}\n\n{prompt}"
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(
                    f"{self._llm_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._llm_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._email_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a Delivery Lead at Tenacious Intelligence writing a research-grounded outreach email. "
                                    "Your tone is Direct, Grounded, Honest, Professional, and Non-condescending. "
                                    "Max 120 words. One clear ask. HTML <p> tags only. No emojis."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 600,
                    },
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                if content is None:
                    return build_fallback_html(brief, prospect_name)
                return content
        except Exception as exc:
            logger.warning("generate_email.llm_failed exc=%s using_fallback=true", exc)
            return build_fallback_html(brief, prospect_name)

    def _save_discovery_brief(
        self,
        brief: HiringSignalBrief,
        prospect_name: str,
        prospect_email: str,
        prospect_phone: Optional[str],
    ) -> Optional[Path]:
        try:
            content = build_discovery_brief(brief, prospect_name, prospect_email, prospect_phone)
            output_dir = Path(__file__).parent / "outputs"
            output_dir.mkdir(exist_ok=True)
            path = output_dir / "discovery_brief.txt"
            path.write_text(content, encoding="utf-8")
            logger.info("discovery_brief saved path=%s", path)
            return path
        except Exception as exc:
            logger.warning("discovery_brief.save_failed exc=%s", exc)
            return None

    def _save_competitor_gap_brief(self, brief: HiringSignalBrief) -> Optional[Path]:
        if not brief.competitor_gap:
            return None
        output_dir = Path(__file__).parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        path = output_dir / "competitor_gap_brief.json"
        with open(path, "w") as f:
            json.dump(brief.competitor_gap, f, indent=2)
        logger.info("competitor_gap_brief saved path=%s", path)
        return path
