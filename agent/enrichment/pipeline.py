"""Main enrichment pipeline orchestrator."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

import httpx
from dotenv import load_dotenv

from agent.observability.tracing import observe

load_dotenv()
from .crunchbase import CrunchbaseEnricher
from .layoffs import LayoffsEnricher
from .jobs import JobScraper
from .ai_maturity import AIMaturityScorer
from .competitor_gap import CompetitorGapAnalyzer


@dataclass
class HiringSignalBrief:
    """Complete hiring signal brief for a prospect."""
    company_name: str
    domain: str
    generated_at: str
    firmographics: Dict[str, Any]
    funding_events_180d: list
    layoff_events_120d: Optional[Dict]
    job_post_velocity: Dict[str, Any]
    leadership_changes_90d: list
    ai_maturity: Dict[str, Any]
    icp_segment: Optional[str]
    segment_confidence: float
    competitor_gap: Optional[Dict[str, Any]]
    signal_confidences: Dict[str, float] = field(default_factory=dict)
    buying_window_signals: List[str] = field(default_factory=list)
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

        icp_segment, segment_confidence = self._classify_segment(
            firmographics, funding_events, layoff_events, leadership_changes, ai_maturity_score
        )

        competitor_gap = None
        if icp_segment in ["segment_1", "segment_2"]:
            competitor_gap = self.gap_analyzer.analyze(
                company_name,
                firmographics.get("industries", []),
                ai_maturity_score,
            )

        buying_window_signals: List[str] = []
        for evt in funding_events[:2]:
            buying_window_signals.append(
                f"Funding: {evt.get('type', 'round')} closed {evt.get('date', 'recently')}"
            )
        if layoff_events:
            if layoff_events.get("has_recent_layoffs"):
                buying_window_signals.append("Layoffs: Detected within last 120 days")
            else:
                buying_window_signals.append("Layoffs: None detected in last 120 days")
        if leadership_changes:
            buying_window_signals.append(
                f"Leadership: New engineering leadership detected "
                f"({len(leadership_changes)} change(s) in 90 days)"
            )

        brief = HiringSignalBrief(
            company_name=company_name,
            domain=domain,
            generated_at=datetime.now().isoformat(),
            firmographics=firmographics,
            funding_events_180d=funding_events,
            layoff_events_120d=layoff_events,
            job_post_velocity=job_velocity,
            leadership_changes_90d=leadership_changes,
            ai_maturity={
                "score": ai_maturity_score.score,
                "confidence": ai_maturity_score.confidence,
                "evidence": ai_maturity_score.evidence,
                "signals": ai_maturity_score.signals,
            },
            icp_segment=icp_segment,
            segment_confidence=segment_confidence,
            competitor_gap=competitor_gap,
            buying_window_signals=buying_window_signals,
            signal_confidences={
                "crunchbase": 0.80 if firmographics else 0.0,
                "funding": funding_events[0].get("confidence", 0.85) if funding_events else 0.0,
                "layoffs": (layoff_events or {}).get("confidence", 0.0),
                "jobs": job_velocity.get("confidence", 0.0),
                "leadership": self._leadership_confidence(leadership_changes),
                "ai_maturity": ai_maturity_score.confidence,
            },
            signal_summary=self._summarise_signals(brief_data={
                "company": company_name,
                "segment": icp_segment,
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
    ) -> tuple[Optional[str], float]:
        """
        Classify prospect into one of four ICP segments.

        Segment 1: Recently funded Series A/B (funding in 180d, 15-200 employees)
        Segment 2: Mid-market restructuring (layoffs in 120d, 200-2000 employees)
        Segment 3: Leadership transition (new CTO/VP Eng in 90d)
        Segment 4: Capability gap (scored separately via AI maturity)
        """
        employee_count = firmographics.get("employee_count", 0) or 0

        if funding_events and 15 <= employee_count <= 200:
            return "segment_1", 0.85

        if layoff_events and layoff_events.get("has_recent_layoffs"):
            if 200 <= employee_count <= 2000:
                return "segment_2", 0.80

        if leadership_changes:
            return "segment_3", 0.70

        if ai_maturity_score and hasattr(ai_maturity_score, "score") and ai_maturity_score.score >= 2:
            return "segment_4", 0.65

        return None, 0.0

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
        return firmographics.get("categories", []) + firmographics.get("industries", [])

    def _save_brief(self, brief: HiringSignalBrief) -> None:
        output_dir = Path(__file__).parent.parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "hiring_signal_brief.json"
        with open(output_path, "w") as f:
            json.dump(asdict(brief), f, indent=2, default=str)
        print(f"Saved hiring signal brief to {output_path}")
