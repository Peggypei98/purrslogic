"""Signed GCS uploads for large Apple Health exports (Cloud Run HTTP limit ~32 MiB)."""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath

import google.auth
from google.auth import compute_engine
from google.auth.transport import requests as google_auth_requests
from google.cloud import storage

DEFAULT_BUCKET = "purrslogic-health-uploads"
UPLOAD_PREFIX = "uploads"
SIGNED_URL_TTL = timedelta(minutes=30)


class GcsUploadService:
    def __init__(self) -> None:
        self.bucket_name = os.getenv("GCS_UPLOAD_BUCKET", DEFAULT_BUCKET)

    def _client(self) -> storage.Client:
        return storage.Client()

    def _object_name(self, user_id: str, filename: str) -> str:
        safe_user = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in user_id)
        safe_name = PurePosixPath(filename or "export.zip").name
        token = uuid.uuid4().hex
        return f"{UPLOAD_PREFIX}/{safe_user}/{token}/{safe_name}"

    def create_signed_upload_url(
        self,
        user_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, str | int]:
        if not self.bucket_name:
            raise RuntimeError("GCS_UPLOAD_BUCKET is not configured.")

        object_name = self._object_name(user_id, filename)
        credentials, _project = google.auth.default()
        if not credentials.valid:
            credentials.refresh(google_auth_requests.Request())

        client = self._client()
        blob = client.bucket(self.bucket_name).blob(object_name)

        sign_kwargs: dict = {
            "version": "v4",
            "expiration": SIGNED_URL_TTL,
            "method": "PUT",
            "content_type": content_type,
        }
        if isinstance(credentials, compute_engine.Credentials):
            sign_kwargs["service_account_email"] = credentials.service_account_email
            sign_kwargs["access_token"] = credentials.token

        upload_url = blob.generate_signed_url(**sign_kwargs)
        return {
            "upload_url": upload_url,
            "object_name": object_name,
            "bucket": self.bucket_name,
            "content_type": content_type,
            "expires_in_seconds": int(SIGNED_URL_TTL.total_seconds()),
        }

    def download_object(self, object_name: str) -> bytes:
        blob = self._client().bucket(self.bucket_name).blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"Upload object not found: {object_name}")
        return blob.download_as_bytes()

    def download_object_to_file(self, object_name: str, dest_path: Path) -> None:
        blob = self._client().bucket(self.bucket_name).blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"Upload object not found: {object_name}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest_path))

    def delete_object(self, object_name: str) -> None:
        blob = self._client().bucket(self.bucket_name).blob(object_name)
        if blob.exists():
            blob.delete()

    def validate_object_for_user(self, object_name: str, user_id: str) -> None:
        safe_user = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in user_id)
        expected_prefix = f"{UPLOAD_PREFIX}/{safe_user}/"
        if not object_name.startswith(expected_prefix):
            raise PermissionError("Upload object does not belong to this user.")


gcs_upload_service = GcsUploadService()
