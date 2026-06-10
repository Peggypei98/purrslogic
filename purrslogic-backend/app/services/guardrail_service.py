"""
Safety guardrails — block agent calendar deletes on IMMOVABLE events.
"""

from typing import Any

PROTECTED_PRIORITIES = frozenset({"IMMOVABLE"})


class SafetyGuardrailService:
    """Validates calendar mutations against the 5D energy matrix priority."""

    def __init__(self) -> None:
        self._events_by_id: dict[str, dict[str, Any]] = {}

    def register_agenda(self, classified_events: list[dict[str, Any]]) -> None:
        """Load today's classified events before an agent run."""
        self._events_by_id = {
            event["event_id"]: event
            for event in classified_events
            if event.get("event_id")
        }

    def clear(self) -> None:
        self._events_by_id = {}

    def _priority(self, event: dict[str, Any]) -> str:
        return event.get("energy_matrix", {}).get("priority", "FLEXIBLE")

    def partition_events(
        self,
        classified_events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split agenda into deletable vs protected (IMMOVABLE) events."""
        deletable: list[dict[str, Any]] = []
        protected: list[dict[str, Any]] = []

        for event in classified_events:
            entry = {
                "event_id": event.get("event_id"),
                "summary": event.get("summary"),
                "priority": self._priority(event),
                "start": event.get("start"),
            }
            if self._priority(event) in PROTECTED_PRIORITIES:
                protected.append(entry)
            else:
                deletable.append(entry)

        return deletable, protected

    def validate_delete(self, event_id: str) -> tuple[bool, str]:
        event = self._events_by_id.get(event_id)
        if not event:
            return False, (
                f"Unknown event_id '{event_id}'. Delete blocked — event not in today's verified agenda."
            )

        priority = self._priority(event)
        summary = event.get("summary", "Untitled")

        if priority in PROTECTED_PRIORITIES:
            return False, (
                f"SAFETY GUARDRAIL: Cannot delete IMMOVABLE event '{summary}' "
                f"(event_id={event_id}). Interviews and critical commitments are protected."
            )

        return True, ""

    def guarded_delete_calendar_event(self, event_id: str) -> dict[str, Any]:
        """Delete only if guardrail allows; otherwise return blocked status for Phoenix audit."""
        allowed, reason = self.validate_delete(event_id)

        if not allowed:
            print(f"🛡️ [Safety Guardrail] BLOCKED delete_calendar_event: {reason}")
            return {
                "status": "blocked",
                "action": "delete",
                "event_id": event_id,
                "reason": reason,
                "guardrail": "IMMOVABLE_PROTECTION",
                "phoenix_audit": "unsafe_delete_prevented",
            }

        from app.services.calendar_service import GoogleCalendarService

        result = GoogleCalendarService().delete_calendar_event(event_id=event_id)
        result["guardrail"] = "passed"
        return result


guardrail_service = SafetyGuardrailService()
