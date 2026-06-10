#!/usr/bin/env python3
"""
CLI wrapper for Apple Health export parsing (original Peggy workflow).

Usage:
  cd purrslogic-backend
  python scripts/parse_health.py path/to/export.zip
  python scripts/parse_health.py path/to/export.xml --csv-dir ./output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.apple_health_parser import parse_apple_health_upload, parse_apple_health_zip


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Apple Health export.zip → CSV + daily summary")
    parser.add_argument("path", help="export.zip or export.xml")
    parser.add_argument("--csv-dir", default=".", help="Directory to write apple_health_*.csv files")
    args = parser.parse_args()

    source = Path(args.path)
    csv_dir = Path(args.csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)

    if source.suffix.lower() == ".zip":
        result = parse_apple_health_zip(source, csv_output_dir=csv_dir)
    else:
        result = parse_apple_health_upload(
            source.read_bytes(),
            source.name,
            csv_output_dir=csv_dir,
        )

    counts = result.counts
    print("🎉 Multi-modal data extraction successful!")
    print(f"  - Vitals:   {counts.vitals:,} → {csv_dir / 'apple_health_vitals.csv'}")
    print(f"  - Sleep:    {counts.sleep:,} → {csv_dir / 'apple_health_sleep.csv'}")
    print(f"  - Activity: {counts.activity:,} → {csv_dir / 'apple_health_activity.csv'}")
    print(f"  - Mobility: {counts.mobility:,} → {csv_dir / 'apple_health_mobility.csv'}")
    print(f"\n📊 Daily recovery rows: {len(result.daily_recovery_summary)}")
    for row in result.daily_recovery_summary[:5]:
        print(f"  {row['date']}: sleep={row['total_sleep_minutes']}m HRV={row.get('hrv_ms')}")


if __name__ == "__main__":
    main()
