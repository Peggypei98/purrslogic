"""Rolling and period aggregates from daily_recovery_summary rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.services.health_dates import parse_health_date, today_pacific_iso


def _parse_date(value: str) -> date:
    return parse_health_date(value)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _metric_avg(rows: list[dict], key: str) -> float | None:
    vals = [float(row[key]) for row in rows if row.get(key) is not None]
    return _avg(vals)


def _period_summary(rows: list[dict]) -> dict[str, Any]:
    return {
        "days": len(rows),
        "avg_sleep_minutes": _metric_avg(rows, "total_sleep_minutes"),
        "avg_deep_sleep_ratio_pct": _metric_avg(rows, "deep_sleep_ratio_pct"),
        "avg_hrv_ms": _metric_avg(rows, "hrv_ms"),
        "avg_resting_heart_rate_bpm": _metric_avg(rows, "resting_heart_rate_bpm"),
    }


def _rows_in_date_window(rows: list[dict], start: date, end: date) -> list[dict]:
    return [
        row for row in rows
        if start <= _parse_date(row["date"]) <= end
    ]


def _activity_period_summary(rows: list[dict]) -> dict[str, Any]:
    exercise_vals = [
        float(row["exercise_minutes"])
        for row in rows
        if row.get("exercise_minutes") is not None and row.get("exercise_minutes") > 0
    ]
    kcal_vals = [
        float(row["active_kcal"])
        for row in rows
        if row.get("active_kcal") is not None and row.get("active_kcal") > 0
    ]
    return {
        "days": len(rows),
        "avg_exercise_minutes": _avg(exercise_vals),
        "avg_active_kcal": _avg(kcal_vals),
    }


def _mobility_period_summary(rows: list[dict]) -> dict[str, Any]:
    speed_vals = [
        float(row["avg_walking_speed_mps"])
        for row in rows
        if row.get("avg_walking_speed_mps") is not None
    ]
    asym_vals = [
        float(row["avg_walking_asymmetry_pct"])
        for row in rows
        if row.get("avg_walking_asymmetry_pct") is not None
    ]
    return {
        "days": len(rows),
        "avg_walking_speed_mps": _avg(speed_vals),
        "avg_walking_asymmetry_pct": _avg(asym_vals),
    }


def _pick_30_day_window(
    sorted_rows: list[dict],
    today: date,
) -> tuple[list[dict], str]:
    start = today - timedelta(days=29)
    window = _rows_in_date_window(sorted_rows, start, today)
    if window:
        return window, "calendar"
    return sorted_rows[-30:], "most_recent_days"


def _score_from_points(points: int) -> str:
    if points >= 4:
        return "green"
    if points >= 2:
        return "yellow"
    return "red"


def compute_wellness_scores(
    daily_rows: list[dict],
    activity_daily: list[dict] | None = None,
    mobility_daily: list[dict] | None = None,
) -> dict[str, Any]:
    """Traffic-light wellness scores from ~30-day rolling averages."""
    activity_daily = activity_daily or []
    mobility_daily = mobility_daily or []

    if not daily_rows and not activity_daily and not mobility_daily:
        return {"period_days": 0, "window": None, "categories": {}}

    today = _parse_date(today_pacific_iso())
    recovery_sorted = sorted(daily_rows, key=lambda row: row["date"])
    activity_sorted = sorted(activity_daily, key=lambda row: row["date"])
    mobility_sorted = sorted(mobility_daily, key=lambda row: row["date"])

    recovery_window, window_kind = _pick_30_day_window(recovery_sorted, today)
    activity_window, _ = _pick_30_day_window(activity_sorted, today)
    mobility_window, _ = _pick_30_day_window(mobility_sorted, today)

    recovery = _period_summary(recovery_window)
    activity = _activity_period_summary(activity_window)
    mobility = _mobility_period_summary(mobility_window)

    sleep_min = recovery.get("avg_sleep_minutes")
    deep_pct = recovery.get("avg_deep_sleep_ratio_pct")
    sleep_points = 0
    if sleep_min is not None:
        if sleep_min >= 420:
            sleep_points += 2
        elif sleep_min >= 360:
            sleep_points += 1
    if deep_pct is not None:
        if deep_pct >= 18:
            sleep_points += 2
        elif deep_pct >= 15:
            sleep_points += 1

    hrv = recovery.get("avg_hrv_ms")
    rhr = recovery.get("avg_resting_heart_rate_bpm")
    vitals_points = 0
    if hrv is not None:
        if hrv >= 50:
            vitals_points += 2
        elif hrv >= 35:
            vitals_points += 1
    if rhr is not None:
        if rhr <= 60:
            vitals_points += 2
        elif rhr <= 72:
            vitals_points += 1

    exercise_min = activity.get("avg_exercise_minutes")
    activity_points = 0
    if exercise_min is not None:
        if exercise_min >= 30:
            activity_points = 4
        elif exercise_min >= 15:
            activity_points = 2
        else:
            activity_points = 0
    elif activity.get("avg_active_kcal") is not None:
        kcal = activity["avg_active_kcal"]
        if kcal >= 400:
            activity_points = 4
        elif kcal >= 250:
            activity_points = 2

    walk_speed = mobility.get("avg_walking_speed_mps")
    walk_asym = mobility.get("avg_walking_asymmetry_pct")
    mobility_points = 0
    if walk_speed is not None:
        if walk_speed >= 1.25:
            mobility_points += 2
        elif walk_speed >= 1.0:
            mobility_points += 1
    if walk_asym is not None:
        if walk_asym <= 1.0:
            mobility_points += 2
        elif walk_asym <= 2.5:
            mobility_points += 1

    period_days = max(
        recovery.get("days") or 0,
        activity.get("days") or 0,
        mobility.get("days") or 0,
    )

    def _category(
        key: str,
        level: str,
        headline: str,
        detail: str,
        days: int,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "level": level,
            "headline": headline,
            "detail": detail,
            "days": days,
        }

    sleep_hours = round(sleep_min / 60, 1) if sleep_min is not None else None
    categories = {
        "sleep": _category(
            "sleep",
            _score_from_points(sleep_points) if sleep_min is not None or deep_pct is not None else "unknown",
            f"{sleep_hours} h/night" if sleep_hours is not None else "—",
            f"Deep sleep {deep_pct}%" if deep_pct is not None else "No sleep data",
            recovery.get("days") or 0,
        ),
        "vitals": _category(
            "vitals",
            _score_from_points(vitals_points) if hrv is not None or rhr is not None else "unknown",
            f"HRV {hrv} ms" if hrv is not None else "—",
            f"Resting HR {rhr} bpm" if rhr is not None else "No vitals data",
            recovery.get("days") or 0,
        ),
        "activity": _category(
            "activity",
            _score_from_points(activity_points) if exercise_min is not None or activity.get("avg_active_kcal") else "unknown",
            f"{round(exercise_min)} min/day" if exercise_min is not None else "—",
            (
                f"Active energy {round(activity['avg_active_kcal'])} kcal/day"
                if activity.get("avg_active_kcal") is not None
                else "No activity data"
            ),
            activity.get("days") or 0,
        ),
        "mobility": _category(
            "mobility",
            _score_from_points(mobility_points) if walk_speed is not None or walk_asym is not None else "unknown",
            f"{walk_speed} m/s gait" if walk_speed is not None else "—",
            (
                f"Asymmetry {walk_asym}%"
                if walk_asym is not None
                else "No mobility data"
            ),
            mobility.get("days") or 0,
        ),
    }

    return {
        "period_days": period_days,
        "window": window_kind,
        "categories": categories,
    }


def compute_health_analytics(
    daily_rows: list[dict],
    activity_daily: list[dict] | None = None,
    mobility_daily: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Build export range, rolling averages, and monthly/yearly rollups
    from daily recovery rows (newest-first or any order).
    """
    if not daily_rows:
        return {
            "export_range": None,
            "rolling": {"last_7_days": None, "last_30_days": None, "recent_30_days": None},
            "monthly": [],
            "yearly": [],
            "wellness_scores": compute_wellness_scores([], activity_daily, mobility_daily),
        }

    sorted_rows = sorted(daily_rows, key=lambda row: row["date"])
    dates = [_parse_date(row["date"]) for row in sorted_rows]
    today = _parse_date(today_pacific_iso())

    export_range = {
        "earliest_date": sorted_rows[0]["date"],
        "latest_date": sorted_rows[-1]["date"],
        "days_with_main_sleep": len(sorted_rows),
    }

    last_7_start = today - timedelta(days=6)
    last_30_start = today - timedelta(days=29)
    window_7 = _rows_in_date_window(sorted_rows, last_7_start, today)
    window_30 = _rows_in_date_window(sorted_rows, last_30_start, today)

    # When today has no watch data, calendar windows may be empty — use latest N days.
    recent_7 = window_7 if window_7 else sorted_rows[-7:]
    recent_30 = window_30 if window_30 else sorted_rows[-30:]

    monthly_buckets: dict[str, list[dict]] = defaultdict(list)
    yearly_buckets: dict[str, list[dict]] = defaultdict(list)
    for row in sorted_rows:
        row_date = _parse_date(row["date"])
        monthly_buckets[row_date.strftime("%Y-%m")].append(row)
        yearly_buckets[str(row_date.year)].append(row)

    monthly = []
    for month_key in sorted(monthly_buckets.keys(), reverse=True)[:12]:
        summary = _period_summary(monthly_buckets[month_key])
        summary["month"] = month_key
        monthly.append(summary)

    yearly = []
    for year_key in sorted(yearly_buckets.keys(), reverse=True):
        summary = _period_summary(yearly_buckets[year_key])
        summary["year"] = year_key
        yearly.append(summary)

    return {
        "export_range": export_range,
        "rolling": {
            "last_7_days": {
                "window": "calendar",
                "start_date": last_7_start.isoformat(),
                "end_date": today.isoformat(),
                **_period_summary(window_7),
            } if window_7 else None,
            "last_30_days": {
                "window": "calendar",
                "start_date": last_30_start.isoformat(),
                "end_date": today.isoformat(),
                **_period_summary(window_30),
            } if window_30 else None,
            "recent_7_days": {
                "window": "most_recent_days",
                "note": "Used when calendar last-7 window has no qualifying sleep days.",
                **_period_summary(recent_7),
            },
            "recent_30_days": {
                "window": "most_recent_days",
                "note": "Used when calendar last-30 window has no qualifying sleep days.",
                **_period_summary(recent_30),
            },
        },
        "monthly": monthly,
        "yearly": yearly,
        "wellness_scores": compute_wellness_scores(
            daily_rows,
            activity_daily,
            mobility_daily,
        ),
    }
