import datetime
import json
from pathlib import Path
from typing import Any, Protocol, cast

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.services.google_oauth_service import google_oauth_service


class _CalendarEventsResource(Protocol):
    def list(self, **kwargs: Any) -> Any: ...


class _CalendarResource(Protocol):
    def events(self) -> _CalendarEventsResource: ...


class GoogleCalendarService:
    service: _CalendarResource

    SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

    def __init__(self, creds: Credentials | None = None, *, allow_legacy_fallback: bool = True):
        self.config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        self.secret_path = self.config_dir / "calendar-client-secret.json"
        self.token_path = self.config_dir / "token.json"
        self.creds = creds

        if self.creds is None and allow_legacy_fallback:
            self.creds = self._load_legacy_credentials()

        if self.creds is None:
            raise ValueError("Google Calendar credentials not available for this user.")

        self.service = cast(_CalendarResource, build("calendar", "v3", credentials=self.creds))

    def _load_legacy_credentials(self) -> Credentials | None:
        """Dev fallback: single-user token.json (optional; prefer per-user OAuth)."""
        if not self.token_path.exists():
            return None

        creds = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as error:
                    print(
                        f"⚠️ [Calendar] Legacy token.json expired or revoked — "
                        f"ignoring dev fallback ({error}). Use per-user OAuth via /health."
                    )
                    return None
            else:
                print(
                    "⚠️ [Calendar] Legacy token.json invalid — "
                    "connect Google Calendar via /health instead."
                )
                return None
            with open(self.token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        return creds

    @classmethod
    async def for_user(cls, user_id: str) -> "GoogleCalendarService | None":
        creds = await google_oauth_service.get_credentials(user_id)
        if creds:
            return cls(creds=creds, allow_legacy_fallback=False)
        return None

    def _events(self) -> _CalendarEventsResource:
        calendar: _CalendarResource = cast(_CalendarResource, self.service)
        return calendar.events()

    def get_today_events(self) -> list[dict[str, str | None]] | dict[str, str]:
        local_now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        start_of_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_of_today = local_now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        try:
            events_result = self._events().list(
                calendarId="primary",
                timeMin=start_of_today,
                timeMax=end_of_today,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = events_result.get("items", [])
            cleaned_events = []
            for event in events:
                start_time = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
                end_time = event.get("end", {}).get("dateTime", event.get("end", {}).get("date"))
                cleaned_events.append({
                    "event_id": event.get("id"),
                    "summary": event.get("summary", "Untitled Meeting"),
                    "start": start_time,
                    "end": end_time,
                    "description": event.get("description", ""),
                })
            return cleaned_events

        except Exception as error:
            print(f"Error fetching calendar events: {error}")
            return {"error": str(error)}

    def get_historical_events(self, months_back: int = 3) -> list[str] | dict[str, str]:
        local_now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        start_time = (
            local_now - datetime.timedelta(days=30 * months_back)
        ).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_time = local_now.isoformat()

        try:
            print(
                f"⏳ [Purrslogic Historical Mining] Fetching historical calendar events "
                f"for the last {months_back} months..."
            )
            events_result = self._events().list(
                calendarId="primary",
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy="startTime",
                maxResults=500,
            ).execute()

            unique_titles = set()
            for event in events_result.get("items", []):
                summary = event.get("summary")
                if summary:
                    unique_titles.add(summary.strip())
            return sorted(list(unique_titles))

        except Exception as error:
            print(f"❌ Historical event fetching failed: {error}")
            return {"error": str(error)}

    def delete_calendar_event(self, event_id: str) -> dict:
        try:
            print(f"🔥 [Google Calendar API] Agent action triggered: Successfully DELETED event ID: {event_id}")
            return {"status": "success", "action": "delete", "event_id": event_id}
        except Exception as error:
            print(f"❌ Failed to delete event {event_id}: {error}")
            return {"status": "error", "message": str(error)}

    def insert_calendar_event(
        self,
        summary: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
    ) -> dict:
        try:
            print(f"✨ [Google Calendar API] Agent action triggered: Successfully INSERTED '{summary}'")
            return {"status": "success", "action": "insert", "summary": summary}
        except Exception as error:
            print(f"❌ Failed to insert event {summary}: {error}")
            return {"status": "error", "message": str(error)}
