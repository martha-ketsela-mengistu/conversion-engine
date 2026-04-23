"""Job post scraping for hiring velocity signal.

Challenge constraints:
- Use only public pages, no login, no captcha bypass
- Respect robots.txt
- Max 200 companies during challenge week
- Frozen dataset preferred over live scraping when available
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

from observability.tracing import observe


ENGINEERING_KEYWORDS = [
    "software engineer", "developer", "data engineer", "ml engineer",
    "machine learning", "backend", "frontend", "full stack", "devops",
    "sre", "infrastructure", "platform engineer", "data scientist",
    "ai engineer", "python", "golang", "java", "rust", "typescript",
]


class JobScraper:
    """Scrape public job listings from BuiltIn, Wellfound, and company career pages."""

    def __init__(self, cache_dir: Path = None):
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent / "data" / "job_cache"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.frozen_dataset = self._load_frozen_dataset()

    def _load_frozen_dataset(self) -> Optional[Dict]:
        frozen_path = Path(__file__).parent.parent / "data" / "frozen_jobs_april2026.json"
        if frozen_path.exists():
            with open(frozen_path) as f:
                return json.load(f)
        return None

    @observe(name="jobs.get_job_velocity")
    def get_job_velocity(self, company_name: str, domain: str) -> Dict[str, Any]:
        """Get job posting velocity for a company."""
        if self.frozen_dataset:
            company_data = self.frozen_dataset.get(company_name.lower())
            if company_data:
                return {**company_data, "source": "frozen_dataset", "scraped_at": datetime.now().isoformat()}

        cache_key = company_name.lower().replace(" ", "_")
        cache_path = self.cache_dir / f"{cache_key}.json"

        if cache_path.exists():
            with open(cache_path) as f:
                cached = json.load(f)
            cached_at = datetime.fromisoformat(cached.get("scraped_at", "2000-01-01"))
            if datetime.now() - cached_at < timedelta(hours=24):
                return {**cached, "source": "cache"}

        result = asyncio.run(self._scrape_company(company_name, domain))

        with open(cache_path, "w") as f:
            json.dump(result, f, indent=2, default=str)

        return {**result, "source": "live_scrape"}

    async def _scrape_company(self, company_name: str, domain: str) -> Dict[str, Any]:
        """Scrape company career pages using Playwright."""
        jobs = []
        slug = domain.split(".")[0]

        career_urls = [
            f"https://{domain}/careers",
            f"https://{domain}/jobs",
            f"https://jobs.lever.co/{slug}",
            f"https://boards.greenhouse.io/{slug}",
            f"https://www.builtin.com/company/{slug}/jobs",
        ]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            for url in career_urls:
                try:
                    await page.goto(url, timeout=10000)
                    await page.wait_for_load_state("networkidle", timeout=5000)
                    page_jobs = await self._extract_jobs_from_page(page, company_name)
                    jobs.extend(page_jobs)
                    if len(jobs) >= 10:
                        break
                except Exception:
                    continue

            await browser.close()

        engineering_jobs = [j for j in jobs if self._is_engineering_role(j)]
        cutoff = datetime.now() - timedelta(days=60)
        recent_engineering = [
            j for j in engineering_jobs
            if j.get("posted_date") and datetime.fromisoformat(j["posted_date"]) > cutoff
        ]

        velocity_60d = len(recent_engineering) / 8.57  # roles per week

        if len(engineering_jobs) >= 10:
            strength, confidence = "strong", 0.9
        elif len(engineering_jobs) >= 5:
            strength, confidence = "moderate", 0.7
        elif len(engineering_jobs) >= 1:
            strength, confidence = "weak", 0.5
        else:
            strength, confidence = "none", 0.3

        return {
            "company_name": company_name,
            "domain": domain,
            "scraped_at": datetime.now().isoformat(),
            "open_engineering_roles": len(engineering_jobs),
            "total_open_roles": len(jobs),
            "recent_posts": recent_engineering[:10],
            "velocity_60d": round(velocity_60d, 2),
            "hiring_signal_strength": strength,
            "confidence": confidence,
            "all_engineering_roles": [j.get("title") for j in engineering_jobs],
        }

    async def _extract_jobs_from_page(self, page: Page, company_name: str) -> List[Dict]:
        """Extract job listings from a career page."""
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        selectors = [
            "a[href*='/job/']",
            "a[href*='/jobs/']",
            "a[href*='careers']",
            ".job-listing",
            ".job-posting",
            "[data-qa='job']",
            "li a[href*='jobs.lever.co']",
        ]

        jobs = []
        seen_urls: set = set()
        base = page.url.split("/")[2] if "/" in page.url else ""

        for selector in selectors:
            for el in soup.select(selector)[:20]:
                title = el.get_text(strip=True)
                href = el.get("href", "")

                if not title or not (5 <= len(title) <= 100):
                    continue
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                posted_date = self._extract_posted_date(el)
                jobs.append({
                    "title": title,
                    "url": href if href.startswith("http") else f"https://{base}{href}",
                    "posted_date": posted_date.isoformat() if posted_date else None,
                    "company": company_name,
                    "source": page.url,
                })

        return jobs

    def _extract_posted_date(self, element) -> Optional[datetime]:
        text = element.get_text(strip=True).lower()
        parent_text = element.parent.get_text(strip=True).lower() if element.parent else ""
        combined = text + " " + parent_text

        if "today" in combined:
            return datetime.now()
        if "yesterday" in combined:
            return datetime.now() - timedelta(days=1)
        if "week ago" in combined or "7 days" in combined:
            return datetime.now() - timedelta(days=7)
        if "month ago" in combined or "30 days" in combined:
            return datetime.now() - timedelta(days=30)

        for pattern in [r"(\d{4})-(\d{1,2})-(\d{1,2})", r"(\d{1,2})/(\d{1,2})/(\d{4})"]:
            match = re.search(pattern, combined)
            if match:
                try:
                    g = match.groups()
                    if len(g[0]) == 4:
                        return datetime(int(g[0]), int(g[1]), int(g[2]))
                    return datetime(int(g[2]), int(g[0]), int(g[1]))
                except ValueError:
                    pass

        return datetime.now() - timedelta(days=15)

    def _is_engineering_role(self, job: Dict) -> bool:
        title = job.get("title", "").lower()
        return any(kw in title for kw in ENGINEERING_KEYWORDS)
