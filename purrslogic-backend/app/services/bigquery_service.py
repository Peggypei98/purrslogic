import os
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

from app.services.health_budget import resolve_health_budget


class BigQueryService:
    BQ_VIEW = os.getenv(
        "PURRSLOGIC_BQ_RECOVERY_VIEW",
        "purrslogic.gcs_health.view_daily_recovery_summary",
    )

    def __init__(self):
        current_file = Path(__file__).resolve()

        possible_paths = [
            current_file.parent.parent.parent / "config" / "purrslogic-gcp-key.json",
            current_file.parent.parent / "config" / "purrslogic-gcp-key.json",
            Path.cwd() / "config" / "purrslogic-gcp-key.json",
        ]

        self.key_path = None
        for path in possible_paths:
            if path.exists():
                self.key_path = path
                break

        if self.key_path:
            print(f"🟢 [Purrslogic Radar] successfully found GCP key! Path: {self.key_path}")
            credentials = service_account.Credentials.from_service_account_file(str(self.key_path))
            self.client = bigquery.Client(credentials=credentials, project=credentials.project_id)
        else:
            print("\n❌ [Purrslogic Alert] GCP JSON key file not found! Radar searched through these paths:")
            for path in possible_paths:
                print(f"  🔍 Search failed: {path.absolute()}")
            print(
                "Please compare the paths above, confirm if your file is in the correct folder, "
                "or if the name is misspelled (must be exactly lowercase purrslogic-gcp-key.json)\n"
            )
            raise FileNotFoundError("GCP Service Account Key is missing. Check paths printed above.")

    def get_daily_recovery_summary(self, limit: int = 7):
        """Fetch processed daily health recovery features from BigQuery view."""
        query = f"""
            SELECT
                CAST(date AS STRING) as date,
                total_sleep_minutes,
                deep_sleep_ratio_pct,
                hrv_ms,
                resting_heart_rate_bpm,
                respiratory_rate_pm
            FROM `{self.BQ_VIEW}`
            ORDER BY date DESC
            LIMIT {limit};
        """

        try:
            query_job = self.client.query(query)
            results = query_job.result()

            recovery_data = []
            for row in results:
                recovery_data.append({
                    "date": row.date,
                    "total_sleep_minutes": row.total_sleep_minutes,
                    "deep_sleep_ratio_pct": row.deep_sleep_ratio_pct,
                    "hrv_ms": row.hrv_ms,
                    "resting_heart_rate_bpm": row.resting_heart_rate_bpm,
                    "respiratory_rate_pm": row.respiratory_rate_pm,
                })
            return recovery_data

        except Exception as error:
            print(f"Error querying BigQuery: {error}")
            return {"error": str(error)}

    def get_today_health_budget(self, user_id: str) -> int:
        """Derive today's energy budget from the latest BigQuery recovery row."""
        try:
            rows = self.get_daily_recovery_summary(limit=7)
            if isinstance(rows, dict) and rows.get("error"):
                return 45
            resolution = resolve_health_budget(rows if isinstance(rows, list) else [])
            return resolution.budget if resolution.budget is not None else 45
        except Exception as error:
            print(f"❌ Failed to fetch health metrics from BigQuery: {error}")
            return 35
