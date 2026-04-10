"""Signature d'URLs GCS pour le package milpo."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlparse

from milpo.config import GCS_SIGNING_SA_EMAIL

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


def _resolve_media_source(media: dict) -> tuple[str | None, str]:
    """Résout l'URL source d'un média.

    Pour les vidéos, on exige `media_url` afin de ne pas dégrader silencieusement
    le média en simple thumbnail image.
    """
    media_type = media.get("media_type", "IMAGE")
    if media_type == "VIDEO":
        return media.get("media_url"), media_type
    return media.get("media_url") or media.get("thumbnail_url"), media_type


def _prepare_media_entries(media: list[dict]) -> list[tuple[str, str]] | None:
    """Prépare la liste des URLs brutes d'un post.

    Retourne `None` si le post est invalide et doit être entièrement ignoré.
    """
    entries: list[tuple[str, str]] = []

    for m in media:
        raw_url, media_type = _resolve_media_source(m)
        if not raw_url:
            logger.warning(
                "Media ignoré: %s sans URL source exploitable (ig_media_id=%s, media_order=%s)",
                media_type,
                m.get("ig_media_id"),
                m.get("media_order"),
            )
            return None
        entries.append((raw_url, media_type))

    return entries


def _progress_step(total: int, target_updates: int = 20) -> int:
    if total <= 0:
        return 1
    return max(1, total // target_updates)


def sign_media_urls(media: list[dict]) -> list[tuple[str, str]]:
    """Signe les URLs de médias. Retourne [(signed_url, media_type)]."""
    prepared = _prepare_media_entries(media)
    if prepared is None:
        return []

    result: list[tuple[str, str]] = []
    for raw_url, media_type in prepared:
        signed = sign_url(raw_url)
        if signed:
            result.append((signed, media_type))
    return result


def sign_all_posts_media(
    posts: list[dict],
    load_post_media_fn,
    conn,
    max_workers: int = 20,
    load_all_media_fn: Any | None = None,
    on_progress: Any | None = None,
) -> dict[int, list[tuple[str, str]]]:
    """Signe les URLs de tous les posts en parallèle (threads).

    Args:
        load_all_media_fn: callback(conn, ig_media_ids) -> {post_id: [media...]}.
            Permet d'éviter le N+1 SQL quand disponible.
        on_progress: callback(phase, done, total) appelé pour suivre l'avancement.

    Returns:
        {ig_media_id: [(signed_url, media_type), ...]}.
    """
    # 1. Charger tous les médias
    n_posts = len(posts)
    all_media: dict[int, list[dict]]
    if on_progress:
        on_progress("loading_media", 0, n_posts)

    if load_all_media_fn is not None:
        post_ids = [post["ig_media_id"] for post in posts]
        loaded = load_all_media_fn(conn, post_ids)
        all_media = {mid: loaded.get(mid, []) for mid in post_ids}
        if on_progress:
            on_progress("loading_media", n_posts, n_posts)
    else:
        all_media = {}
        progress_step = _progress_step(n_posts)
        for i, post in enumerate(posts):
            mid = post["ig_media_id"]
            all_media[mid] = load_post_media_fn(conn, mid)
            if on_progress and ((i + 1) % progress_step == 0 or i + 1 == n_posts):
                on_progress("loading_media", i + 1, n_posts)

    # 2. Collecter toutes les URLs uniques à signer
    url_to_sign: dict[str, None] = {}  # ordered set
    media_index: list[tuple[int, str, str]] = []  # (ig_media_id, raw_url, media_type)
    expected_media_count: dict[int, int] = {}
    invalid_posts: set[int] = set()

    for mid, media_list in all_media.items():
        prepared = _prepare_media_entries(media_list)
        if prepared is None:
            invalid_posts.add(mid)
            continue
        expected_media_count[mid] = len(prepared)
        for raw_url, media_type in prepared:
            url_to_sign[raw_url] = None
            media_index.append((mid, raw_url, media_type))

    unique_urls = list(url_to_sign.keys())
    n_urls = len(unique_urls)
    n_gcs_urls = sum(1 for url in unique_urls if is_gcs_url(url))
    logger.info(
        "Signature de %d URLs uniques dont %d GCS (%d threads)...",
        n_urls,
        n_gcs_urls,
        max_workers,
    )
    if on_progress:
        on_progress("collecting_urls", n_urls, n_urls)
        on_progress("signing", 0, n_gcs_urls)

    # 3. Signer en parallèle
    # Init credentials avant le pool (pas thread-safe)
    signed_map: dict[str, str] = {url: url for url in unique_urls if not is_gcs_url(url)}
    signed_count = 0
    sign_targets = [url for url in unique_urls if is_gcs_url(url)]
    progress_step = _progress_step(len(sign_targets))

    def _sign_one(url: str) -> tuple[str, str | None]:
        try:
            return url, sign_url(url)
        except Exception:
            logger.exception("Echec signature URL GCS: %s", url)
            return url, None

    if sign_targets:
        _ensure_credentials()
        _get_storage_client()

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_sign_one, url) for url in sign_targets]
            for future in as_completed(futures):
                original, signed = future.result()
                if signed:
                    signed_map[original] = signed
                signed_count += 1
                if on_progress and (
                    signed_count % progress_step == 0 or signed_count == len(sign_targets)
                ):
                    on_progress("signing", signed_count, len(sign_targets))
    elif on_progress:
        on_progress("signing", 0, 0)

    # 4. Assembler les résultats par post
    result: dict[int, list[tuple[str, str]]] = {}
    for mid, raw_url, media_type in media_index:
        if raw_url in signed_map:
            result.setdefault(mid, []).append((signed_map[raw_url], media_type))
        else:
            invalid_posts.add(mid)

    valid_result: dict[int, list[tuple[str, str]]] = {}
    for mid, signed_media in result.items():
        if mid in invalid_posts:
            continue
        if len(signed_media) != expected_media_count.get(mid, 0):
            logger.warning(
                "Post %s ignoré: signature incomplète (%d/%d médias signés)",
                mid,
                len(signed_media),
                expected_media_count.get(mid, 0),
            )
            continue
        valid_result[mid] = signed_media

    if invalid_posts:
        logger.warning("%d posts ignorés pendant la signature des médias", len(invalid_posts))

    return valid_result
