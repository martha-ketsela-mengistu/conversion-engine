"""Tests for EnrichmentPipeline."""

import json
import csv
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from agent.enrichment.pipeline import EnrichmentPipeline, HiringSignalBrief
from agent.enrichment.ai_maturity import AIMaturityScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def crunchbase_csv(tmp_path) -> Path:
    path = tmp_path / "crunchbase.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "description", "homepage_url", "founded_on", "country_code",
            "city", "region", "employee_count", "category_groups_list", "category_list",
            "total_funding_usd", "num_funding_rounds", "last_funding_type",
            "last_funding_at", "investor_names", "valuation_usd",
        ])
        writer.writeheader()
        writer.writerow({
            "name": "TestCo",
            "description": "Test SaaS company",
            "homepage_url": "https://testco.com",
            "founded_on": "2021-01-01",
            "country_code": "KE",
            "city": "Nairobi",
            "region": "Nairobi Area",
            "employee_count": "80",
            "category_groups_list": '["Software"]',
            "category_list": '["SaaS"]',
            "total_funding_usd": "15000000",
            "num_funding_rounds": "2",
            "last_funding_type": "series_a",
            "last_funding_at": "2025-12-01",
            "investor_names": '["Y Combinator"]',
            "valuation_usd": "70000000",
        })
    return path


@pytest.fixture
def layoffs_csv(tmp_path) -> Path:
    path = tmp_path / "layoffs.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "date", "headcount_affected", "percentage", "source"])
        writer.writeheader()
        # No layoffs for TestCo — clean slate
    return path


@pytest.fixture
def job_velocity_fixture() -> dict:
    return {
        "open_engineering_roles": 4,
        "total_open_roles": 10,
        "recent_posts": [
            {"title": "Backend Engineer", "url": "https://testco.com/jobs/1",
             "posted_date": "2026-03-01", "company": "TestCo", "source": "frozen"},
        ],
        "velocity_60d": 0.47,
        "hiring_signal_strength": "moderate",
        "confidence": 0.7,
        "all_engineering_roles": ["Backend Engineer", "Data Engineer"],
        "source": "frozen_dataset",
        "scraped_at": datetime.now().isoformat(),
    }


@pytest.fixture
def pipeline(tmp_path, crunchbase_csv, layoffs_csv, job_velocity_fixture) -> EnrichmentPipeline:
    """Pipeline with mocked job scraper and temp data paths."""
    from agent.enrichment.crunchbase import CrunchbaseEnricher
    from agent.enrichment.layoffs import LayoffsEnricher
    from agent.enrichment.jobs import JobScraper
    from agent.enrichment.ai_maturity import AIMaturityScorer
    from agent.enrichment.competitor_gap import CompetitorGapAnalyzer

    p = EnrichmentPipeline.__new__(EnrichmentPipeline)
    p.crunchbase = CrunchbaseEnricher(data_path=crunchbase_csv)
    p.layoffs = LayoffsEnricher(data_path=layoffs_csv)
    p.job_scraper = MagicMock()
    p.job_scraper.get_job_velocity.return_value = job_velocity_fixture
    p.ai_scorer = AIMaturityScorer()

    # CompetitorGapAnalyzer with pre-loaded benchmarks (no CSV needed)
    gap = CompetitorGapAnalyzer.__new__(CompetitorGapAnalyzer)
    gap.crunchbase = p.crunchbase
    gap.ai_scorer = p.ai_scorer
    gap.sector_benchmarks = {
        "saas": {
            "avg_maturity": 1.5,
            "top_quartile": 3,
            "sample_size": 20,
            "practices": ["AI feature development", "Predictive analytics"],
        }
    }
    p.gap_analyzer = gap

    # Redirect output to tmp_path
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    p._output_dir = output_dir

    # Stub out the LLM summarise call so tests run offline
    p._summarise_signals = MagicMock(return_value="TestCo raised a Series A and is actively hiring engineers.")
    return p


# ---------------------------------------------------------------------------
# Segment classification
# ---------------------------------------------------------------------------

class TestClassifySegment:
    def test_segment_1_funded_small_company(self, pipeline):
        firmographics = {"employee_count": 80}
        funding = [{"type": "series_a", "amount_usd": 12_000_000}]
        segment, confidence = pipeline._classify_segment(firmographics, funding, None, [])
        assert segment == "segment_1"
        assert confidence == pytest.approx(0.85)

    def test_segment_1_requires_15_to_200_employees(self, pipeline):
        firmographics = {"employee_count": 5}  # too small
        funding = [{"type": "series_a"}]
        segment, _ = pipeline._classify_segment(firmographics, funding, None, [])
        assert segment != "segment_1"

    def test_segment_2_layoffs_mid_market(self, pipeline):
        firmographics = {"employee_count": 500}
        layoffs = {"has_recent_layoffs": True}
        segment, confidence = pipeline._classify_segment(firmographics, [], layoffs, [])
        assert segment == "segment_2"
        assert confidence == pytest.approx(0.80)

    def test_segment_2_requires_200_to_2000_employees(self, pipeline):
        firmographics = {"employee_count": 100}  # below 200
        layoffs = {"has_recent_layoffs": True}
        segment, _ = pipeline._classify_segment(firmographics, [], layoffs, [])
        assert segment != "segment_2"

    def test_segment_3_leadership_change(self, pipeline):
        firmographics = {"employee_count": 300}
        changes = [{"detected": True, "confidence": "medium"}]
        segment, confidence = pipeline._classify_segment(firmographics, [], None, changes)
        assert segment == "segment_3"
        assert confidence == pytest.approx(0.70)

    def test_no_segment_when_no_signals(self, pipeline):
        firmographics = {"employee_count": 50}
        segment, confidence = pipeline._classify_segment(firmographics, [], None, [])
        assert segment is None
        assert confidence == 0.0

    def test_segment_1_takes_priority_over_leadership(self, pipeline):
        firmographics = {"employee_count": 100}
        funding = [{"type": "series_a"}]
        changes = [{"detected": True}]
        segment, _ = pipeline._classify_segment(firmographics, funding, None, changes)
        assert segment == "segment_1"


class TestExtractTechStack:
    def test_combines_categories_and_industries(self, pipeline):
        firmographics = {"categories": ["Software", "SaaS"], "industries": ["B2B", "Cloud"]}
        stack = pipeline._extract_tech_stack(firmographics)
        assert "Software" in stack
        assert "B2B" in stack

    def test_missing_keys_return_empty(self, pipeline):
        stack = pipeline._extract_tech_stack({})
        assert stack == []


# ---------------------------------------------------------------------------
# Full pipeline run
# ---------------------------------------------------------------------------

class TestPipelineRun:
    def _run(self, pipeline, tmp_path):
        # Patch _save_brief to write to tmp_path
        brief_path = tmp_path / "outputs" / "hiring_signal_brief.json"

        original_save = pipeline._save_brief

        def save_to_tmp(brief):
            brief_path.parent.mkdir(exist_ok=True)
            import json, dataclasses
            with open(brief_path, "w") as f:
                json.dump(dataclasses.asdict(brief), f, indent=2, default=str)

        pipeline._save_brief = save_to_tmp
        return pipeline.run("TestCo", "testco.com"), brief_path

    def test_run_returns_hiring_signal_brief(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        assert isinstance(brief, HiringSignalBrief)

    def test_brief_has_company_name(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        assert brief.company_name == "TestCo"
        assert brief.domain == "testco.com"

    def test_brief_has_generated_at(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        assert brief.generated_at is not None
        datetime.fromisoformat(brief.generated_at)  # should not raise

    def test_brief_ai_maturity_structure(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        assert "score" in brief.ai_maturity
        assert "confidence" in brief.ai_maturity
        assert "evidence" in brief.ai_maturity
        assert isinstance(brief.ai_maturity["score"], int)

    def test_brief_job_velocity_from_mock(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        assert brief.job_post_velocity["open_engineering_roles"] == 4
        assert brief.job_post_velocity["source"] == "frozen_dataset"

    def test_output_file_written(self, pipeline, tmp_path):
        _, brief_path = self._run(pipeline, tmp_path)
        assert brief_path.exists()
        data = json.loads(brief_path.read_text())
        assert data["company_name"] == "TestCo"

    def test_segment_1_for_funded_small_company(self, pipeline, tmp_path):
        # TestCo: 80 employees + series_a funding in 2025-12-01 (within 180d) → segment_1
        brief, _ = self._run(pipeline, tmp_path)
        assert brief.icp_segment == "segment_1"
        assert brief.segment_confidence == pytest.approx(0.85)

    def test_competitor_gap_run_for_segment_1(self, pipeline, tmp_path):
        brief, _ = self._run(pipeline, tmp_path)
        # segment_1 should trigger competitor gap analysis
        assert brief.competitor_gap is not None
