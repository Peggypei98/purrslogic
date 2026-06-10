"""Orchestrate Apple Health zip upload, parse, Mongo persist, optional BigQuery read."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.database import db
from app.services.apple_health_parser import parse_apple_health_upload
from app.services.health_budget import (
    budget_meta_dict,
    resolve_health_budget,
    today_pacific_iso,
)


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

        return {
            "status": "success",
            "user_id": user_id,
            "record_counts": {
                "vitals": result.counts.vitals,
                "sleep": result.counts.sleep,
                "activity": result.counts.activity,
                "mobility": result.counts.mobility,
            },
            "record_counts_scope": "full_export_lifetime",
            "days_parsed": len(result.daily_recovery_summary),
            "daily_recovery_summary": result.daily_recovery_summary[:14],
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
                "record_counts": {
                    "vitals": result.counts.vitals,
                    "sleep": result.counts.sleep,
                    "activity": result.counts.activity,
                    "mobility": result.counts.mobility,
                },
                "record_counts_scope": "full_export_lifetime",
                "daily_recovery_summary": result.daily_recovery_summary[:30],
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

    async def get_stored_summary(self, user_id: str, limit: int = 7) -> dict[str, Any]:
        doc = await db.health_uploads.find_one({"user_id": user_id})
        if not doc:
            return {"status": "not_found", "message": "No Apple Health upload yet."}

        daily = doc.get("daily_recovery_summary") or []
        resolution = resolve_health_budget(daily)

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
            "daily_recovery_summary": daily[:limit],
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
