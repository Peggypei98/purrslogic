"""Map Apple Watch recovery metrics to Purrslogic daily energy budget."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from app.services.health_analytics_service import _period_summary, _rows_in_date_window
from app.services.health_dates import parse_health_date, today_pacific_iso

THREE_MONTH_LOOKBACK_DAYS = 90

BudgetSource = Literal["today", "rolling_3_month_avg", "stale", "insufficient"]


@dataclass
class BudgetResolution:
    budget: int | None
    source: BudgetSource
    source_date: str | None
    today_date_pacific: str
    recovery_row: dict | None
    baseline_summary: dict | None = None


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


def _synthetic_row_from_averages(summary: dict, as_of: str) -> dict:
    return {
        "date": as_of,
        "total_sleep_minutes": summary.get("avg_sleep_minutes"),
        "deep_sleep_ratio_pct": summary.get("avg_deep_sleep_ratio_pct"),
        "hrv_ms": summary.get("avg_hrv_ms"),
        "resting_heart_rate_bpm": summary.get("avg_resting_heart_rate_bpm"),
    }


def resolve_health_budget(daily_rows: list[dict]) -> BudgetResolution:
    """
    Pick which recovery metrics drive today's energy budget.

    - today: Pacific calendar day matches a daily summary row
    - rolling_3_month_avg: no today row — use last 90 days average as baseline
    - stale: fallback to most recent qualifying day
    - insufficient: no usable data
    """
    today = today_pacific_iso()
    today_date = parse_health_date(today)

    today_row = next((row for row in daily_rows if row.get("date") == today), None)
    if today_row:
        return BudgetResolution(
            budget=calculate_health_budget(today_row),
            source="today",
            source_date=today,
            today_date_pacific=today,
            recovery_row=today_row,
        )

    if not daily_rows:
        return BudgetResolution(
            budget=None,
            source="insufficient",
            source_date=None,
            today_date_pacific=today,
            recovery_row=None,
        )

    sorted_rows = sorted(daily_rows, key=lambda row: row["date"])
    start_3mo = today_date - timedelta(days=THREE_MONTH_LOOKBACK_DAYS - 1)
    window_3mo = _rows_in_date_window(sorted_rows, start_3mo, today_date)

    if window_3mo:
        summary = _period_summary(window_3mo)
        range_label = f"{start_3mo.isoformat()}..{today}"
        synthetic = _synthetic_row_from_averages(summary, range_label)
        if summary.get("avg_sleep_minutes"):
            return BudgetResolution(
                budget=calculate_health_budget(synthetic),
                source="rolling_3_month_avg",
                source_date=range_label,
                today_date_pacific=today,
                recovery_row=synthetic,
                baseline_summary=summary,
            )

    stale_row = sorted_rows[-1]
    return BudgetResolution(
        budget=calculate_health_budget(stale_row),
        source="stale",
        source_date=stale_row.get("date"),
        today_date_pacific=today,
        recovery_row=stale_row,
    )


def budget_meta_dict(resolution: BudgetResolution) -> dict:
    """Serializable budget provenance for API / MongoDB."""
    meta = {
        "source": resolution.source,
        "source_date": resolution.source_date,
        "today_date_pacific": resolution.today_date_pacific,
        "is_today_data": resolution.source == "today",
        "is_fallback": resolution.source != "today",
    }
    if resolution.baseline_summary:
        meta["baseline_summary"] = resolution.baseline_summary
    return meta


def pick_today_recovery_row(daily_rows: list[dict]) -> dict | None:
    """Backward-compatible helper — returns the row used for budget."""
    return resolve_health_budget(daily_rows).recovery_row
