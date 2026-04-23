"""Tests for CrunchbaseEnricher."""

import csv
import pytest
from pathlib import Path

from enrichment.crunchbase import CrunchbaseEnricher


@pytest.fixture
def sample_csv(tmp_path) -> Path:
    """Minimal CSV fixture with controlled dates for deterministic tests."""
    csv_path = tmp_path / "crunchbase.csv"
    rows = [
        {
            "name": "Acme Corp",
            "description": "A fast-growing SaaS company",
            "homepage_url": "https://acme.com",
            "founded_on": "2020-03-01",
            "country_code": "KE",
            "city": "Nairobi",
            "region": "Nairobi Area",
            "employee_count": "75",
            "category_groups_list": '["Software","SaaS"]',
            "category_list": '["B2B Software","Cloud Computing"]',
            "total_funding_usd": "12000000",
            "num_funding_rounds": "2",
            "last_funding_type": "series_a",
            "last_funding_at": "2025-12-01",  # ~142 days before 2026-04-22 → within 180d
            "investor_names": '["Sequoia Capital"]',
            "valuation_usd": "60000000",
        },
        {
            "name": "Old Co",
            "description": "Older company",
            "homepage_url": "https://oldco.com",
            "founded_on": "2015-01-01",
            "country_code": "NG",
            "city": "Lagos",
            "region": "Lagos State",
            "employee_count": "500",
            "category_groups_list": '["Fintech"]',
            "category_list": '["Payments"]',
            "total_funding_usd": "5000000",
            "num_funding_rounds": "1",
            "last_funding_type": "seed",
            "last_funding_at": "2023-01-01",  # > 180 days ago → outside window
            "investor_names": "[]",
            "valuation_usd": "",
        },
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def enricher(sample_csv) -> CrunchbaseEnricher:
    return CrunchbaseEnricher(data_path=sample_csv)


class TestGetCompany:
    def test_exact_match(self, enricher):
        result = enricher.get_company("Acme Corp")
        assert result is not None
        assert result["name"] == "Acme Corp"

    def test_case_insensitive(self, enricher):
        result = enricher.get_company("acme corp")
        assert result is not None
        assert result["name"] == "Acme Corp"

    def test_partial_match(self, enricher):
        result = enricher.get_company("acme")
        assert result is not None
        assert result["name"] == "Acme Corp"

    def test_not_found_returns_none(self, enricher):
        assert enricher.get_company("Nonexistent Company XYZ") is None

    def test_employee_count_parsed(self, enricher):
        result = enricher.get_company("Acme Corp")
        assert result["employee_count"] == 75

    def test_categories_parsed_as_list(self, enricher):
        result = enricher.get_company("Acme Corp")
        assert isinstance(result["categories"], list)
        assert "Software" in result["categories"]

    def test_funding_parsed_as_float(self, enricher):
        result = enricher.get_company("Acme Corp")
        assert result["total_funding_usd"] == 12_000_000.0

    def test_missing_valuation_returns_none(self, enricher):
        result = enricher.get_company("Old Co")
        assert result["valuation_usd"] is None


class TestGetFundingEvents:
    def test_recent_funding_returned(self, enricher):
        events = enricher.get_funding_events("Acme Corp", days=180)
        assert len(events) == 1
        assert events[0]["type"] == "series_a"
        assert events[0]["within_180d"] is True

    def test_old_funding_excluded(self, enricher):
        events = enricher.get_funding_events("Old Co", days=180)
        assert events == []

    def test_unknown_company_returns_empty(self, enricher):
        events = enricher.get_funding_events("NoSuchCo", days=180)
        assert events == []

    def test_shorter_window_excludes_event(self, enricher):
        # Acme Corp funded 2025-12-01 (~142 days before 2026-04-22) — outside 90d window
        events = enricher.get_funding_events("Acme Corp", days=90)
        assert events == []


class TestDetectLeadershipChange:
    def test_recent_funding_triggers_leadership_signal(self, enricher):
        changes = enricher.detect_leadership_change("Acme Corp", days=180)
        assert len(changes) == 1
        assert changes[0]["detected"] is True
        assert "confidence" in changes[0]

    def test_old_funding_yields_no_signal(self, enricher):
        changes = enricher.detect_leadership_change("Old Co", days=90)
        assert changes == []

    def test_unknown_company_returns_empty(self, enricher):
        assert enricher.detect_leadership_change("Ghost Corp") == []


class TestParseHelpers:
    def test_parse_employee_count_range(self, sample_csv, tmp_path):
        csv_path = tmp_path / "range.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "description", "homepage_url",
                "founded_on", "country_code", "city", "region", "employee_count",
                "category_groups_list", "category_list", "total_funding_usd",
                "num_funding_rounds", "last_funding_type", "last_funding_at",
                "investor_names", "valuation_usd"])
            writer.writeheader()
            writer.writerow({
                "name": "Range Co", "description": "", "homepage_url": "",
                "founded_on": "", "country_code": "", "city": "", "region": "",
                "employee_count": "51-100",
                "category_groups_list": "[]", "category_list": "[]",
                "total_funding_usd": "", "num_funding_rounds": "", "last_funding_type": "",
                "last_funding_at": "", "investor_names": "[]", "valuation_usd": "",
            })
        e = CrunchbaseEnricher(data_path=csv_path)
        result = e.get_company("Range Co")
        assert result["employee_count"] == 75  # (51+100)//2

    def test_parse_list_csv_format(self, enricher):
        result = enricher._parse_list("Software, SaaS, Fintech")
        assert result == ["Software", "SaaS", "Fintech"]

    def test_parse_list_json_format(self, enricher):
        result = enricher._parse_list('["A", "B"]')
        assert result == ["A", "B"]

    def test_parse_list_empty(self, enricher):
        assert enricher._parse_list("") == []


class TestFileHandling:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CrunchbaseEnricher(data_path=tmp_path / "missing.csv")
