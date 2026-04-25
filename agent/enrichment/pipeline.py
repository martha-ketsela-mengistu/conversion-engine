"""Main enrichment pipeline orchestrator."""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

import httpx
from dotenv import load_dotenv

from agent.observability.tracing import observe

load_dotenv()

logger = logging.getLogger(__name__)

from .crunchbase import CrunchbaseEnricher
from .layoffs import LayoffsEnricher
from .jobs import JobScraper
from .ai_maturity import AIMaturityScorer
from .competitor_gap import CompetitorGapAnalyzer


@dataclass
class HiringSignalBrief:
    """Complete hiring signal brief for a prospect."""
    prospect_domain: str
    prospect_name: str
    generated_at: str
    primary_segment_match: str  # segment_1_series_a_b, etc.
    segment_confidence: float
    ai_maturity: Dict[str, Any]
    hiring_velocity: Dict[str, Any]
    buying_window_signals: Dict[str, Any]
    tech_stack: List[str]
    bench_to_brief_match: Dict[str, Any]
    data_sources_checked: List[Dict[str, Any]]
    honesty_flags: List[str]
    firmographics: Dict[str, Any] = field(default_factory=dict)  # Keep for internal use
    competitor_gap: Optional[Dict[str, Any]] = field(default=None)
    signal_summary: Optional[str] = field(default=None)


class EnrichmentPipeline:
    """Orchestrate all enrichment sources into a unified brief."""

    def __init__(self):
        self.crunchbase = CrunchbaseEnricher()
        self.layoffs = LayoffsEnricher()
        self.job_scraper = JobScraper()
        self.ai_scorer = AIMaturityScorer()
        self.gap_analyzer = CompetitorGapAnalyzer()

    @observe(name="enrichment.pipeline.run")
    def run(self, company_name: str, domain: str) -> HiringSignalBrief:
        """Run full enrichment pipeline for a prospect."""

        firmographics = self.crunchbase.get_company(company_name) or {}
        funding_events = self.crunchbase.get_funding_events(company_name, days=180)
        layoff_events = self.layoffs.get_layoffs(company_name, days=120)
        job_velocity = self.job_scraper.get_job_velocity(company_name, domain)
        leadership_changes = self.crunchbase.detect_leadership_change(company_name, days=90)

        ai_maturity_score = self.ai_scorer.score(
            job_posts=job_velocity.get("recent_posts", []),
            team_page=None,
            github_org=firmographics.get("website", ""),
            executive_posts=[],
            tech_stack=self._extract_tech_stack(firmographics),
            press_mentions=[],
        )

        primary_segment, segment_confidence = self._classify_segment(
            firmographics, funding_events, layoff_events, leadership_changes, ai_maturity_score
        )

        # Competitor gap analysis for segment 1 and 2 only
        competitor_gap = None
        if primary_segment in ["segment_1_series_a_b", "segment_2_mid_market_restructure"]:
            competitor_gap = self.gap_analyzer.analyze(
                company_name,
                firmographics.get("industries", []),
                ai_maturity_score,
            )

        # Buying window signals (BuyingWindowSignals schema)
        funding = funding_events[0] if funding_events else {}
        layoff = layoff_events if layoff_events else {}
        leadership = leadership_changes[0] if leadership_changes else {}
        
        buying_window = {
            "funding_event": {
                "detected": bool(funding),
                "stage": funding.get("type", "none"),
                "amount_usd": funding.get("amount_usd"),
                "closed_at": funding.get("date"),
                "source_url": None,
            },
            "layoff_event": {
                "detected": layoff.get("has_recent_layoffs", False),
                "date": layoff.get("date"),
                "headcount_reduction": layoff.get("headcount_reduction"),
                "percentage_cut": layoff.get("percentage_cut"),
                "source_url": None,
            },
            "leadership_change": {
                "detected": leadership.get("detected", False),
                "role": "cto" if "cto" in leadership.get("evidence", "").lower() else "vp_engineering",
                "new_leader_name": None,
                "started_at": leadership.get("date"),
                "source_url": None,
            }
        }

        # Bench to brief match
        tech_stack = self._extract_tech_stack(firmographics)
        bench_match = self._check_bench_match(tech_stack)

        # Honesty flags
        honesty_flags = []
        if job_velocity.get("confidence", 0) < 0.6:
            honesty_flags.append("weak_hiring_velocity_signal")
        if ai_maturity_score.confidence < 0.6:
            honesty_flags.append("weak_ai_maturity_signal")
        if bench_match.get("gaps"):
            honesty_flags.append("bench_gap_detected")

        brief = HiringSignalBrief(
            prospect_domain=domain,
            prospect_name=company_name,
            generated_at=datetime.now().isoformat(),
            primary_segment_match=primary_segment,
            segment_confidence=segment_confidence,
            ai_maturity={
                "score": ai_maturity_score.score,
                "confidence": ai_maturity_score.confidence,
                "justifications": [
                    {
                        "signal": name,
                        "status": "detected" if val else "not_detected",
                        "weight": self.ai_scorer.SIGNAL_WEIGHTS.get(name, "low"),
                        "confidence": "medium",
                        "source_url": None
                    } for name, val in ai_maturity_score.signals.items()
                ]
            },
            hiring_velocity={
                "open_roles_today": job_velocity.get("open_engineering_roles", 0),
                "open_roles_60_days_ago": 0,  # Placeholder as we don't have historical in the sample
                "velocity_label": job_velocity.get("velocity_label", "flat"),
                "signal_confidence": job_velocity.get("confidence", 0.0),
                "sources": ["company_careers_page"]
            },
            buying_window_signals=buying_window,
            tech_stack=tech_stack,
            bench_to_brief_match=bench_match,
            data_sources_checked=[
                {"source": "crunchbase", "status": "success" if firmographics else "no_data"},
                {"source": "layoffs.fyi", "status": "success" if layoff_events else "no_data"},
                {"source": "job_boards", "status": "success" if job_velocity else "no_data"},
            ],
            honesty_flags=honesty_flags,
            firmographics=firmographics,
            competitor_gap=competitor_gap,
            signal_summary=self._summarise_signals(brief_data={
                "company": company_name,
                "segment": primary_segment,
                "employees": firmographics.get("employee_count"),
                "industries": firmographics.get("industries", []),
                "funding_events": len(funding_events),
                "has_layoffs": bool(layoff_events and layoff_events.get("has_recent_layoffs")),
                "leadership_changes": len(leadership_changes),
                "ai_score": ai_maturity_score.score,
                "ai_evidence": ai_maturity_score.evidence[:3],
                "hiring_strength": job_velocity.get("hiring_signal_strength", "none"),
            }),
        )

        self._save_brief(brief)
        return brief

    def _classify_segment(
        self,
        firmographics: Dict,
        funding_events: list,
        layoff_events: Optional[Dict],
        leadership_changes: list,
        ai_maturity_score: Any = None,
    ) -> tuple[str, float]:
        """
        Classify prospect into one of four ICP segments or abstain.
        Rules from seed/icp_definition.md.
        """
        employee_count = firmographics.get("employee_count", 0) or 0
        has_layoffs = bool(layoff_events and layoff_events.get("has_recent_layoffs"))
        has_funding = bool(funding_events)
        has_leadership = bool(leadership_changes)
        ai_score = ai_maturity_score.score if hasattr(ai_maturity_score, "score") else 0

        # Rule 1: Layoff AND fresh funding -> Segment 2
        if has_layoffs and has_funding:
            if 200 <= employee_count <= 2000:
                return "segment_2_mid_market_restructure", 0.90
            return "segment_2_mid_market_restructure", 0.70

        # Rule 2: New CTO/VP Eng in last 90 days -> Segment 3
        if has_leadership:
            if 50 <= employee_count <= 500:
                return "segment_3_leadership_transition", 0.85
            return "segment_3_leadership_transition", 0.60

        # Rule 3: Specialized capability signal AND AI-readiness >= 2 -> Segment 4
        if ai_score >= 2:
            return "segment_4_specialized_capability", 0.75

        # Rule 4: Fresh funding in last 180 days -> Segment 1
        if has_funding:
            if 15 <= employee_count <= 80:
                return "segment_1_series_a_b", 0.85
            return "segment_1_series_a_b", 0.65

        return "abstain", 0.0

    @observe(name="enrichment.summarise_signals")
    def _summarise_signals(self, brief_data: Dict) -> Optional[str]:
        """Use ENRICHMENT_MODEL to produce a 1-2 sentence signal summary for the brief."""
        llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        raw_model = os.getenv("ENRICHMENT_MODEL", "qwen/qwen3.5-flash-02-23")
        model = raw_model.removeprefix("openrouter/")
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return None

        prompt = (
            f"Summarise the following B2B sales signals for {brief_data['company']} "
            f"in exactly 1-2 sentences. Be specific and factual. No filler words.\n\n"
            f"Signals: {json.dumps(brief_data)}"
        )
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    f"{llm_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 120,
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            print(f"[EnrichmentPipeline] Signal summary skipped ({exc})")
            return None

    def _leadership_confidence(self, leadership_changes: list) -> float:
        if not leadership_changes:
            return 0.0
        raw = leadership_changes[0].get("confidence", 0.0)
        if isinstance(raw, str):
            return {"high": 0.90, "medium": 0.60, "low": 0.30}.get(raw.lower(), 0.50)
        return float(raw)

    def _extract_tech_stack(self, firmographics: Dict) -> list:
        return list(set(firmographics.get("categories", []) + firmographics.get("industries", [])))

    def _check_bench_match(self, tech_stack: List[str]) -> Dict[str, Any]:
        """Check if required stacks are available in seed/bench_summary.json."""
        summary_path = Path(__file__).parent.parent / "data" / "tenacious_sales_data" / "seed" / "bench_summary.json"
        if not summary_path.exists():
            return {"required_stacks": tech_stack, "bench_available": False, "gaps": tech_stack}
        
        with open(summary_path) as f:
            summary = json.load(f)
        
        available_stacks = summary.get("stacks", {})
        required = []
        gaps = []
        
        stack_keywords = {
            "python": ["python", "django", "fastapi", "flask"],
            "go": ["go", "golang", "microservices"],
            "data": ["data", "dbt", "snowflake", "databricks"],
            "ml": ["ml", "ai", "machine learning", "pytorch"],
            "infra": ["infra", "terraform", "aws", "gcp", "kubernetes"],
        }
        
        for ts in tech_stack:
            ts_lower = ts.lower()
            found_stack = None
            for stack_name, kws in stack_keywords.items():
                if any(kw in ts_lower for kw in kws):
                    found_stack = stack_name
                    break
            
            if found_stack:
                required.append(found_stack)
                if available_stacks.get(found_stack, {}).get("available_engineers", 0) <= 0:
                    gaps.append(found_stack)
            else:
                # If we can't map it, assume we don't have it (conservative)
                gaps.append(ts)
                required.append(ts)

        return {
            "required_stacks": list(set(required)),
            "bench_available": len(gaps) == 0,
            "gaps": list(set(gaps))
        }
    @observe(name="enrichment.summarise_signals")
    def _summarise_signals(self, brief_data: Dict) -> str:
        """Generate a 1-2 sentence signal summary using LLM."""
        llm_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        model = os.getenv("ENRICHMENT_MODEL", "qwen/qwen3.5-flash-02-23").removeprefix("openrouter/")

        if not api_key:
            return "Signals detected: " + str(brief_data)

        prompt = (
            f"Summarize these B2B signals into 1-2 professional sentences for a sales team:\n"
            f"{json.dumps(brief_data, indent=2)}\n\n"
            "Focus on why now is a good time to reach out. Be direct and grounded."
        )

        try:
            with httpx.Client(timeout=10) as client:
                r = client.post(
                    f"{llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}]}
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("summarise_signals.llm_failed exc=%s", e)
            return f"Company {brief_data['company']} showing {brief_data['segment']} signals with AI maturity {brief_data.get('ai_score', brief_data.get('ai_maturity', 0))}/3."

    def _save_brief(self, brief: HiringSignalBrief) -> None:
        output_dir = Path(__file__).parent.parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "hiring_signal_brief.json"
        with open(output_path, "w") as f:
            json.dump(asdict(brief), f, indent=2, default=str)
        print(f"Saved hiring signal brief to {output_path}")
