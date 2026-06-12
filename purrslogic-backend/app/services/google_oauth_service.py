"""Google Calendar OAuth — per-user tokens in MongoDB."""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config.database import db

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
SECRET_PATH = CONFIG_DIR / "calendar-client-secret.json"
REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    "http://127.0.0.1:8000/api/v1/calendar/oauth/callback",
)
PENDING_TTL = timedelta(minutes=15)


def _utc_aware(value: datetime) -> datetime:
    """MongoDB may return naive datetimes even when stored as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class GoogleOAuthService:
    def _materialize_secret_from_env(self) -> None:
        """Cloud Run: inject OAuth client JSON via GOOGLE_OAUTH_CLIENT_JSON secret."""
        raw = os.getenv("GOOGLE_OAUTH_CLIENT_JSON")
        if not raw or SECRET_PATH.exists():
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SECRET_PATH.write_text(raw, encoding="utf-8")

    def _require_secret(self) -> Path:
        self._materialize_secret_from_env()
        if not SECRET_PATH.exists():
            raise FileNotFoundError(
                f"Google OAuth client secret not found at {SECRET_PATH}. "
                "Set GOOGLE_OAUTH_CLIENT_JSON (Cloud Run) or mount calendar-client-secret.json."
            )
        return SECRET_PATH

    def create_flow(self) -> Flow:
        return Flow.from_client_secrets_file(
            str(self._require_secret()),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
        )

    async def _save_pending_verifier(self, user_id: str, code_verifier: str) -> None:
        await db.google_oauth_pending.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "code_verifier": code_verifier,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    async def _load_pending_verifier(self, user_id: str) -> str | None:
        doc = await db.google_oauth_pending.find_one({"user_id": user_id})
        if not doc or not doc.get("code_verifier"):
            return None

        created_at = doc.get("created_at")
        if created_at and datetime.now(timezone.utc) - _utc_aware(created_at) > PENDING_TTL:
            await db.google_oauth_pending.delete_one({"user_id": user_id})
            return None
        return doc["code_verifier"]

    async def _clear_pending_verifier(self, user_id: str) -> None:
        await db.google_oauth_pending.delete_one({"user_id": user_id})

    async def authorization_url(self, user_id: str) -> str:
        flow = self.create_flow()
        url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=user_id,
        )
        if not flow.code_verifier:
            raise ValueError("OAuth PKCE code_verifier was not generated.")
        await self._save_pending_verifier(user_id, flow.code_verifier)
        return url

    async def exchange_code(self, code: str, user_id: str) -> dict:
        code_verifier = await self._load_pending_verifier(user_id)
        if not code_verifier:
            raise ValueError(
                "OAuth session expired or missing. Click Connect Google Calendar again."
            )

        flow = self.create_flow()
        flow.code_verifier = code_verifier
        try:
            flow.fetch_token(code=code)
        finally:
            await self._clear_pending_verifier(user_id)

        creds = flow.credentials
        return await self.save_credentials(user_id, creds)

    async def save_credentials(self, user_id: str, creds: Credentials) -> dict:
        doc = {
            "user_id": user_id,
            "token_json": creds.to_json(),
            "scopes": list(creds.scopes or SCOPES),
            "connected_at": datetime.now(timezone.utc),
        }
        await db.google_calendar_tokens.update_one(
            {"user_id": user_id},
            {"$set": doc},
            upsert=True,
        )
        return {"status": "connected", "user_id": user_id}

    async def get_credentials(self, user_id: str) -> Credentials | None:
        doc = await db.google_calendar_tokens.find_one({"user_id": user_id})
        if not doc or not doc.get("token_json"):
            return None

        creds = Credentials.from_authorized_user_info(
            json.loads(doc["token_json"]),
            SCOPES,
        )
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                await db.google_calendar_tokens.delete_one({"user_id": user_id})
                return None
            await self.save_credentials(user_id, creds)
        if not creds.valid:
            return None
        return creds

    async def get_status(self, user_id: str) -> dict:
        creds = await self.get_credentials(user_id)
        if creds:
            doc = await db.google_calendar_tokens.find_one({"user_id": user_id})
            return {
                "status": "connected",
                "user_id": user_id,
                "connected_at": doc.get("connected_at") if doc else None,
                "scopes": list(creds.scopes or SCOPES),
            }

        # Stale row in MongoDB — token expired/revoked; treat as disconnected.
        await db.google_calendar_tokens.delete_one({"user_id": user_id})
        return {
            "status": "disconnected",
            "user_id": user_id,
            "connect_url": f"/api/v1/calendar/oauth/start?user_id={user_id}",
        }

    async def disconnect(self, user_id: str) -> dict:
        await db.google_calendar_tokens.delete_one({"user_id": user_id})
        return {"status": "disconnected", "user_id": user_id}


google_oauth_service = GoogleOAuthService()
