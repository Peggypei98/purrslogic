"""
Parse Apple Health export.xml (from iPhone Settings → Export All Health Data).
Adapted from Peggy's original parse_health.py CLI script.
"""

from __future__ import annotations

import csv
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

ProgressCallback = Callable[[dict], None]
PARSE_PROGRESS_INTERVAL = 10_000

PACIFIC = ZoneInfo("America/Los_Angeles")

VITALS_TYPES = {
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "HRV",
    "HKQuantityTypeIdentifierRestingHeartRate": "RestingHeartRate",
    "HKQuantityTypeIdentifierRespiratoryRate": "RespiratoryRate",
    "HKQuantityTypeIdentifierOxygenSaturation": "OxygenSaturation",
}

ACTIVITY_TYPES = {
    "HKQuantityTypeIdentifierActiveEnergyBurned": "ActiveEnergyBurned",
    "HKQuantityTypeIdentifierAppleExerciseTime": "AppleExerciseTime",
}

MOBILITY_TYPES = {
    "HKQuantityTypeIdentifierWalkingSpeed": "WalkingSpeed",
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage": "WalkingAsymmetry",
}

# Legacy constants kept for datamodeling.sql reference; parser uses _classify_sleep_segment().
SLEEP_ASLEEP_VALUES = frozenset({"2", "3", "4", "AsleepCore", "AsleepDeep", "AsleepREM"})
SLEEP_DEEP_VALUES = frozenset({"3", "AsleepDeep"})


def _sleep_value_samples(sleep_rows: list[tuple]) -> set[str]:
    return {str(row[3]).strip() for row in sleep_rows[:8000] if row[3]}


def _detect_sleep_encoding(sleep_rows: list[tuple]) -> str:
    sample = _sleep_value_samples(sleep_rows)
    if any("HKCategory" in v or "Asleep" in v or "InBed" in v or "Awake" in v for v in sample):
        return "modern"
    return "legacy"


def _classify_sleep_segment(value: str, encoding: str) -> str:
    """Return: in_bed | awake | asleep | deep | unknown."""
    v = (value or "").strip()
    if not v:
        return "unknown"

    compact = v.replace("HKCategoryValueSleepAnalysis", "").replace("_", "").lower()

    if encoding == "modern":
        if v == "2" or "awake" in compact:
            return "awake"
        if v == "0" or compact == "inbed":
            return "in_bed"
        if v == "4" or "asleepdeep" in compact:
            return "deep"
        if v in ("3", "5") or "asleepcore" in compact or "asleeprem" in compact:
            return "asleep"
        if v == "1" or "asleepunspecified" in compact or compact == "asleep":
            return "asleep"
        return "unknown"

    # Legacy numeric export (matches datamodeling.sql)
    if v == "2":
        return "asleep"
    if v == "3":
        return "deep"
    if v == "4":
        return "asleep"
    if v == "0":
        return "in_bed"
    if v == "1":
        return "asleep"
    return "unknown"


@dataclass
class ParseCounts:
    vitals: int = 0
    sleep: int = 0
    activity: int = 0
    mobility: int = 0


@dataclass
class AppleHealthParseResult:
    counts: ParseCounts = field(default_factory=ParseCounts)
    daily_recovery_summary: list[dict] = field(default_factory=list)
    activity_daily: list[dict] = field(default_factory=list)
    mobility_daily: list[dict] = field(default_factory=list)
    csv_files: dict[str, str] = field(default_factory=dict)


def _parse_apple_timestamp(value: str) -> datetime:
    """Apple export dates look like '2024-06-01 07:30:00 -0700'."""
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=PACIFIC)
            return parsed
        except ValueError:
            continue
    raise ValueError(f"Unrecognized Apple Health date: {value}")


def _pacific_date(ts: datetime) -> str:
    return ts.astimezone(PACIFIC).date().isoformat()


def preprocess_xml(source_path: Path, dest_path: Path) -> None:
    """Strip DTD and invisible characters that break ElementTree."""
    with (
        source_path.open("r", encoding="UTF-8") as infile,
        dest_path.open("w", encoding="UTF-8") as outfile,
    ):
        skip_dtd = False
        for line in infile:
            if "<!DOCTYPE" in line:
                skip_dtd = True
            if not skip_dtd:
                outfile.write(line.replace("\x0b", ""))
            if "]>" in line:
                skip_dtd = False


def extract_export_xml_from_zip(zip_path: Path, work_dir: Path) -> Path:
    """Accept export.zip or a zip that contains apple_health_export/export.xml."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        candidates = [
            name
            for name in names
            if name.endswith("export.xml") and not name.startswith("__MACOSX")
        ]
        if not candidates:
            raise ValueError(
                "No export.xml found in zip. Export from iPhone: "
                "Settings → Health → Export All Health Data."
            )
        xml_name = "apple_health_export/export.xml"
        if xml_name not in candidates:
            xml_name = candidates[0]
        target = work_dir / "export.xml"
        with archive.open(xml_name) as src, target.open("wb") as dst:
            dst.write(src.read())
        return target


def _aggregate_daily_recovery(
    vitals_rows: list[tuple],
    sleep_rows: list[tuple],
) -> list[dict]:
    """Build daily sleep + vitals rows (Pacific), main sleep > 120 min."""
    encoding = _detect_sleep_encoding(sleep_rows)
    sleep_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "total_in_bed": 0.0,
            "total_sleep": 0.0,
            "deep_sleep": 0.0,
            "awake": 0.0,
        }
    )
    for _metric, start, end, value in sleep_rows:
        _apply_sleep_segment(sleep_by_date, start, end, value, encoding)

    vitals_by_date: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: {
            "HRV": {"sum": 0.0, "count": 0.0},
            "RestingHeartRate": {"sum": 0.0, "count": 0.0},
            "RespiratoryRate": {"sum": 0.0, "count": 0.0},
        }
    )
    for metric, start, _end, value, _unit in vitals_rows:
        _apply_vital_sample(vitals_by_date, metric, start, value)

    return _finalize_daily_recovery(sleep_by_date, vitals_by_date)


def _infer_sleep_encoding(value: str, current: str) -> str:
    if current == "modern":
        return current
    sample = (value or "").strip()
    if any(token in sample for token in ("HKCategory", "Asleep", "InBed", "Awake")):
        return "modern"
    return current


def _apply_sleep_segment(
    sleep_by_date: dict[str, dict[str, float]],
    start: str,
    end: str,
    value: str,
    encoding: str,
) -> None:
    start_dt = _parse_apple_timestamp(start)
    end_dt = _parse_apple_timestamp(end)
    minutes = (end_dt - start_dt).total_seconds() / 60.0
    check_date = _pacific_date(end_dt)
    bucket = sleep_by_date[check_date]
    segment = _classify_sleep_segment(value, encoding)

    if segment == "in_bed":
        bucket["total_in_bed"] += minutes
    elif segment == "awake":
        bucket["awake"] += minutes
        bucket["total_in_bed"] += minutes
    elif segment == "asleep":
        bucket["total_sleep"] += minutes
        bucket["total_in_bed"] += minutes
    elif segment == "deep":
        bucket["total_sleep"] += minutes
        bucket["deep_sleep"] += minutes
        bucket["total_in_bed"] += minutes


def _apply_activity_sample(
    activity_by_date: dict[str, dict[str, float]],
    metric: str,
    start: str,
    value: str,
) -> None:
    try:
        check_date = _pacific_date(_parse_apple_timestamp(start))
        bucket = activity_by_date[check_date]
        amount = float(value)
        if metric == "ActiveEnergyBurned":
            bucket["active_kcal"] += amount
        elif metric == "AppleExerciseTime":
            bucket["exercise_min"] += amount
    except (TypeError, ValueError):
        return


def _apply_mobility_sample(
    mobility_by_date: dict[str, dict[str, float]],
    metric: str,
    start: str,
    value: str,
) -> None:
    try:
        check_date = _pacific_date(_parse_apple_timestamp(start))
        bucket = mobility_by_date[check_date]
        amount = float(value)
        if metric == "WalkingSpeed":
            bucket["speed_sum"] += amount
            bucket["speed_count"] += 1
        elif metric == "WalkingAsymmetry":
            bucket["asym_sum"] += amount
            bucket["asym_count"] += 1
    except (TypeError, ValueError):
        return


def _finalize_activity_daily(activity_by_date: dict[str, dict[str, float]]) -> list[dict]:
    rows: list[dict] = []
    for check_date in sorted(activity_by_date.keys()):
        bucket = activity_by_date[check_date]
        rows.append({
            "date": check_date,
            "active_kcal": round(bucket.get("active_kcal", 0.0), 1),
            "exercise_minutes": round(bucket.get("exercise_min", 0.0), 1),
        })
    return rows


def _finalize_mobility_daily(mobility_by_date: dict[str, dict[str, float]]) -> list[dict]:
    rows: list[dict] = []
    for check_date in sorted(mobility_by_date.keys()):
        bucket = mobility_by_date[check_date]
        speed_count = int(bucket.get("speed_count", 0))
        asym_count = int(bucket.get("asym_count", 0))
        rows.append({
            "date": check_date,
            "avg_walking_speed_mps": (
                round(bucket["speed_sum"] / speed_count, 3) if speed_count else None
            ),
            "avg_walking_asymmetry_pct": (
                round(bucket["asym_sum"] / asym_count, 2) if asym_count else None
            ),
        })
    return rows


def _apply_vital_sample(
    vitals_by_date: dict[str, dict[str, dict[str, float]]],
    metric: str,
    start: str,
    value: str,
) -> None:
    if metric not in ("HRV", "RestingHeartRate", "RespiratoryRate"):
        return
    try:
        check_date = _pacific_date(_parse_apple_timestamp(start))
        bucket = vitals_by_date[check_date][metric]
        bucket["sum"] += float(value)
        bucket["count"] += 1
    except (TypeError, ValueError):
        return


def _finalize_daily_recovery(
    sleep_by_date: dict[str, dict[str, float]],
    vitals_by_date: dict[str, dict[str, dict[str, float]]],
) -> list[dict]:
    rows: list[dict] = []
    for check_date in sorted(sleep_by_date.keys(), reverse=True):
        sleep = sleep_by_date[check_date]
        total_sleep = sleep["total_sleep"]
        if total_sleep <= 120:
            in_bed_net = sleep["total_in_bed"] - sleep["awake"]
            if in_bed_net > 120:
                total_sleep = in_bed_net
            else:
                continue

        deep_sleep = sleep["deep_sleep"]
        vitals = vitals_by_date.get(check_date, {})
        deep_ratio = round(deep_sleep / total_sleep * 100, 2) if total_sleep and deep_sleep else None

        def _avg(metric: str) -> float | None:
            bucket = vitals.get(metric, {})
            count = int(bucket.get("count", 0))
            if count <= 0:
                return None
            return round(bucket["sum"] / count, 2)

        rows.append({
            "date": check_date,
            "total_sleep_minutes": round(total_sleep, 1),
            "deep_sleep_ratio_pct": deep_ratio,
            "hrv_ms": _avg("HRV"),
            "resting_heart_rate_bpm": _avg("RestingHeartRate"),
            "respiratory_rate_pm": _avg("RespiratoryRate"),
        })

    return rows


def _emit_progress(
    on_progress: ProgressCallback | None,
    stage: str,
    percent: int,
    **extra,
) -> None:
    if on_progress:
        on_progress({"stage": stage, "percent": percent, **extra})


def parse_export_xml(
    xml_path: Path,
    write_csv_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> AppleHealthParseResult:
    """Stream-parse export.xml into optional CSV shards and a daily recovery summary."""
    counts = ParseCounts()
    sleep_encoding = "legacy"
    sleep_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "total_in_bed": 0.0,
            "total_sleep": 0.0,
            "deep_sleep": 0.0,
            "awake": 0.0,
        }
    )
    vitals_by_date: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: {
            "HRV": {"sum": 0.0, "count": 0.0},
            "RestingHeartRate": {"sum": 0.0, "count": 0.0},
            "RespiratoryRate": {"sum": 0.0, "count": 0.0},
        }
    )
    activity_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"active_kcal": 0.0, "exercise_min": 0.0}
    )
    mobility_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "speed_sum": 0.0,
            "speed_count": 0.0,
            "asym_sum": 0.0,
            "asym_count": 0.0,
        }
    )

    writers: dict[str, csv.writer] = {}
    file_handles: list = []
    try:
        if write_csv_dir:
            write_csv_dir.mkdir(parents=True, exist_ok=True)
            vitals_file = (write_csv_dir / "apple_health_vitals.csv").open(
                "w", newline="", encoding="utf-8"
            )
            sleep_file = (write_csv_dir / "apple_health_sleep.csv").open(
                "w", newline="", encoding="utf-8"
            )
            activity_file = (write_csv_dir / "apple_health_activity.csv").open(
                "w", newline="", encoding="utf-8"
            )
            mobility_file = (write_csv_dir / "apple_health_mobility.csv").open(
                "w", newline="", encoding="utf-8"
            )
            file_handles = [vitals_file, sleep_file, activity_file, mobility_file]
            writers["vitals"] = csv.writer(vitals_file)
            writers["sleep"] = csv.writer(sleep_file)
            writers["activity"] = csv.writer(activity_file)
            writers["mobility"] = csv.writer(mobility_file)
            writers["vitals"].writerow(["metric", "startDate", "endDate", "value", "unit"])
            writers["sleep"].writerow(["metric", "startDate", "endDate", "value"])
            writers["activity"].writerow(["metric", "startDate", "endDate", "value", "unit"])
            writers["mobility"].writerow(["metric", "startDate", "endDate", "value", "unit"])

        with tempfile.TemporaryDirectory() as tmp:
            cleaned = Path(tmp) / "temp_preprocessed_export.xml"
            _emit_progress(on_progress, "preprocessing_xml", 15)
            preprocess_xml(xml_path, cleaned)
            _emit_progress(on_progress, "parsing_records", 18)

            records_seen = 0
            for _event, elem in ET.iterparse(cleaned, events=("end",)):
                if elem.tag != "Record":
                    elem.clear()
                    continue

                record_type = elem.attrib.get("type")
                start = elem.attrib.get("startDate", "")
                end = elem.attrib.get("endDate", "")
                val = elem.attrib.get("value", "")
                unit = elem.attrib.get("unit", "")

                if record_type in VITALS_TYPES:
                    metric = VITALS_TYPES[record_type]
                    if "vitals" in writers:
                        writers["vitals"].writerow([metric, start, end, val, unit])
                    _apply_vital_sample(vitals_by_date, metric, start, val)
                    counts.vitals += 1
                elif record_type == "HKCategoryTypeIdentifierSleepAnalysis":
                    sleep_encoding = _infer_sleep_encoding(val, sleep_encoding)
                    if "sleep" in writers:
                        writers["sleep"].writerow(["SleepAnalysis", start, end, val])
                    _apply_sleep_segment(sleep_by_date, start, end, val, sleep_encoding)
                    counts.sleep += 1
                elif record_type in ACTIVITY_TYPES:
                    metric = ACTIVITY_TYPES[record_type]
                    if "activity" in writers:
                        writers["activity"].writerow([metric, start, end, val, unit])
                    _apply_activity_sample(activity_by_date, metric, start, val)
                    counts.activity += 1
                elif record_type in MOBILITY_TYPES:
                    metric = MOBILITY_TYPES[record_type]
                    if "mobility" in writers:
                        writers["mobility"].writerow([metric, start, end, val, unit])
                    _apply_mobility_sample(mobility_by_date, metric, start, val)
                    counts.mobility += 1

                records_seen += 1
                if records_seen % PARSE_PROGRESS_INTERVAL == 0:
                    total = (
                        counts.vitals + counts.sleep + counts.activity + counts.mobility
                    )
                    parse_pct = 18 + min(62, int(total / 80_000 * 62))
                    _emit_progress(
                        on_progress,
                        "parsing_records",
                        parse_pct,
                        record_counts={
                            "vitals": counts.vitals,
                            "sleep": counts.sleep,
                            "activity": counts.activity,
                            "mobility": counts.mobility,
                            "total": total,
                        },
                    )

                elem.clear()

        _emit_progress(
            on_progress,
            "parsing_records",
            80,
            record_counts={
                "vitals": counts.vitals,
                "sleep": counts.sleep,
                "activity": counts.activity,
                "mobility": counts.mobility,
                "total": (
                    counts.vitals + counts.sleep + counts.activity + counts.mobility
                ),
            },
        )
        _emit_progress(on_progress, "aggregating", 85)
        daily = _finalize_daily_recovery(sleep_by_date, vitals_by_date)
        activity_daily = _finalize_activity_daily(activity_by_date)
        mobility_daily = _finalize_mobility_daily(mobility_by_date)
        csv_files: dict[str, str] = {}
        if write_csv_dir:
            csv_files = {
                "vitals": str(write_csv_dir / "apple_health_vitals.csv"),
                "sleep": str(write_csv_dir / "apple_health_sleep.csv"),
                "activity": str(write_csv_dir / "apple_health_activity.csv"),
                "mobility": str(write_csv_dir / "apple_health_mobility.csv"),
            }

        return AppleHealthParseResult(
            counts=counts,
            daily_recovery_summary=daily,
            activity_daily=activity_daily,
            mobility_daily=mobility_daily,
            csv_files=csv_files,
        )
    finally:
        for handle in file_handles:
            handle.close()


def parse_apple_health_zip(
    zip_path: Path,
    csv_output_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> AppleHealthParseResult:
    """End-to-end: zip → export.xml → CSV shards + daily recovery summary."""
    with tempfile.TemporaryDirectory() as work_dir:
        _emit_progress(on_progress, "extracting_zip", 10)
        xml_path = extract_export_xml_from_zip(zip_path, Path(work_dir))
        return parse_export_xml(xml_path, write_csv_dir=csv_output_dir, on_progress=on_progress)


def parse_apple_health_file(
    file_path: Path,
    filename: str | None = None,
    csv_output_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> AppleHealthParseResult:
    """Parse from a zip or xml path on disk (lower memory than loading bytes)."""
    resolved_name = filename or file_path.name
    lower = resolved_name.lower()
    if lower.endswith(".xml"):
        _emit_progress(on_progress, "received", 8)
        return parse_export_xml(file_path, write_csv_dir=csv_output_dir, on_progress=on_progress)

    if lower.endswith(".zip"):
        _emit_progress(on_progress, "received", 8)
        return parse_apple_health_zip(file_path, csv_output_dir=csv_output_dir, on_progress=on_progress)

    raise ValueError("Upload export.zip or export.xml from Apple Health.")


def parse_apple_health_upload(
    file_bytes: bytes,
    filename: str,
    csv_output_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
) -> AppleHealthParseResult:
    """Accept .zip or raw export.xml upload bytes."""
    lower = filename.lower()
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        if lower.endswith(".xml"):
            xml_path = work / "export.xml"
            xml_path.write_bytes(file_bytes)
            _emit_progress(on_progress, "received", 8)
            return parse_export_xml(xml_path, write_csv_dir=csv_output_dir, on_progress=on_progress)

        if not lower.endswith(".zip"):
            raise ValueError("Upload export.zip or export.xml from Apple Health.")

        zip_path = work / "upload.zip"
        zip_path.write_bytes(file_bytes)
        _emit_progress(on_progress, "received", 8)
        return parse_apple_health_zip(zip_path, csv_output_dir=csv_output_dir, on_progress=on_progress)
