"""Signature d'URLs GCS pour le package hilpo (sync)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlparse

from hilpo.config import GCS_SIGNING_SA_EMAIL

logger = logging.getLogger(__name__)

GCS_HOST = "storage.googleapis.com"

_credentials: Any = None
_auth_request: Any = None
_storage_client: Any = None


def is_gcs_url(url: str | None) -> bool:
    return bool(url) and GCS_HOST in url


def _parse_gcs_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    bucket, _, blob = path.partition("/")
    return bucket, blob


def _ensure_credentials() -> Any:
    global _credentials, _auth_request
    if _credentials is None:
        import google.auth
        import google.auth.transport.requests
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        _auth_request = google.auth.transport.requests.Request()
    if _credentials.expired or not _credentials.token:
        cast(Any, _credentials).refresh(_auth_request)
    return _credentials


def _get_storage_client() -> Any:
    global _storage_client
    if _storage_client is None:
        from google.cloud import storage
        creds = _ensure_credentials()
        _storage_client = storage.Client(credentials=creds)
    return _storage_client


def sign_url(url: str | None, expiration_minutes: int = 60) -> str | None:
    """Signe une URL GCS. Retourne l'URL originale si pas GCS."""
    if not url or not is_gcs_url(url):
        return url

    bucket_name, blob_path = _parse_gcs_url(url)
    client = _get_storage_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    creds = _ensure_credentials()

    sign_kwargs: dict[str, object] = {
        "version": "v4",
        "expiration": timedelta(minutes=expiration_minutes),
        "method": "GET",
    }

    sa_email = getattr(creds, "service_account_email", None) or GCS_SIGNING_SA_EMAIL
    if sa_email and creds.token:
        sign_kwargs["service_account_email"] = sa_email
        sign_kwargs["access_token"] = creds.token

    return cast(str, blob.generate_signed_url(**sign_kwargs))


def sign_media_urls(media: list[dict]) -> list[tuple[str, str]]:
    """Signe les URLs de médias. Retourne [(signed_url, media_type)]."""
    result = []
    for m in media:
        raw_url = m.get("media_url") or m.get("thumbnail_url")
        media_type = m.get("media_type", "IMAGE")
        signed = sign_url(raw_url)
        if signed:
            result.append((signed, media_type))
    return result
