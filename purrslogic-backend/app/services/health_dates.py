"""Shared date helpers for health metrics (avoids circular imports)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def today_pacific_iso() -> str:
    return datetime.now(PACIFIC).date().isoformat()


def parse_health_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
