"""Competitor gap analysis for research-grounded outreach."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from agent.observability.tracing import observe
from .ai_maturity import AIMaturityScore, AIMaturityScorer
from .crunchbase import CrunchbaseEnricher


class CompetitorGapAnalyzer:
    """
    Analyze competitive positioning for a prospect.

    Compares prospect's AI maturity against top-quartile peers in the same sector.
    """

    def __init__(self):
        self.crunchbase = CrunchbaseEnricher()
        self.ai_scorer = AIMaturityScorer()
        self.sector_benchmarks = self._load_or_build_benchmarks()

    def _load_or_build_benchmarks(self) -> Dict[str, Any]:
        benchmark_path = Path(__file__).parent.parent / "data" / "sector_benchmarks.json"
        if benchmark_path.exists():
            with open(benchmark_path) as f:
                return json.load(f)
        return self._build_sector_benchmarks()

    def _build_sector_benchmarks(self) -> Dict[str, Any]:
        benchmarks: Dict[str, Any] = {}
        if self.crunchbase.df is None:
            return benchmarks

        df = self.crunchbase.df
        
        all_industries = set()
        for val in df["category_list"].dropna():
            if val.startswith("["):
                try:
                    for i in json.loads(val):
                        all_industries.add(i)
                except:
                    pass
            else:
                for i in val.split(","):
                    all_industries.add(i.strip())

        for industry in list(all_industries)[:20]:
            industry_companies = df[df["category_list"].str.contains(industry, regex=False, na=False)]
            if len(industry_companies) < 2:  # lowered threshold so it works on small samples
                continue

            maturities = []
            for _, row in industry_companies.head(10).iterrows():
                funding = row.get("total_funding_usd", 0) or 0
                employees = row.get("employee_count", 0) or 0
                if funding > 50_000_000 and employees > 100:
                    score = 3
                elif funding > 10_000_000 and employees > 50:
                    score = 2
                elif funding > 1_000_000:
                    score = 1
                else:
                    score = 0
                maturities.append(score)

            if maturities:
                benchmarks[industry] = {
                    "avg_maturity": sum(maturities) / len(maturities),
                    "top_quartile": sorted(maturities)[int(len(maturities) * 0.75)] if len(maturities) >= 4 else max(maturities),
                    "sample_size": len(maturities),
                    "practices": self._get_sector_practices(industry),
                }

        benchmark_path = Path(__file__).parent.parent / "data" / "sector_benchmarks.json"
        with open(benchmark_path, "w") as f:
            json.dump(benchmarks, f, indent=2)

        return benchmarks

    def _get_sector_practices(self, industry: str) -> List[str]:
        practices_map = {
            "software": ["Dedicated AI/ML engineering team", "Modern data stack (Snowflake/Databricks)", "MLOps infrastructure", "LLM integration in product"],
            "fintech": ["AI-powered risk assessment", "Automated underwriting", "Fraud detection ML models", "Personalized financial recommendations"],
            "healthcare": ["Clinical decision support AI", "Medical imaging ML", "Patient outcome prediction", "AI-assisted diagnostics"],
            "e-commerce": ["AI-powered recommendations", "Dynamic pricing optimization", "Inventory forecasting", "Customer service chatbots"],
            "saas": ["AI feature development", "Predictive analytics", "Automated workflows", "Natural language processing"],
        }
        industry_lower = industry.lower()
        for key, practices in practices_map.items():
            if key in industry_lower:
                return practices
        return [
            "Dedicated data/ML engineering capacity",
            "AI feature development velocity",
            "Modern data infrastructure",
            "ML model deployment pipeline",
        ]

    @observe(name="competitor_gap.analyze")
    def analyze(
        self,
        company_name: str,
        industries: List[str],
        ai_maturity: AIMaturityScore,
    ) -> Optional[Dict[str, Any]]:
        """Generate competitor gap analysis."""
        primary_sector = self._determine_primary_sector(industries)
        if not primary_sector:
            return None

        benchmark = self.sector_benchmarks.get(primary_sector, {
            "avg_maturity": 1.5,
            "top_quartile": 2,
            "sample_size": 10,
            "practices": self._get_sector_practices(primary_sector),
        })

        prospect_score = ai_maturity.score
        avg = benchmark.get("avg_maturity", 1.5)
        top_quartile = benchmark.get("top_quartile", 2)

        if prospect_score >= top_quartile:
            percentile = 75 + (prospect_score - top_quartile) * 10
        elif prospect_score >= avg:
            percentile = 50 + (prospect_score - avg) / max(top_quartile - avg, 0.1) * 25
        else:
            percentile = max(0, 50 - (avg - prospect_score) / max(avg, 0.1) * 50)
        percentile = min(99, max(1, percentile))

        gaps = self._identify_gaps(prospect_score, top_quartile, ai_maturity.evidence, benchmark.get("practices", []))
        gap_severity = self._determine_severity(prospect_score, top_quartile)
        confidence = min(0.95, max(0.3, ai_maturity.confidence * (benchmark.get("sample_size", 10) / 20)))

        practices_gap = next((g for g in gaps if g.get("category") == "practices"), None)
        top_quartile_practices_not_observed = [
            {
                "practice": p,
                "public_signal": (
                    f"Not observed in {company_name}'s public signal data; "
                    f"sector leaders consistently demonstrate this capability."
                ),
            }
            for p in (practices_gap or {}).get("missing_practices", [])
        ]

        computed_gap_finding = (
            f"AI maturity score of {prospect_score}/3, compared to a sector top-quartile "
            f"benchmark of {top_quartile}/3 "
            f"(sector average: {round(avg, 1)}/3 across "
            f"{benchmark.get('sample_size', 10)} companies analysed)."
        )

        return {
            "prospect_name": company_name,
            "sector": primary_sector,
            "sector_companies_analyzed": benchmark.get("sample_size", 10),
            "prospect_ai_maturity": prospect_score,
            "sector_avg_ai_maturity": round(avg, 2),
            "sector_top_quartile_maturity": top_quartile,
            "prospect_percentile": round(percentile, 1),
            "identified_gaps": gaps,
            "top_quartile_practices": benchmark.get("practices", []),
            "gap_severity": gap_severity,
            "confidence": round(confidence, 2),
            "computed_gap_finding": computed_gap_finding,
            "top_quartile_practices_not_observed": top_quartile_practices_not_observed,
            "suggested_pitch_shift": self._generate_pitch_shift(gaps, gap_severity),
            "actionable_insight": self._generate_insight(gaps, gap_severity, company_name),
        }

    def _determine_primary_sector(self, industries: List[str]) -> Optional[str]:
        if not industries:
            return None
        priority = ["software", "saas", "fintech", "healthcare", "e-commerce", "ai"]
        industries_lower = [i.lower() for i in industries]
        for sector in priority:
            if any(sector in i for i in industries_lower):
                return sector
        return industries[0].lower()

    def _identify_gaps(self, prospect_score: int, top_quartile: int, evidence: List[str], sector_practices: List[str]) -> List[Dict[str, Any]]:
        gaps = []
        if prospect_score < top_quartile:
            gap_size = top_quartile - prospect_score
            gaps.append({
                "category": "ai_maturity",
                "description": f"AI maturity score {gap_size} point(s) below sector leaders",
                "impact": "high" if gap_size >= 2 else "medium",
                "evidence": f"Top quartile companies show score of {top_quartile}",
            })

        evidence_text = " ".join(evidence).lower()
        missing = [p for p in sector_practices if not any(kw in evidence_text for kw in p.lower().split())]
        if missing:
            gaps.append({
                "category": "practices",
                "description": f"Missing {len(missing)} common practices seen in top-quartile peers",
                "missing_practices": missing[:3],
                "impact": "medium",
                "evidence": f"Sector leaders consistently demonstrate: {missing[0]}",
            })

        return gaps

    def _determine_severity(self, prospect_score: int, top_quartile: int) -> str:
        gap = top_quartile - prospect_score
        if gap >= 3:
            return "critical"
        if gap >= 2:
            return "significant"
        if gap >= 1:
            return "moderate"
        return "minimal"

    def _generate_insight(self, gaps: List[Dict], severity: str, company_name: str) -> str:
        """Research-finding framing — never condescending, never asserts failure."""
        if severity == "critical":
            return (
                f"Sector peers show consistent public signal of AI infrastructure investment "
                f"not yet visible for {company_name}. "
                f"Worth asking whether this is a deliberate sequencing decision or a resourcing constraint."
            )
        if severity == "significant":
            gap_desc = gaps[0].get("description", "a capability difference") if gaps else "a capability difference"
            return (
                f"For {company_name}, there is {gap_desc} relative to top-quartile peers in this sector. "
                f"Curious whether this is already on the roadmap or still being scoped."
            )
        if severity == "moderate":
            return (
                f"{company_name} is tracking near the sector average for AI maturity. "
                f"The question is whether the goal is to stay paced with the field or get ahead of it."
            )
        return (
            f"{company_name} shows strong AI maturity relative to sector peers. "
            f"The conversation is likely about scaling execution velocity, not capability gaps."
        )

    def _generate_pitch_shift(self, gaps: List[Dict], severity: str) -> str:
        if severity in ("critical", "significant"):
            practices_gap = next((g for g in gaps if g.get("category") == "practices"), None)
            if practices_gap and practices_gap.get("missing_practices"):
                top_practice = practices_gap["missing_practices"][0]
                return (
                    f"Shift from generic talent pitch to specialized capability question: "
                    f"'Have you scoped a dedicated {top_practice.lower()} function yet?'"
                )
            return "Lead with the sector benchmark data as a research finding, then ask about roadmap sequencing."
        if severity == "moderate":
            return (
                "Frame as an acceleration question: "
                "'The gap between sector average and top quartile is often one focused function — "
                "is that something you're actively scoping?'"
            )
        return "Lead with execution velocity, not capability gaps — prospect is already AI-mature."
