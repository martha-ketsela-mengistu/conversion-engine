"""Tests for LayoffsEnricher."""

import csv
import pytest
from pathlib import Path

from enrichment.layoffs import LayoffsEnricher


@pytest.fixture
def sample_csv(tmp_path) -> Path:
    csv_path = tmp_path / "layoffs.csv"
    rows = [
        # ~102 days before 2026-04-22 → within 120d window
        {"company": "MegaSoft", "date": "2026-01-10", "headcount_affected": "500", "percentage": "20%", "source": "https://layoffs.fyi/megasoft"},
        # ~128 days before 2026-04-22 → outside 120d window
        {"company": "TechCorp", "date": "2025-12-15", "headcount_affected": "120", "percentage": "15%", "source": "https://layoffs.fyi/techcorp"},
        # ~172 days before 2026-04-22 → outside window
        {"company": "StartupXYZ", "date": "2025-11-01", "headcount_affected": "25", "percentage": "10%", "source": "https://layoffs.fyi/startupxyz"},
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def enricher(sample_csv) -> LayoffsEnricher:
    return LayoffsEnricher(data_path=sample_csv)


class TestGetLayoffs:
    def test_recent_layoff_detected(self, enricher):
        result = enricher.get_layoffs("MegaSoft", days=120)
        assert result is not None
        assert result["has_recent_layoffs"] is True
        assert result["within_120d"] is True
        assert len(result["events"]) == 1
        assert result["latest_event"]["headcount_affected"] == 500

    def test_old_layoff_not_recent(self, enricher):
        result = enricher.get_layoffs("TechCorp", days=120)
        assert result is not None
        assert result["has_recent_layoffs"] is False

    def test_unknown_company_returns_none(self, enricher):
        assert enricher.get_layoffs("NoSuchCompany") is None

    def test_case_insensitive_match(self, enricher):
        result = enricher.get_layoffs("megasoft", days=120)
        assert result["has_recent_layoffs"] is True

    def test_partial_name_match(self, enricher):
        result = enricher.get_layoffs("Mega", days=120)
        assert result["has_recent_layoffs"] is True

    def test_missing_file_returns_none(self, tmp_path):
        enricher = LayoffsEnricher(data_path=tmp_path / "missing.csv")
        assert enricher.get_layoffs("Anyone") is None

    def test_missing_file_df_is_empty(self, tmp_path):
        enricher = LayoffsEnricher(data_path=tmp_path / "missing.csv")
        assert enricher.df.empty

    def test_wider_window_catches_old_event(self, enricher):
        result = enricher.get_layoffs("TechCorp", days=200)
        assert result["has_recent_layoffs"] is True

    def test_events_list_structure(self, enricher):
        result = enricher.get_layoffs("MegaSoft", days=120)
        event = result["events"][0]
        assert "date" in event
        assert "headcount_affected" in event
        assert "percentage" in event
        assert "source" in event
