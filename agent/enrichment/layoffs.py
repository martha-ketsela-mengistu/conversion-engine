"""Layoffs.fyi data integration."""

import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dateutil import parser as date_parser

from observability.tracing import observe


class LayoffsEnricher:
    """Check for recent layoffs from layoffs.fyi dataset."""

    def __init__(self, data_path: Path = None):
        if data_path is None:
            data_path = Path(__file__).parent.parent / "data" / "layoffs.csv"
        self.data_path = data_path
        self.df = None
        self._load_data()

    def _load_data(self) -> None:
        if not self.data_path.exists():
            print(f"Warning: Layoffs data not found at {self.data_path}")
            self.df = pd.DataFrame()
            return
        self.df = pd.read_csv(self.data_path)
        self.df["company_lower"] = self.df["company"].str.lower()

    @observe(name="layoffs.get_layoffs")
    def get_layoffs(self, company_name: str, days: int = 120) -> Optional[Dict[str, Any]]:
        """Check if company had layoffs in the specified window."""
        if self.df.empty:
            return None

        name_lower = company_name.lower().strip()
        matches = self.df[self.df["company_lower"] == name_lower]
        if matches.empty:
            matches = self.df[self.df["company_lower"].str.contains(name_lower, na=False)]
        if matches.empty:
            return None

        cutoff = datetime.now() - timedelta(days=days)
        recent_layoffs = []

        for _, row in matches.iterrows():
            try:
                layoff_date = date_parser.parse(str(row.get("date")))
                if layoff_date >= cutoff:
                    recent_layoffs.append({
                        "date": str(row.get("date")),
                        "headcount_affected": row.get("headcount_affected"),
                        "percentage": row.get("percentage"),
                        "source": row.get("source"),
                    })
            except (ValueError, TypeError):
                continue

        if recent_layoffs:
            return {
                "has_recent_layoffs": True,
                "within_120d": True,
                "events": recent_layoffs,
                "latest_event": recent_layoffs[0],
            }

        return {"has_recent_layoffs": False, "within_120d": False}
