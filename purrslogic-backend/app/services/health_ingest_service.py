"""Orchestrate Apple Health zip upload, parse, Mongo persist, optional BigQuery read."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.database import db
from app.services.apple_health_parser import parse_apple_health_file, parse_apple_health_upload
from app.services.health_analytics_service import compute_health_analytics
from app.services.health_budget import budget_meta_dict, resolve_health_budget
from app.services.health_dates import today_pacific_iso


class HealthIngestService:
    def _build_response(
        self,
        result,
        user_id: str,
        filename: str,
        save_csv_dir: Path | None,
    ) -> dict[str, Any]:
        resolution = resolve_health_budget(result.daily_recovery_summary)
        meta = budget_meta_dict(resolution)
        analytics = compute_health_analytics(
            result.daily_recovery_summary,
            result.activity_daily,
            result.mobility_daily,
        )

        return {
            "status": "success",
            "user_id": user_id,
            "days_parsed": len(result.daily_recovery_summary),
            "daily_recovery_summary": result.daily_recovery_summary[:14],
            "health_analytics": analytics,
            "wellness_scores": analytics.get("wellness_scores"),
            "budget_recovery_row": resolution.recovery_row,
            "today_health_budget": resolution.budget,
            "budget_meta": meta,
            "today_date_pacific": resolution.today_date_pacific,
            # Backward-compatible aliases
            "today_recovery": resolution.recovery_row,
            "csv_saved_to": str(save_csv_dir) if save_csv_dir else None,
            "next_steps": [
                "Your energy budget is now available to /api/v1/calendar/today.",
                "Optional: load CSVs to GCS → BigQuery tables for purrslogic.gcs_health.*",
            ],
            "_doc": {
                "user_id": user_id,
                "uploaded_at": datetime.now(timezone.utc),
                "source_filename": filename,
                "daily_recovery_summary": result.daily_recovery_summary,
                "activity_daily": result.activity_daily,
                "mobility_daily": result.mobility_daily,
                "health_analytics": analytics,
                "budget_recovery_row": resolution.recovery_row,
                "today_recovery": resolution.recovery_row,
                "today_health_budget": resolution.budget,
                "budget_meta": meta,
                "today_date_pacific": resolution.today_date_pacific,
            },
        }

    async def _persist_upload(self, doc: dict[str, Any]) -> None:
        await db.health_uploads.update_one(
            {"user_id": doc["user_id"]},
            {"$set": doc},
            upsert=True,
        )

    async def process_upload(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        save_csv_dir: Path | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(
            parse_apple_health_upload,
            file_bytes,
            filename,
            save_csv_dir,
        )
        payload = self._build_response(result, user_id, filename, save_csv_dir)
        await self._persist_upload(payload.pop("_doc"))
        return payload

    async def process_upload_stream(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        save_csv_dir: Path | None = None,
    ) -> AsyncIterator[str]:
        """Yield NDJSON progress events, then a final `done` or `error` event."""
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        file_size_mb = round(len(file_bytes) / (1024 * 1024), 2)

        def on_progress(event: dict) -> None:
            if event.get("stage") == "received":
                event["file_size_mb"] = file_size_mb
            loop.call_soon_threadsafe(progress_queue.put_nowait, {"type": "progress", **event})

        async def run_pipeline() -> None:
            try:
                result = await asyncio.to_thread(
                    parse_apple_health_upload,
                    file_bytes,
                    filename,
                    save_csv_dir,
                    on_progress,
                )
                await progress_queue.put({
                    "type": "progress",
                    "stage": "calculating_budget",
                    "percent": 90,
                })
                payload = self._build_response(result, user_id, filename, save_csv_dir)
                await progress_queue.put({
                    "type": "progress",
                    "stage": "saving",
                    "percent": 96,
                })
                await self._persist_upload(payload.pop("_doc"))
                await progress_queue.put({
                    "type": "progress",
                    "stage": "complete",
                    "percent": 100,
                })
                await progress_queue.put({"type": "done", "result": payload})
            except Exception as error:
                await progress_queue.put({"type": "error", "detail": str(error)})
            finally:
                await progress_queue.put(None)

        worker = asyncio.create_task(run_pipeline())
        try:
            while True:
                event = await progress_queue.get()
                if event is None:
                    break
                yield json.dumps(event, default=str) + "\n"
        finally:
            await worker

    async def process_upload_stream_from_path(
        self,
        file_path: Path,
        filename: str,
        user_id: str,
        save_csv_dir: Path | None = None,
    ) -> AsyncIterator[str]:
        """Yield NDJSON progress events from a file on disk (lower peak memory)."""
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict | None] = asyncio.Queue()

        file_size_mb = round(file_path.stat().st_size / (1024 * 1024), 2)

        def on_progress(event: dict) -> None:
            if event.get("stage") == "received":
                event["file_size_mb"] = file_size_mb
            loop.call_soon_threadsafe(progress_queue.put_nowait, {"type": "progress", **event})

        async def run_pipeline() -> None:
            try:
                result = await asyncio.to_thread(
                    parse_apple_health_file,
                    file_path,
                    filename,
                    save_csv_dir,
                    on_progress,
                )
                await progress_queue.put({
                    "type": "progress",
                    "stage": "calculating_budget",
                    "percent": 90,
                })
                payload = self._build_response(result, user_id, filename, save_csv_dir)
                await progress_queue.put({
                    "type": "progress",
                    "stage": "saving",
                    "percent": 96,
                })
                await self._persist_upload(payload.pop("_doc"))
                await progress_queue.put({
                    "type": "progress",
                    "stage": "complete",
                    "percent": 100,
                })
                await progress_queue.put({"type": "done", "result": payload})
            except Exception as error:
                await progress_queue.put({"type": "error", "detail": str(error)})
            finally:
                await progress_queue.put(None)

        worker = asyncio.create_task(run_pipeline())
        try:
            while True:
                event = await progress_queue.get()
                if event is None:
                    break
                yield json.dumps(event, default=str) + "\n"
        finally:
            await worker

    async def get_stored_summary(self, user_id: str, limit: int = 7) -> dict[str, Any]:
        doc = await db.health_uploads.find_one({"user_id": user_id})
        if not doc:
            return {"status": "not_found", "message": "No Apple Health upload yet."}

        daily = doc.get("daily_recovery_summary") or []
        resolution = resolve_health_budget(daily)
        analytics = doc.get("health_analytics") or compute_health_analytics(
            daily,
            doc.get("activity_daily") or [],
            doc.get("mobility_daily") or [],
        )

        doc.pop("_id", None)
        return {
            "status": "success",
            "user_id": user_id,
            "uploaded_at": doc.get("uploaded_at"),
            "record_counts_scope": doc.get("record_counts_scope", "full_export_lifetime"),
            "today_health_budget": resolution.budget,
            "budget_recovery_row": resolution.recovery_row,
            "today_recovery": resolution.recovery_row,
            "budget_meta": budget_meta_dict(resolution),
            "today_date_pacific": resolution.today_date_pacific,
            "health_analytics": analytics,
            "daily_recovery_summary": daily[:limit],
        }

    async def get_analytics(self, user_id: str) -> dict[str, Any]:
        doc = await db.health_uploads.find_one({"user_id": user_id})
        if not doc:
            return {"status": "not_found", "message": "No Apple Health upload yet."}

        daily = doc.get("daily_recovery_summary") or []
        analytics = doc.get("health_analytics") or compute_health_analytics(
            daily,
            doc.get("activity_daily") or [],
            doc.get("mobility_daily") or [],
        )
        resolution = resolve_health_budget(daily)

        return {
            "status": "success",
            "user_id": user_id,
            "uploaded_at": doc.get("uploaded_at"),
            "today_date_pacific": resolution.today_date_pacific,
            "budget_meta": budget_meta_dict(resolution),
            "health_analytics": analytics,
        }

    async def get_today_budget(self, user_id: str) -> int | None:
        doc = await db.health_uploads.find_one({"user_id": user_id})
        if not doc:
            return None
        resolution = resolve_health_budget(doc.get("daily_recovery_summary") or [])
        return resolution.budget

    async def get_budget_resolution(self, user_id: str):
        doc = await db.health_uploads.find_one({"user_id": user_id})
        if not doc:
            return None
        return resolve_health_budget(doc.get("daily_recovery_summary") or [])


health_ingest_service = HealthIngestService()
