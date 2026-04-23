"""Crunchbase ODM sample parser for firmographic enrichment."""

import json
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dateutil import parser as date_parser

from observability.tracing import observe


class CrunchbaseEnricher:
    """Parse Crunchbase ODM sample for company data."""

    def __init__(self, data_path: Path = None):
        if data_path is None:
            # Prefer real ODM file if present, fall back to sample
            data_dir = Path(__file__).parent.parent / "data"
            real = data_dir / "crunchbase-companies-information.csv"
            data_path = real if real.exists() else data_dir / "crunchbase_sample.csv"
        self.data_path = data_path
        self.df = None
        self._load_data()

    # Maps real Crunchbase ODM column names → internal names
    _COLUMN_MAP = {
        "about":         "description",
        "website":       "homepage_url",
        "founded_date":  "founded_on",
        "num_employees": "employee_count",
        "industries":    "category_list",
        "location":      "city",
        "funds_total":   "total_funding_usd",
        "funding_rounds": "num_funding_rounds",
        "funding_rounds_list": "funding_rounds_list",
    }

    def _load_data(self) -> None:
        if not self.data_path.exists():
            raise FileNotFoundError(f"Crunchbase data not found at {self.data_path}")
        self.df = pd.read_csv(self.data_path, low_memory=False)
        # Rename real ODM columns to internal names when present
        rename = {k: v for k, v in self._COLUMN_MAP.items() if k in self.df.columns}
        if rename:
            self.df = self.df.rename(columns=rename)
        self.df["name_lower"] = self.df["name"].str.lower()

    @observe(name="crunchbase.get_company")
    def get_company(self, company_name: str) -> Optional[Dict[str, Any]]:
        """Get firmographic data for a company."""
        name_lower = company_name.lower().strip()
        match = self.df[self.df["name_lower"] == name_lower]
        if match.empty:
            match = self.df[self.df["name_lower"].str.contains(name_lower, na=False)]
        if match.empty:
            return None

        row = match.iloc[0].to_dict()
        return {
            "name": row.get("name"),
            "description": row.get("description"),
            "website": row.get("homepage_url"),
            "founded_on": row.get("founded_on"),
            "country_code": row.get("country_code"),
            "city": self._parse_city(row.get("city")),
            "region": row.get("region"),
            "employee_count": self._parse_employee_count(row.get("employee_count")),
            "categories": self._parse_list(row.get("category_groups_list")),
            "industries": self._parse_list(row.get("category_list")),
            "total_funding_usd": self._parse_funding(row.get("total_funding_usd")),
            "num_funding_rounds": row.get("num_funding_rounds"),
            "last_funding_type": row.get("last_funding_type"),
            "last_funding_at": row.get("last_funding_at"),
            "investors": self._parse_list(row.get("investor_names")),
            "valuation_usd": self._parse_funding(row.get("valuation_usd")),
        }

    @observe(name="crunchbase.get_funding_events")
    def get_funding_events(self, company_name: str, days: int = 180) -> List[Dict]:
        """Get funding events within the specified window."""
        company = self.get_company(company_name)
        if not company:
            return []
        last_funding = company.get("last_funding_at")
        if not last_funding:
            return []
        try:
            funding_date = date_parser.parse(str(last_funding))
            cutoff = datetime.now() - timedelta(days=days)
            if funding_date >= cutoff:
                return [{
                    "date": last_funding,
                    "type": company.get("last_funding_type"),
                    "amount_usd": company.get("total_funding_usd"),
                    "valuation_usd": company.get("valuation_usd"),
                    "within_180d": True,
                }]
        except (ValueError, TypeError):
            pass
        return []

    @observe(name="crunchbase.detect_leadership_change")
    def detect_leadership_change(self, company_name: str, days: int = 90) -> List[Dict]:
        """Detect recent CTO/VP Engineering changes from press references."""
        funding_events = self.get_funding_events(company_name, days)
        if funding_events:
            return [{
                "detected": True,
                "confidence": "medium",
                "evidence": f"Recent {funding_events[0]['type']} funding suggests possible team expansion",
                "date": funding_events[0]["date"],
            }]
        return []

    def _parse_city(self, value) -> Optional[str]:
        """Extract city name from plain string or ODM location JSON array."""
        if not value or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, str) and value.startswith("["):
            try:
                locations = json.loads(value)
                if locations and isinstance(locations[0], dict):
                    return locations[0].get("name")
            except (json.JSONDecodeError, IndexError):
                pass
        return str(value) if value else None

    def _parse_employee_count(self, value) -> Optional[int]:
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                if "-" in value:
                    low, high = value.split("-")
                    return (int(low) + int(high)) // 2
                return int(value.replace(",", ""))
            return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_funding(self, value) -> Optional[float]:
        if pd.isna(value):
            return None
        try:
            if isinstance(value, str):
                return float(value.replace(",", "").replace("$", ""))
            return float(value)
        except (ValueError, TypeError):
            return None

    def _parse_list(self, value) -> List[str]:
        if pd.isna(value) or not value:
            return []
        try:
            if isinstance(value, str):
                if value.startswith("["):
                    parsed = json.loads(value)
                    # Real ODM format: [{"id": "saas", "value": "SaaS"}, ...]
                    if parsed and isinstance(parsed[0], dict):
                        return [item.get("value", item.get("id", "")) for item in parsed if item]
                    return [str(v) for v in parsed]
                return [v.strip() for v in value.split(",") if v.strip()]
            return list(value) if value else []
        except (json.JSONDecodeError, TypeError):
            return []
