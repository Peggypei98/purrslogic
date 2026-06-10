"""Map Apple Watch recovery metrics to Purrslogic daily energy budget."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

BudgetSource = Literal["today", "stale", "insufficient"]


@dataclass
class BudgetResolution:
    budget: int | None
    source: BudgetSource
    source_date: str | None
    today_date_pacific: str
    recovery_row: dict | None


def calculate_health_budget(recovery_row: dict) -> int:
    """Convert sleep + HRV + deep-sleep ratio into a 30–55 point daily budget."""
    budget = 35

    sleep_min = recovery_row.get("total_sleep_minutes") or 0
    if sleep_min >= 420:
        budget += 10
    elif sleep_min >= 360:
        budget += 6
    elif sleep_min >= 300:
        budget += 3
    elif sleep_min < 240:
        budget -= 5

    deep_pct = recovery_row.get("deep_sleep_ratio_pct")
    if deep_pct is not None:
        if deep_pct >= 22:
            budget += 4
        elif deep_pct >= 15:
            budget += 2

    hrv = recovery_row.get("hrv_ms")
    if hrv is not None:
        if hrv >= 55:
            budget += 5
        elif hrv >= 40:
            budget += 2
        elif hrv < 25:
            budget -= 3

    rhr = recovery_row.get("resting_heart_rate_bpm")
    if rhr is not None and rhr > 72:
        budget -= 2

    return max(30, min(55, budget))


def today_pacific_iso() -> str:
    return datetime.now(PACIFIC).date().isoformat()


def resolve_health_budget(daily_rows: list[dict]) -> BudgetResolution:
    """
    Pick which day's recovery metrics drive today's energy budget.

    - today: Pacific calendar day matches a daily summary row
    - stale: no row for today; use most recent day with main sleep (>120 min)
    - insufficient: no qualifying daily rows at all
    """
    today = today_pacific_iso()
    today_row = next((row for row in daily_rows if row.get("date") == today), None)
    if today_row:
        return BudgetResolution(
            budget=calculate_health_budget(today_row),
            source="today",
            source_date=today,
            today_date_pacific=today,
            recovery_row=today_row,
        )

    if daily_rows:
        stale_row = daily_rows[0]
        return BudgetResolution(
            budget=calculate_health_budget(stale_row),
            source="stale",
            source_date=stale_row.get("date"),
            today_date_pacific=today,
            recovery_row=stale_row,
        )

    return BudgetResolution(
        budget=None,
        source="insufficient",
        source_date=None,
        today_date_pacific=today,
        recovery_row=None,
    )


def budget_meta_dict(resolution: BudgetResolution) -> dict:
    """Serializable budget provenance for API / MongoDB."""
    return {
        "source": resolution.source,
        "source_date": resolution.source_date,
        "today_date_pacific": resolution.today_date_pacific,
        "is_today_data": resolution.source == "today",
        "is_fallback": resolution.source != "today",
    }


def pick_today_recovery_row(daily_rows: list[dict]) -> dict | None:
    """Backward-compatible helper — returns the row used for budget."""
    return resolve_health_budget(daily_rows).recovery_row
