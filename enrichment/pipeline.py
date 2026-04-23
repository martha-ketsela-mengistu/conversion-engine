"""Main enrichment pipeline orchestrator."""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from observability.tracing import observe
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
            firmographics, funding_events, layoff_events, leadership_changes
        )

        competitor_gap = None
        if icp_segment in ["segment_1", "segment_2"]:
            competitor_gap = self.gap_analyzer.analyze(
                company_name,
                firmographics.get("industries", []),
                ai_maturity_score,
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
        )

        self._save_brief(brief)
        return brief

    def _classify_segment(
        self,
        firmographics: Dict,
        funding_events: list,
        layoff_events: Optional[Dict],
        leadership_changes: list,
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

        return None, 0.0

    def _extract_tech_stack(self, firmographics: Dict) -> list:
        return firmographics.get("categories", []) + firmographics.get("industries", [])

    def _save_brief(self, brief: HiringSignalBrief) -> None:
        output_dir = Path(__file__).parent.parent / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / "hiring_signal_brief.json"
        with open(output_path, "w") as f:
            json.dump(asdict(brief), f, indent=2, default=str)
        print(f"Saved hiring signal brief to {output_path}")
