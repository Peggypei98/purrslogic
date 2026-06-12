"""Orchestrate calendar fetch, energy accounting, and ADK triage with optional progress stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.config.database import db
from app.services.calendar_service import GoogleCalendarService
from app.services.classifier_service import DynamicEventClassifierService
from app.services.guardrail_service import guardrail_service
from app.services.health_budget import budget_meta_dict
from app.services.health_ingest_service import health_ingest_service
from app.services.recovery_service import MicroRecoveryService

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]

_classifier = DynamicEventClassifierService()
_recovery = MicroRecoveryService()


async def _get_calendar_service(user_id: str) -> GoogleCalendarService:
    calendar_service = await GoogleCalendarService.for_user(user_id)
    if calendar_service:
        return calendar_service
    try:
        return GoogleCalendarService()
    except (ValueError, FileNotFoundError) as error:
        raise ValueError(
            "Google Calendar not connected. "
            f"Visit /api/v1/calendar/oauth/start?user_id={user_id} to authorize."
        ) from error


async def _emit(
    progress: ProgressCallback | None,
    stage: str,
    percent: int,
    **extra: Any,
) -> None:
    if progress:
        await progress({"type": "progress", "stage": stage, "percent": percent, **extra})


class CalendarTriageService:
    async def run_triage(
        self,
        user_id: str,
        *,
        simulate_budget: int | None = None,
        bq_service: Any = None,
        brain_service: Any,
        legacy_brain_service: Any,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        await _emit(progress, "profile", 5)

        user_profile = await db.user_profiles.find_one({"user_id": user_id})
        custom_rules = user_profile.get("custom_heuristic_rules", []) if user_profile else []

        await _emit(progress, "calendar", 15)
        calendar_service = await _get_calendar_service(user_id)
        raw_events = calendar_service.get_today_events()
        if isinstance(raw_events, dict):
            raise ValueError(raw_events.get("error", "Failed to fetch calendar events"))

        await _emit(progress, "classify", 30, event_count=len(raw_events))
        classified_events, total_mental_cost, total_physical_cost = _classifier.calculate_and_tag_agenda(
            raw_events=raw_events,
            custom_rules=custom_rules,
        )
        total_agenda_cost = total_mental_cost + total_physical_cost

        await _emit(progress, "budget", 45)
        budget_meta = None
        if simulate_budget is not None:
            today_health_budget = simulate_budget
            budget_meta = {"source": "simulated", "source_date": None, "is_fallback": False}
        else:
            resolution = await health_ingest_service.get_budget_resolution(user_id=user_id)
            if resolution and resolution.budget is not None:
                today_health_budget = resolution.budget
                budget_meta = budget_meta_dict(resolution)
            elif bq_service:
                today_health_budget = bq_service.get_today_health_budget(user_id=user_id)
                budget_meta = {"source": "bigquery", "source_date": None, "is_fallback": True}
            else:
                today_health_budget = 45
                budget_meta = {"source": "default", "source_date": None, "is_fallback": True}

        remaining_energy_net = today_health_budget - total_agenda_cost
        is_overloaded = remaining_energy_net < 0
        recommendations = []
        triage_status = "HEALTHY_BALANCED"

        if is_overloaded:
            triage_status = "ENERGY_OVERLOAD_WARNING"
            recommendations = _recovery.get_top_recommendations(
                needed_charge=abs(remaining_energy_net),
                limit=2,
            )

        await _emit(progress, "guardrails", 55)
        guardrail_service.register_agenda(classified_events)
        deletable_events, protected_events = guardrail_service.partition_events(classified_events)

        payload_for_ai = {
            "user_id": user_id,
            "triage_summary": {
                "status_code": triage_status,
                "is_overloaded_warning": is_overloaded,
                "physiological_budget": today_health_budget,
                "budget_meta": budget_meta,
                "total_agenda_cost_burn": total_agenda_cost,
                "remaining_net_energy": remaining_energy_net,
            },
            "proactive_interventions": recommendations,
            "events": classified_events,
            "safety_guardrails": {
                "policy": "NEVER delete IMMOVABLE events. Runtime blocks unsafe deletes.",
                "deletable_event_ids": [e["event_id"] for e in deletable_events if e.get("event_id")],
                "deletable_events": deletable_events,
                "protected_events": protected_events,
            },
        }

        await _emit(progress, "prefetch", 65)
        await _emit(progress, "agent", 72, detail="ADK + Gemini + MCP")
        brain_response = await brain_service.generate_triage_coaching(triage_data=payload_for_ai)

        if "error" in brain_response:
            await _emit(progress, "fallback", 85, detail="ADK busy — retrying with legacy Gemini")
            print(f"⚠️ [Triage] ADK fallback: {brain_response['error']}")
            brain_response = await legacy_brain_service.generate_triage_coaching(
                triage_data=payload_for_ai
            )

        if "error" in brain_response:
            raise RuntimeError(brain_response["error"])

        await _emit(progress, "complete", 100)

        return {
            "status": "success",
            "user_id": user_id,
            "triage_summary": payload_for_ai["triage_summary"],
            "agent_decision_center": brain_response.get("agent_coaching_text"),
            "proactive_interventions": brain_response.get("automated_actions_executed", []),
            "events": classified_events,
        }

    async def run_triage_stream(
        self,
        user_id: str,
        *,
        simulate_budget: int | None = None,
        bq_service: Any = None,
        brain_service: Any,
        legacy_brain_service: Any,
    ) -> AsyncIterator[str]:
        progress_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_progress(event: dict[str, Any]) -> None:
            await progress_queue.put(event)

        async def worker() -> None:
            try:
                result = await self.run_triage(
                    user_id,
                    simulate_budget=simulate_budget,
                    bq_service=bq_service,
                    brain_service=brain_service,
                    legacy_brain_service=legacy_brain_service,
                    progress=on_progress,
                )
                await progress_queue.put({"type": "done", "result": result})
            except Exception as error:
                await progress_queue.put({"type": "error", "detail": str(error)})
            finally:
                await progress_queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                event = await progress_queue.get()
                if event is None:
                    break
                yield json.dumps(event, default=str) + "\n"
        finally:
            await task


calendar_triage_service = CalendarTriageService()
