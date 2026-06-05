import os
from google.cloud import bigquery
from google.oauth2 import service_account
from pathlib import Path

class BigQueryService:
    def __init__(self):
        # 1. for local development with VSCode debugger  
        
        current_file = Path(__file__).resolve()
        
        # 2. to prevent folder level混乱，Peggy will scan 3 most likely places to put config  
        possible_paths = [
            current_file.parent.parent.parent / "config" / "purrslogic-gcp-key.json",  # root/config/
            current_file.parent.parent / "config" / "purrslogic-gcp-key.json",         # app/config/
            Path.cwd() / "config" / "purrslogic-gcp-key.json",                          # current working directory/config/
        ]
        
        # 3. start searching sequentially
        self.key_path = None
        for path in possible_paths:
            if path.exists():
                self.key_path = path
                break
        
        # 4. based on the search results, initialize the client
        if self.key_path:
            print(f"🟢 [Purrslogic Radar] successfully found GCP key! Path: {self.key_path}")
            credentials = service_account.Credentials.from_service_account_file(str(self.key_path))
            self.client = bigquery.Client(credentials=credentials, project=credentials.project_id)
        else:
            # 💡 Key: if not found, print out all the paths the radar searched through!
            print("\n❌ [Purrslogic Alert] GCP JSON key file not found! Radar searched through these paths:")
            print("Radar just searched through these paths, and they are all empty:")
            for path in possible_paths:
                print(f"  🔍 Search failed: {path.absolute()}")
            print("Please compare the paths above, confirm if your file is in the correct folder, or if the name is misspelled (must be exactly lowercase purrslogic-gcp-key.json)\n")
            
            # force throw error, prevent program from calling default credentials
            raise FileNotFoundError("GCP Service Account Key is missing. Check paths printed above.")

    def get_daily_recovery_summary(self, limit: int = 7):
        """
        Fetch the processed daily health recovery features from BigQuery View
        """
        query = f"""
            SELECT 
                CAST(date AS STRING) as date,
                total_sleep_minutes,
                deep_sleep_ratio_pct,
                hrv_ms,
                resting_heart_rate_bpm,
                respiratory_rate_pm
            FROM `purrslogic.gcs.view_daily_recovery_summary`
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
                    "respiratory_rate_pm": row.respiratory_rate_pm
                })
            return recovery_data
            
        except Exception as e:
            print(f"Error querying BigQuery: {e}")
            return {"error": str(e)}
        
    def get_today_health_budget(self, user_id: str) -> int:
        """
        [Day 12] Fetches Apple Watch physiological telemetry (HRV, Sleep, Resting HR) 
        from BigQuery and calculates today's baseline energy pool budget.
        """
        try:
            # TODO: In future iterations, execute actual SQL query against BigQuery table
            # For now, we simulate a realistic daily health budget based on standard vitals.
            # A perfect night gives 50 points, a standard night gives 35-40 points.
            mock_health_budget = 45 
            return mock_health_budget
        except Exception as e:
            print(f"❌ Failed to fetch health metrics from BigQuery: {e}")
            return 35 # Safe fallback budget if data pipe fails