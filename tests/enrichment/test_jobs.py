"""Tests for JobScraper."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from enrichment.jobs import JobScraper


@pytest.fixture
def scraper(tmp_path) -> JobScraper:
    return JobScraper(cache_dir=tmp_path / "job_cache")


@pytest.fixture
def frozen_dataset(tmp_path) -> Path:
    path = tmp_path / "frozen_jobs_april2026.json"
    path.write_text(json.dumps({
        "acme corp": {
            "open_engineering_roles": 5,
            "total_open_roles": 12,
            "recent_posts": [],
            "velocity_60d": 0.58,
            "hiring_signal_strength": "moderate",
            "confidence": 0.7,
            "all_engineering_roles": ["Backend Engineer", "ML Engineer"],
        }
    }))
    return path


class TestFrozenDataset:
    def test_frozen_dataset_used_when_present(self, tmp_path, frozen_dataset):
        scraper = JobScraper(cache_dir=tmp_path / "job_cache")
        # Patch the frozen path to our tmp file
        scraper.frozen_dataset = json.loads(frozen_dataset.read_text())
        result = scraper.get_job_velocity("Acme Corp", "acme.com")
        assert result["source"] == "frozen_dataset"
        assert result["open_engineering_roles"] == 5

    def test_frozen_dataset_lookup_is_case_insensitive(self, tmp_path, frozen_dataset):
        scraper = JobScraper(cache_dir=tmp_path / "job_cache")
        scraper.frozen_dataset = json.loads(frozen_dataset.read_text())
        result = scraper.get_job_velocity("ACME CORP", "acme.com")
        assert result["source"] == "frozen_dataset"

    def test_frozen_dataset_miss_falls_through(self, tmp_path, frozen_dataset):
        scraper = JobScraper(cache_dir=tmp_path / "job_cache")
        scraper.frozen_dataset = json.loads(frozen_dataset.read_text())
        # "Unknown Co" not in frozen dataset — should attempt cache then live
        with patch.object(scraper, "_scrape_company") as mock_scrape:
            mock_scrape.return_value = {
                "company_name": "Unknown Co",
                "domain": "unknown.com",
                "scraped_at": datetime.now().isoformat(),
                "open_engineering_roles": 0,
                "total_open_roles": 0,
                "recent_posts": [],
                "velocity_60d": 0.0,
                "hiring_signal_strength": "none",
                "confidence": 0.3,
                "all_engineering_roles": [],
            }
            with patch("enrichment.jobs.asyncio.run", return_value=mock_scrape.return_value):
                result = scraper.get_job_velocity("Unknown Co", "unknown.com")
        assert result["source"] == "live_scrape"


class TestCache:
    def test_fresh_cache_is_used(self, scraper, tmp_path):
        cache_data = {
            "open_engineering_roles": 3,
            "total_open_roles": 8,
            "recent_posts": [],
            "velocity_60d": 0.35,
            "hiring_signal_strength": "moderate",
            "confidence": 0.7,
            "scraped_at": datetime.now().isoformat(),
            "all_engineering_roles": [],
        }
        cache_path = scraper.cache_dir / "cached_co.json"
        cache_path.write_text(json.dumps(cache_data))

        result = scraper.get_job_velocity("Cached Co", "cached.com")
        assert result["source"] == "cache"
        assert result["open_engineering_roles"] == 3

    def test_stale_cache_triggers_live_scrape(self, scraper, tmp_path):
        stale_data = {
            "open_engineering_roles": 1,
            "scraped_at": (datetime.now() - timedelta(hours=25)).isoformat(),
        }
        cache_path = scraper.cache_dir / "stale_co.json"
        cache_path.write_text(json.dumps(stale_data))

        mock_result = {
            "company_name": "Stale Co",
            "domain": "stale.com",
            "scraped_at": datetime.now().isoformat(),
            "open_engineering_roles": 2,
            "total_open_roles": 5,
            "recent_posts": [],
            "velocity_60d": 0.2,
            "hiring_signal_strength": "weak",
            "confidence": 0.5,
            "all_engineering_roles": [],
        }
        with patch("enrichment.jobs.asyncio.run", return_value=mock_result):
            result = scraper.get_job_velocity("Stale Co", "stale.com")
        assert result["source"] == "live_scrape"


class TestIsEngineeringRole:
    @pytest.mark.parametrize("title", [
        "Software Engineer",
        "Senior Backend Developer",
        "ML Engineer",
        "Machine Learning Researcher",
        "Data Engineer",
        "Platform Engineer",
        "AI Engineer",
        "Python Developer",
        "DevOps Engineer",
        "Data Scientist",
        "Full Stack Developer",
    ])
    def test_engineering_role_detected(self, scraper, title):
        assert scraper._is_engineering_role({"title": title}) is True

    @pytest.mark.parametrize("title", [
        "Sales Manager",
        "Marketing Lead",
        "Customer Success",
        "Finance Analyst",
        "HR Business Partner",
        "Office Manager",
    ])
    def test_non_engineering_role_rejected(self, scraper, title):
        assert scraper._is_engineering_role({"title": title}) is False

    def test_empty_title_returns_false(self, scraper):
        assert scraper._is_engineering_role({"title": ""}) is False

    def test_missing_title_returns_false(self, scraper):
        assert scraper._is_engineering_role({}) is False


class TestExtractPostedDate:
    def _make_el(self, text: str):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(f"<a>{text}</a>", "lxml")
        return soup.find("a")

    def test_today_returns_today(self, scraper):
        el = self._make_el("Posted today")
        result = scraper._extract_posted_date(el)
        assert result.date() == datetime.now().date()

    def test_yesterday_returns_yesterday(self, scraper):
        el = self._make_el("Posted yesterday")
        result = scraper._extract_posted_date(el)
        assert result.date() == (datetime.now() - timedelta(days=1)).date()

    def test_week_ago_returns_7_days(self, scraper):
        el = self._make_el("1 week ago")
        result = scraper._extract_posted_date(el)
        assert result.date() == (datetime.now() - timedelta(days=7)).date()

    def test_month_ago_returns_30_days(self, scraper):
        el = self._make_el("30 days ago")
        result = scraper._extract_posted_date(el)
        assert result.date() == (datetime.now() - timedelta(days=30)).date()

    def test_iso_date_parsed(self, scraper):
        el = self._make_el("2026-03-15 posted")
        result = scraper._extract_posted_date(el)
        assert result == datetime(2026, 3, 15)

    def test_unknown_text_defaults_to_15_days_ago(self, scraper):
        el = self._make_el("Some obscure posting text")
        result = scraper._extract_posted_date(el)
        expected = datetime.now() - timedelta(days=15)
        assert abs((result - expected).total_seconds()) < 5


class TestLiveScrapeReturnStructure:
    def test_live_scrape_returns_expected_keys(self, scraper):
        mock_result = {
            "company_name": "Test Co",
            "domain": "test.com",
            "scraped_at": datetime.now().isoformat(),
            "open_engineering_roles": 0,
            "total_open_roles": 0,
            "recent_posts": [],
            "velocity_60d": 0.0,
            "hiring_signal_strength": "none",
            "confidence": 0.3,
            "all_engineering_roles": [],
        }
        with patch("enrichment.jobs.asyncio.run", return_value=mock_result):
            result = scraper.get_job_velocity("Test Co", "test.com")

        required_keys = [
            "open_engineering_roles", "total_open_roles", "recent_posts",
            "velocity_60d", "hiring_signal_strength", "confidence", "source",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_cache_file_written_after_live_scrape(self, scraper, tmp_path):
        mock_result = {
            "company_name": "NewCo",
            "domain": "newco.com",
            "scraped_at": datetime.now().isoformat(),
            "open_engineering_roles": 2,
            "total_open_roles": 4,
            "recent_posts": [],
            "velocity_60d": 0.2,
            "hiring_signal_strength": "weak",
            "confidence": 0.5,
            "all_engineering_roles": ["Backend Engineer"],
        }
        with patch("enrichment.jobs.asyncio.run", return_value=mock_result):
            scraper.get_job_velocity("NewCo", "newco.com")

        cache_path = scraper.cache_dir / "newco.json"
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text())
        assert cached["open_engineering_roles"] == 2
