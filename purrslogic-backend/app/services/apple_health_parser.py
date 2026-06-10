"""
Parse Apple Health export.xml (from iPhone Settings → Export All Health Data).
Adapted from Peggy's original parse_health.py CLI script.
"""

from __future__ import annotations

import csv
import io
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

SLEEP_ASLEEP_VALUES = frozenset({"2", "3", "4", "AsleepCore", "AsleepDeep", "AsleepREM"})
SLEEP_DEEP_VALUES = frozenset({"3", "AsleepDeep"})


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
    """Mirror purrslogic.gcs_health.view_daily_recovery_summary SQL logic."""
    sleep_by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"total_in_bed": 0.0, "total_sleep": 0.0, "deep_sleep": 0.0}
    )
    for _metric, start, end, value in sleep_rows:
        start_dt = _parse_apple_timestamp(start)
        end_dt = _parse_apple_timestamp(end)
        minutes = (end_dt - start_dt).total_seconds() / 60.0
        check_date = _pacific_date(end_dt)
        sleep_by_date[check_date]["total_in_bed"] += minutes
        if value in SLEEP_ASLEEP_VALUES:
            sleep_by_date[check_date]["total_sleep"] += minutes
        if value in SLEEP_DEEP_VALUES:
            sleep_by_date[check_date]["deep_sleep"] += minutes

    vitals_by_date: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"HRV": [], "RestingHeartRate": [], "RespiratoryRate": []}
    )
    for metric, start, _end, value, _unit in vitals_rows:
        if metric not in ("HRV", "RestingHeartRate", "RespiratoryRate"):
            continue
        try:
            check_date = _pacific_date(_parse_apple_timestamp(start))
            vitals_by_date[check_date][metric].append(float(value))
        except (TypeError, ValueError):
            continue

    rows: list[dict] = []
    for check_date in sorted(sleep_by_date.keys(), reverse=True):
        sleep = sleep_by_date[check_date]
        total_sleep = sleep["total_sleep"]
        if total_sleep <= 120:
            continue

        deep_sleep = sleep["deep_sleep"]
        vitals = vitals_by_date.get(check_date, {})
        deep_ratio = round(deep_sleep / total_sleep * 100, 2) if total_sleep else None
        hrv_vals = vitals.get("HRV", [])
        rhr_vals = vitals.get("RestingHeartRate", [])
        resp_vals = vitals.get("RespiratoryRate", [])

        rows.append({
            "date": check_date,
            "total_sleep_minutes": round(total_sleep, 1),
            "deep_sleep_ratio_pct": deep_ratio,
            "hrv_ms": round(sum(hrv_vals) / len(hrv_vals), 2) if hrv_vals else None,
            "resting_heart_rate_bpm": (
                round(sum(rhr_vals) / len(rhr_vals), 2) if rhr_vals else None
            ),
            "respiratory_rate_pm": (
                round(sum(resp_vals) / len(resp_vals), 2) if resp_vals else None
            ),
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
    """Stream-parse export.xml into CSV shards and a daily recovery summary."""
    counts = ParseCounts()
    vitals_rows: list[tuple] = []
    sleep_rows: list[tuple] = []
    activity_rows: list[tuple] = []
    mobility_rows: list[tuple] = []

    csv_buffers: dict[str, io.StringIO] | None = None
    writers: dict[str, csv.writer] = {}
    if write_csv_dir:
        write_csv_dir.mkdir(parents=True, exist_ok=True)
    else:
        csv_buffers = {
            "vitals": io.StringIO(),
            "sleep": io.StringIO(),
            "activity": io.StringIO(),
            "mobility": io.StringIO(),
        }
        writers["vitals"] = csv.writer(csv_buffers["vitals"])
        writers["sleep"] = csv.writer(csv_buffers["sleep"])
        writers["activity"] = csv.writer(csv_buffers["activity"])
        writers["mobility"] = csv.writer(csv_buffers["mobility"])
        writers["vitals"].writerow(["metric", "startDate", "endDate", "value", "unit"])
        writers["sleep"].writerow(["metric", "startDate", "endDate", "value"])
        writers["activity"].writerow(["metric", "startDate", "endDate", "value", "unit"])
        writers["mobility"].writerow(["metric", "startDate", "endDate", "value", "unit"])

    file_handles: list = []
    try:
        if write_csv_dir:
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
                    writers["vitals"].writerow([metric, start, end, val, unit])
                    vitals_rows.append((metric, start, end, val, unit))
                    counts.vitals += 1
                elif record_type == "HKCategoryTypeIdentifierSleepAnalysis":
                    writers["sleep"].writerow(["SleepAnalysis", start, end, val])
                    sleep_rows.append(("SleepAnalysis", start, end, val))
                    counts.sleep += 1
                elif record_type in ACTIVITY_TYPES:
                    metric = ACTIVITY_TYPES[record_type]
                    writers["activity"].writerow([metric, start, end, val, unit])
                    activity_rows.append((metric, start, end, val, unit))
                    counts.activity += 1
                elif record_type in MOBILITY_TYPES:
                    metric = MOBILITY_TYPES[record_type]
                    writers["mobility"].writerow([metric, start, end, val, unit])
                    mobility_rows.append((metric, start, end, val, unit))
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
        daily = _aggregate_daily_recovery(vitals_rows, sleep_rows)
        csv_files: dict[str, str] = {}
        if write_csv_dir:
            csv_files = {
                "vitals": str(write_csv_dir / "apple_health_vitals.csv"),
                "sleep": str(write_csv_dir / "apple_health_sleep.csv"),
                "activity": str(write_csv_dir / "apple_health_activity.csv"),
                "mobility": str(write_csv_dir / "apple_health_mobility.csv"),
            }
        elif csv_buffers:
            csv_files = {key: buf.getvalue() for key, buf in csv_buffers.items()}

        return AppleHealthParseResult(
            counts=counts,
            daily_recovery_summary=daily,
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
