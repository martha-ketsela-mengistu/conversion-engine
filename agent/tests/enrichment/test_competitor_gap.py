"""Tests for CompetitorGapAnalyzer."""

import pytest
from enrichment.competitor_gap import CompetitorGapAnalyzer
from enrichment.ai_maturity import AIMaturityScore


@pytest.fixture
def analyzer(tmp_path, monkeypatch) -> CompetitorGapAnalyzer:
    # Prevent loading/writing sector_benchmarks.json from the real data dir
    monkeypatch.chdir(tmp_path)
    analyzer = CompetitorGapAnalyzer.__new__(CompetitorGapAnalyzer)
    analyzer.crunchbase = None
    analyzer.ai_scorer = None
    analyzer.sector_benchmarks = {
        "saas": {
            "avg_maturity": 1.5,
            "top_quartile": 3,
            "sample_size": 20,
            "practices": [
                "AI feature development",
                "Predictive analytics",
                "Automated workflows",
                "Natural language processing",
            ],
        },
        "fintech": {
            "avg_maturity": 1.0,
            "top_quartile": 2,
            "sample_size": 15,
            "practices": ["AI-powered risk assessment", "Automated underwriting"],
        },
    }
    return analyzer


def _score(score: int, confidence: float = 0.6, evidence=None) -> AIMaturityScore:
    return AIMaturityScore(score=score, confidence=confidence, evidence=evidence or [])


class TestAnalyze:
    def test_returns_none_for_empty_industries(self, analyzer):
        result = analyzer.analyze("Acme", [], _score(1))
        assert result is None

    def test_returns_dict_for_known_sector(self, analyzer):
        result = analyzer.analyze("Acme", ["SaaS"], _score(1))
        assert result is not None
        assert result["sector"] == "saas"

    def test_prospect_name_in_result(self, analyzer):
        result = analyzer.analyze("BetaCo", ["SaaS"], _score(2))
        assert result["prospect_name"] == "BetaCo"

    def test_result_keys_present(self, analyzer):
        result = analyzer.analyze("Co", ["SaaS"], _score(1))
        required = [
            "prospect_name", "sector", "sector_companies_analyzed",
            "prospect_ai_maturity", "sector_avg_ai_maturity",
            "sector_top_quartile_maturity", "prospect_percentile",
            "identified_gaps", "top_quartile_practices", "gap_severity",
            "confidence", "actionable_insight",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_score_at_top_quartile_has_high_percentile(self, analyzer):
        result = analyzer.analyze("Co", ["SaaS"], _score(3))
        assert result["prospect_percentile"] >= 75

    def test_score_below_average_has_low_percentile(self, analyzer):
        result = analyzer.analyze("Co", ["SaaS"], _score(0))
        assert result["prospect_percentile"] < 50

    def test_percentile_clamped_between_1_and_99(self, analyzer):
        for s in [0, 1, 2, 3]:
            result = analyzer.analyze("Co", ["SaaS"], _score(s))
            assert 1 <= result["prospect_percentile"] <= 99


class TestDetermineSeverity:
    def test_critical_gap(self, analyzer):
        assert analyzer._determine_severity(0, 3) == "critical"

    def test_significant_gap(self, analyzer):
        assert analyzer._determine_severity(1, 3) == "significant"

    def test_moderate_gap(self, analyzer):
        assert analyzer._determine_severity(2, 3) == "moderate"

    def test_minimal_gap(self, analyzer):
        assert analyzer._determine_severity(3, 3) == "minimal"

    def test_above_quartile_is_minimal(self, analyzer):
        assert analyzer._determine_severity(3, 2) == "minimal"


class TestGenerateInsight:
    def test_critical_severity_insight(self, analyzer):
        insight = analyzer._generate_insight([], "critical", "Acme")
        assert "Acme" in insight
        assert "behind" in insight.lower() or "significantly" in insight.lower()

    def test_significant_severity_with_gaps(self, analyzer):
        gaps = [{"description": "AI maturity 2 points below sector leaders"}]
        insight = analyzer._generate_insight(gaps, "significant", "BetaCo")
        assert "BetaCo" in insight

    def test_moderate_severity_insight(self, analyzer):
        insight = analyzer._generate_insight([], "moderate", "GammaCo")
        assert "GammaCo" in insight
        assert "average" in insight.lower() or "near" in insight.lower()

    def test_minimal_severity_insight(self, analyzer):
        insight = analyzer._generate_insight([], "minimal", "DeltaCo")
        assert "DeltaCo" in insight
        assert "strong" in insight.lower()


class TestIdentifyGaps:
    def test_gap_detected_below_top_quartile(self, analyzer):
        practices = ["AI feature development", "Predictive analytics"]
        gaps = analyzer._identify_gaps(1, 3, [], practices)
        assert any(g["category"] == "ai_maturity" for g in gaps)

    def test_no_maturity_gap_at_top_quartile(self, analyzer):
        practices = []
        gaps = analyzer._identify_gaps(3, 3, [], practices)
        maturity_gaps = [g for g in gaps if g["category"] == "ai_maturity"]
        assert maturity_gaps == []

    def test_missing_practices_detected(self, analyzer):
        practices = ["MLOps infrastructure", "LLM integration"]
        gaps = analyzer._identify_gaps(1, 3, ["some other evidence"], practices)
        practice_gaps = [g for g in gaps if g["category"] == "practices"]
        assert practice_gaps  # at least one practice gap found

    def test_gap_severity_high_for_large_gap(self, analyzer):
        practices = []
        gaps = analyzer._identify_gaps(0, 3, [], practices)
        maturity_gap = next(g for g in gaps if g["category"] == "ai_maturity")
        assert maturity_gap["impact"] == "high"


class TestDeterminePrimarySector:
    def test_saas_detected(self, analyzer):
        # No "software" in the list so "saas" wins from the priority ordering
        assert analyzer._determine_primary_sector(["SaaS", "Analytics"]) == "saas"

    def test_fintech_detected(self, analyzer):
        assert analyzer._determine_primary_sector(["Fintech", "Banking"]) == "fintech"

    def test_software_takes_priority_over_other(self, analyzer):
        assert analyzer._determine_primary_sector(["software", "saas"]) == "software"

    def test_empty_list_returns_none(self, analyzer):
        assert analyzer._determine_primary_sector([]) is None

    def test_unknown_sector_returns_first_lowercase(self, analyzer):
        assert analyzer._determine_primary_sector(["Logistics"]) == "logistics"
