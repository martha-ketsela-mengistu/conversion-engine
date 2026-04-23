"""Competitor gap analysis for research-grounded outreach."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from observability.tracing import observe
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
        for industry in df["category_list"].dropna().unique()[:20]:
            industry_companies = df[df["category_list"].str.contains(industry, na=False)]
            if len(industry_companies) < 5:
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
        if severity == "critical":
            return f"{company_name} is significantly behind sector leaders in AI readiness—this represents both a risk and an opportunity to leapfrog with dedicated engineering capacity."
        if severity == "significant":
            if gaps:
                return f"{company_name} shows a {gaps[0].get('description', 'gap')} compared to peers. Addressing this could accelerate time-to-market for AI initiatives."
            return f"{company_name} has room to accelerate AI capabilities relative to sector benchmarks."
        if severity == "moderate":
            return f"{company_name} is tracking near sector average for AI maturity. Additional engineering capacity could push you into the top quartile within 6 months."
        return f"{company_name} demonstrates strong AI maturity relative to peers. The opportunity is in scaling execution velocity."
