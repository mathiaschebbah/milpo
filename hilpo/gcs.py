"""Signature d'URLs GCS pour le package hilpo."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
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


def sign_all_posts_media(
    posts: list[dict],
    load_post_media_fn,
    conn,
    max_workers: int = 20,
) -> dict[int, list[tuple[str, str]]]:
    """Signe les URLs de tous les posts en parallèle (threads).

    Returns:
        {ig_media_id: [(signed_url, media_type), ...]}.
    """
    # 1. Charger tous les médias
    all_media: dict[int, list[dict]] = {}
    for post in posts:
        mid = post["ig_media_id"]
        all_media[mid] = load_post_media_fn(conn, mid)

    # 2. Collecter toutes les URLs uniques à signer
    url_to_sign: dict[str, None] = {}  # ordered set
    media_index: list[tuple[int, str, str]] = []  # (ig_media_id, raw_url, media_type)

    for mid, media_list in all_media.items():
        for m in media_list:
            raw_url = m.get("media_url") or m.get("thumbnail_url")
            media_type = m.get("media_type", "IMAGE")
            if raw_url:
                url_to_sign[raw_url] = None
                media_index.append((mid, raw_url, media_type))

    unique_urls = list(url_to_sign.keys())
    logger.info("Signature de %d URLs uniques (%d threads)...", len(unique_urls), max_workers)

    # 3. Signer en parallèle
    # Init credentials avant le pool (pas thread-safe)
    _ensure_credentials()
    _get_storage_client()

    signed_map: dict[str, str] = {}

    def _sign_one(url: str) -> tuple[str, str | None]:
        return url, sign_url(url)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for original, signed in pool.map(lambda u: _sign_one(u), unique_urls):
            if signed:
                signed_map[original] = signed

    # 4. Assembler les résultats par post
    result: dict[int, list[tuple[str, str]]] = {}
    for mid, raw_url, media_type in media_index:
        if raw_url in signed_map:
            result.setdefault(mid, []).append((signed_map[raw_url], media_type))

    return result
