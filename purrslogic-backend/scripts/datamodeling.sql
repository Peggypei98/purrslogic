-- BigQuery view (matches Peggy's gcs_health dataset)
-- Load apple_health_*.csv into purrslogic.gcs_health.vitals / .sleep first.

CREATE OR REPLACE VIEW `purrslogic.gcs_health.view_daily_recovery_summary` AS
WITH sleep_metrics AS (
  SELECT
    EXTRACT(DATE FROM TIMESTAMP(endDate) AT TIME ZONE 'America/Los_Angeles') AS check_date,
    SUM(TIMESTAMP_DIFF(TIMESTAMP(endDate), TIMESTAMP(startDate), MINUTE)) AS total_in_bed_minutes,
    SUM(CASE WHEN value IN ('2', '3', '4', 'AsleepCore', 'AsleepDeep', 'AsleepREM')
             THEN TIMESTAMP_DIFF(TIMESTAMP(endDate), TIMESTAMP(startDate), MINUTE) ELSE 0 END) AS total_sleep_minutes,
    SUM(CASE WHEN value IN ('3', 'AsleepDeep')
             THEN TIMESTAMP_DIFF(TIMESTAMP(endDate), TIMESTAMP(startDate), MINUTE) ELSE 0 END) AS deep_sleep_minutes
  FROM `purrslogic.gcs_health.sleep`
  GROUP BY check_date
),
vitals_metrics AS (
  SELECT
    EXTRACT(DATE FROM TIMESTAMP(startDate) AT TIME ZONE 'America/Los_Angeles') AS check_date,
    AVG(CASE WHEN metric = 'HRV' THEN CAST(value AS FLOAT64) END) AS avg_hrv,
    AVG(CASE WHEN metric = 'RestingHeartRate' THEN CAST(value AS FLOAT64) END) AS avg_resting_heart_rate,
    AVG(CASE WHEN metric = 'RespiratoryRate' THEN CAST(value AS FLOAT64) END) AS avg_respiratory_rate
  FROM `purrslogic.gcs_health.vitals`
  GROUP BY check_date
)
SELECT
  s.check_date AS date,
  s.total_sleep_minutes,
  ROUND(s.deep_sleep_minutes / NULLIF(s.total_sleep_minutes, 0) * 100, 2) AS deep_sleep_ratio_pct,
  ROUND(v.avg_hrv, 2) AS hrv_ms,
  ROUND(v.avg_resting_heart_rate, 2) AS resting_heart_rate_bpm,
  ROUND(v.avg_respiratory_rate, 2) AS respiratory_rate_pm
FROM sleep_metrics s
LEFT JOIN vitals_metrics v ON s.check_date = v.check_date
WHERE s.total_sleep_minutes > 120
ORDER BY date DESC;
