"""Workflow d'extraction des features descripteur pour le split dev."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from milpo.async_inference import async_call_descriptor, get_async_client
from milpo.config import MODEL_DESCRIPTOR_FEED, MODEL_DESCRIPTOR_REELS
from milpo.db import get_conn, load_post_media, load_posts_media, store_api_call, store_prediction
from milpo.gcs import sign_all_posts_media
from milpo.persistence import finish_extraction_run, get_or_create_extraction_run
from milpo.prompting import load_descriptor_prompt_configs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("extract_features_dev")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extrait les features descripteur pour les posts dev annotés et "
            "les cache en BDD pour réutilisation par DSPy/MILPO."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre de posts traités (smoke test).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore le cache existant et re-traite tous les posts annotés.",
    )
    parser.add_argument(
        "--max-concurrent-api",
        type=int,
        default=20,
        help="Nombre max d'appels API simultanés (default: 20).",
    )
    return parser


def load_annotated_dev_posts_without_features(
    conn,
    run_id: int,
    limit: int | None = None,
    force: bool = False,
) -> list[dict]:
    """Charge les posts dev annotés qui n'ont pas encore de features cachées."""
    if force:
        query = """
            SELECT p.ig_media_id, p.caption,
                   p.media_type::text AS media_type,
                   p.media_product_type::text AS media_product_type
            FROM sample_posts sp
            JOIN posts p ON p.ig_media_id = sp.ig_media_id
            JOIN annotations a ON a.ig_media_id = p.ig_media_id
            WHERE sp.split = 'dev'
            ORDER BY sp.presentation_order
        """
        params: tuple = ()
    else:
        query = """
            SELECT p.ig_media_id, p.caption,
                   p.media_type::text AS media_type,
                   p.media_product_type::text AS media_product_type
            FROM sample_posts sp
            JOIN posts p ON p.ig_media_id = sp.ig_media_id
            JOIN annotations a ON a.ig_media_id = p.ig_media_id
            WHERE sp.split = 'dev'
              AND NOT EXISTS (
                  SELECT 1 FROM predictions pr
                  WHERE pr.ig_media_id = p.ig_media_id
                    AND pr.agent = 'descriptor'
                    AND pr.simulation_run_id = %s
              )
            ORDER BY sp.presentation_order
        """
        params = (run_id,)

    if limit:
        query += " LIMIT %s"
        params = (*params, limit)

    return conn.execute(query, params).fetchall()


async def extract_one(
    client,
    semaphore: asyncio.Semaphore,
    post: dict,
    signed_media: list[tuple[str, str]],
    descriptor_prompts: dict[str, dict],
):
    """Extrait les features pour un post. Retourne (post, features, api_log) ou échec."""
    scope = post["media_product_type"].upper()
    if scope not in ("FEED", "REELS"):
        log.warning("Post %s : scope %s non supporté, skip", post["ig_media_id"], scope)
        return post, None, None

    config = descriptor_prompts[scope]
    model = MODEL_DESCRIPTOR_FEED if scope == "FEED" else MODEL_DESCRIPTOR_REELS
    try:
        features, api_log = await async_call_descriptor(
            client=client,
            model=model,
            scope=scope,
            media_urls=[url for url, _ in signed_media],
            media_types=[media_type for _, media_type in signed_media],
            caption=post["caption"],
            instructions=config["instructions"],
            descriptions_taxonomiques=config["descriptions"],
            semaphore=semaphore,
        )
        return post, features, api_log
    except Exception as exc:
        log.error("Post %s : échec extraction features (%s)", post["ig_media_id"], exc)
        return post, None, None


async def run_feature_cache(args) -> int:
    conn = get_conn()
    t0 = time.monotonic()

    log.info("=" * 55)
    log.info("Extraction features descripteur — split dev")
    log.info("=" * 55)

    run_id = get_or_create_extraction_run(conn)
    posts = load_annotated_dev_posts_without_features(conn, run_id, limit=args.limit, force=args.force)
    log.info("Posts à traiter : %d (mode %s)", len(posts), "FORCE" if args.force else "incrémental")

    if not posts:
        log.info("Rien à faire — tous les posts annotés ont déjà des features cachées.")
        finish_extraction_run(conn, run_id, n_processed=0, n_skipped=0)
        conn.close()
        return run_id

    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(
        posts,
        load_post_media,
        conn,
        max_workers=20,
        load_all_media_fn=load_posts_media,
    )
    descriptor_prompts = load_descriptor_prompt_configs(conn, source="human_v0")

    log.info("Extraction en cours (concurrence API=%d)...", args.max_concurrent_api)
    client = get_async_client()
    semaphore = asyncio.Semaphore(args.max_concurrent_api)
    tasks = []
    for post in posts:
        signed = signed_by_post.get(post["ig_media_id"], [])
        if not signed:
            log.warning("Post %s : pas de média signé, skip", post["ig_media_id"])
            continue
        tasks.append(extract_one(client, semaphore, post, signed, descriptor_prompts))

    n_done = 0
    n_ok = 0
    n_failed = 0

    for coro in asyncio.as_completed(tasks):
        post, features, api_log = await coro
        n_done += 1

        if features is None:
            n_failed += 1
        else:
            n_ok += 1
            scope = post["media_product_type"].upper()
            descriptor_prompt_id = descriptor_prompts[scope]["id"]
            store_prediction(
                conn,
                ig_media_id=post["ig_media_id"],
                agent="descriptor",
                prompt_version_id=descriptor_prompt_id,
                predicted_value="features_extracted",
                raw_response={"text": features},
                simulation_run_id=run_id,
            )
            store_api_call(
                conn,
                call_type="classification",
                agent="descriptor",
                model_name=api_log.model,
                prompt_version_id=descriptor_prompt_id,
                ig_media_id=post["ig_media_id"],
                input_tokens=api_log.input_tokens,
                output_tokens=api_log.output_tokens,
                cost_usd=None,
                latency_ms=api_log.latency_ms,
                simulation_run_id=run_id,
            )

        if n_done % 10 == 0 or n_done == len(tasks):
            elapsed = time.monotonic() - t0
            rate = n_done / elapsed if elapsed > 0 else 0
            eta = (len(tasks) - n_done) / rate if rate > 0 else 0
            log.info(
                "  %d/%d (%d ok, %d échec) — %.1f posts/s — ETA %.0fs",
                n_done,
                len(tasks),
                n_ok,
                n_failed,
                rate,
                eta,
            )

    finish_extraction_run(conn, run_id, n_processed=n_ok, n_skipped=0)
    elapsed = time.monotonic() - t0
    log.info("")
    log.info("=" * 55)
    log.info("RÉSULTATS extraction features dev")
    log.info("=" * 55)
    log.info("  Posts traités    : %d", n_ok)
    log.info("  Posts en échec   : %d", n_failed)
    log.info("  Durée            : %.0fs (%.1f min)", elapsed, elapsed / 60)
    log.info("  simulation_run_id = %d", run_id)
    log.info("✓ Extraction features dev terminée")

    conn.close()
    return run_id


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    return asyncio.run(run_feature_cache(args))


__all__ = [
    "build_parser",
    "extract_one",
    "load_annotated_dev_posts_without_features",
    "main",
    "run_feature_cache",
]
