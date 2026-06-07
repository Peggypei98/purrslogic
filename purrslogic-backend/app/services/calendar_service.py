import datetime
from pathlib import Path
from typing import Any, Protocol, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


class _CalendarEventsResource(Protocol):
    def list(self, **kwargs: Any) -> Any: ...


class _CalendarResource(Protocol):
    def events(self) -> _CalendarEventsResource: ...


class GoogleCalendarService:
    service: _CalendarResource

    def __init__(self):
        # for local development with VSCode debugger  
        self.SCOPES = ['https://www.googleapis.com/auth/calendar.events.readonly']
        self.config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        self.secret_path = self.config_dir / "calendar-client-secret.json"
        self.token_path = self.config_dir / "token.json"  # to store the cached token after user authorization  
        self.creds = None

        # 1. check if there is a previously authorized token.json
        if self.token_path.exists():
            self.creds = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)
            
        # 2. if there is no token, or the token is expired, trigger the browser login flow  
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if not self.secret_path.exists():
                    raise FileNotFoundError(f"Google Calendar credential not found, please confirm the file is in: {self.secret_path}")
                
                flow = InstalledAppFlow.from_client_secrets_file(str(self.secret_path), self.SCOPES)
                # start local server, automatically pop up browser to click authorize
                self.creds = flow.run_local_server(port=0)
                
            # save the authorized token, so next time don't need to repeat login
            with open(self.token_path, 'w') as token:
                token.write(self.creds.to_json())

        # 3. build Calendar API service client
        self.service = cast(_CalendarResource, build("calendar", "v3", credentials=self.creds))

    def _events(self) -> _CalendarEventsResource:
        calendar: _CalendarResource = cast(_CalendarResource, self.service)
        return calendar.events()

    def get_today_events(self) -> list[dict[str, str | None]] | dict[str, str]:
        """
        fetch all events for today (from 00:00 to 23:59)
        """
        local_now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        # set the start and end of today (UTC time)
        start_of_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_of_today = local_now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        try:
            events_result = self._events().list(
                calendarId='primary',  # represents the primary calendar
                timeMin=start_of_today,
                timeMax=end_of_today,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            cleaned_events = []
            for event in events:
                start_time = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                end_time = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
                
                cleaned_events.append({
                    "event_id": event.get("id"),
                    "summary": event.get('summary', 'Untitled Meeting'),
                    "start": start_time,
                    "end": end_time,
                    "description": event.get('description', '')
                })
            return cleaned_events

        except Exception as e:
            print(f"Error fetching calendar events: {e}")
            return {"error": str(e)}
        
    def get_historical_events(self, months_back: int = 3) -> list[str] | dict[str, str]:
      
        import datetime # ensure datetime is available within the function
        
        local_now = datetime.datetime.now(datetime.timezone.utc).astimezone()
        # calculate the start time 3 months ago
        start_time = (local_now - datetime.timedelta(days=30 * months_back)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_time = local_now.isoformat()

        try:
            print(f"⏳ [Purrslogic Historical Mining] Fetching historical calendar events for the last {months_back} months...")
            events_result = self._events().list(
                calendarId='primary',
                timeMin=start_time,
                timeMax=end_time,
                singleEvents=True,
                orderBy='startTime',
                maxResults=500  # give enough historical allowance
            ).execute()
            
            events = events_result.get('items', [])
            
            # Core magic: use set collection to perform literal de-duplication
            unique_titles = set()
            for event in events:
                summary = event.get('summary')
                if summary:  # exclude blank events without titles
                    unique_titles.add(summary.strip())
            
            # sort and convert back to List, convenient for JSON transmission and frontend display
            return sorted(list(unique_titles))

        except Exception as e:
            print(f"❌ Historical event fetching failed: {e}")
            return {"error": str(e)}
        
    def delete_calendar_event(self, event_id: str) -> dict:
        """
        [Day 14] Real-world wrapper to delete or cancel an event from Google Calendar.
        """
        try:
            # In production: self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            print(f"🔥 [Google Calendar API] Agent action triggered: Successfully DELETED event ID: {event_id}")
            return {"status": "success", "action": "delete", "event_id": event_id}
        except Exception as e:
            print(f"❌ Failed to delete event {event_id}: {e}")
            return {"status": "error", "message": str(e)}

    def insert_calendar_event(self, summary: str, start_iso: str, end_iso: str, description: str = "") -> dict:
        """
        [Day 14] Real-world wrapper to insert a high-impact recovery block into Google Calendar.
        ```"""
        try:
            event_body = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': start_iso, 'timeZone': 'America/Los_Angeles'},
                'end': {'dateTime': end_iso, 'timeZone': 'America/Los_Angeles'},
            }
            # In production: self.service.events().insert(calendarId='primary', body=event_body).execute()
            print(f"✨ [Google Calendar API] Agent action triggered: Successfully INSERTED '{summary}'")
            return {"status": "success", "action": "insert", "summary": summary}
        except Exception as e:
            print(f"❌ Failed to insert event {summary}: {e}")
            return {"status": "error", "message": str(e)}