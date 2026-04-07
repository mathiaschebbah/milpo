"""Extraction des features descripteur pour les posts dev annotés.

But : générer une fois pour toutes les `DescriptorFeatures` JSON pour tous les
posts du split dev qui ont une annotation humaine, et les cacher dans la table
`predictions` (agent='descriptor', raw_response=features JSON). Cela évite à
DSPy (et à toute autre méthode d'optimisation) de devoir réappeler le
descripteur multimodal à chaque iteration sur le dev split.

Coût attendu : ~$1 sur Gemini 3 Flash Preview pour ~237 posts.
Durée attendue : ~5 minutes en concurrence 10 posts × 20 appels API.

Idempotent : skip les posts qui ont déjà des features cachées dans le run de
feature extraction. Pour forcer une régénération, soit supprimer les rows
correspondantes, soit créer un nouveau run.

Usage :
    .venv/bin/python scripts/extract_features_dev.py
    .venv/bin/python scripts/extract_features_dev.py --limit 10  # smoke test
    .venv/bin/python scripts/extract_features_dev.py --force      # ignore le cache existant

ATTENTION : ce script LANCE des appels au LLM. Ne pas exécuter sans avoir
validé que les annotations dev sont suffisantes et que le budget OpenRouter
est OK. Voir related_work/dspy_baseline/README.md pour le contexte.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time

from milpo.async_inference import async_call_descriptor, get_async_client
from milpo.config import MODEL_DESCRIPTOR_FEED, MODEL_DESCRIPTOR_REELS
from milpo.db import (
    format_descriptions,
    get_active_prompt,
    get_conn,
    load_categories,
    load_post_media,
    load_strategies,
    load_visual_formats,
    store_api_call,
    store_prediction,
)
from milpo.gcs import sign_all_posts_media

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("extract_features_dev")


# ── Identification du run de feature extraction ─────────────────


FEATURE_EXTRACTION_RUN_NAME = "feature_cache_dev"


def get_or_create_extraction_run(conn) -> int:
    """Retourne l'id du run de feature extraction dev (existant ou nouveau).

    On utilise un seul run dédié à la feature extraction du dev pour pouvoir
    retrouver facilement toutes les features avec une simple WHERE clause
    sur simulation_run_id.
    """
    row = conn.execute(
        """
        SELECT id FROM simulation_runs
        WHERE config->>'name' = %s
        ORDER BY id DESC LIMIT 1
        """,
        (FEATURE_EXTRACTION_RUN_NAME,),
    ).fetchone()
    if row is not None:
        log.info("Run feature extraction existant : id=%d", row["id"])
        return row["id"]

    log.info("Création d'un nouveau run feature extraction...")
    row = conn.execute(
        """
        INSERT INTO simulation_runs (seed, batch_size, config, status, started_at)
        VALUES (42, 0, %s::jsonb, 'running', NOW())
        RETURNING id
        """,
        (json.dumps({
            "name": FEATURE_EXTRACTION_RUN_NAME,
            "kind": "feature_extraction",
            "split": "dev",
            "description": (
                "Cache des features descripteur pour les posts dev annotés. "
                "Permet à DSPy et autres méthodes d'optimisation d'éviter de "
                "réappeler le descripteur multimodal à chaque itération."
            ),
        }),),
    ).fetchone()
    conn.commit()
    log.info("  → run_id=%d", row["id"])
    return row["id"]


def finish_extraction_run(conn, run_id: int, n_processed: int, n_skipped: int) -> None:
    conn.execute(
        """
        UPDATE simulation_runs
        SET status = 'completed', finished_at = NOW(),
            config = config || %s::jsonb
        WHERE id = %s
        """,
        (
            json.dumps({
                "n_processed": n_processed,
                "n_skipped_already_cached": n_skipped,
            }),
            run_id,
        ),
    )
    conn.commit()


# ── Chargement des posts à traiter ───────────────────────────────


def load_annotated_dev_posts_without_features(conn, run_id: int, limit: int | None = None, force: bool = False) -> list[dict]:
    """Charge les posts dev annotés qui n'ont pas encore de features cachées.

    Si `force=True`, retourne tous les annotés (re-traite ceux déjà cachés).
    """
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


# ── Chargement des prompts v0 descripteur ────────────────────────


def load_descriptor_prompts(conn) -> dict[str, dict]:
    """Charge les 2 prompts descripteur v0 (FEED + REELS) avec leurs descriptions taxonomiques.

    Format : {scope: {"instructions": ..., "descriptions": ..., "id": ...}}
    """
    out: dict[str, dict] = {}
    for scope in ("FEED", "REELS"):
        record = get_active_prompt(conn, "descriptor", scope, source="human_v0")
        if record is None:
            raise RuntimeError(f"Prompt descripteur v0 introuvable pour scope={scope}")
        vf = load_visual_formats(conn, scope)
        out[scope] = {
            "instructions": record["content"],
            "descriptions": format_descriptions(vf),
            "id": record["id"],
        }
    return out


# ── Boucle d'extraction async ────────────────────────────────────


async def extract_one(
    client,
    semaphore: asyncio.Semaphore,
    post: dict,
    signed_media: list[tuple[str, str]],
    descriptor_prompts: dict[str, dict],
):
    """Extrait les features pour un post. Retourne (post, features, api_log) ou (post, None, None) si échec."""
    scope = post["media_product_type"].upper()
    if scope not in ("FEED", "REELS"):
        log.warning("Post %s : scope %s non supporté, skip", post["ig_media_id"], scope)
        return post, None, None

    config = descriptor_prompts[scope]
    media_urls = [u for u, _ in signed_media]
    media_types = [m for _, m in signed_media]
    model = MODEL_DESCRIPTOR_FEED if scope == "FEED" else MODEL_DESCRIPTOR_REELS

    try:
        features, api_log = await async_call_descriptor(
            client=client,
            model=model,
            media_urls=media_urls,
            media_types=media_types,
            caption=post["caption"],
            instructions=config["instructions"],
            descriptions_taxonomiques=config["descriptions"],
            semaphore=semaphore,
        )
        return post, features, api_log
    except Exception as exc:
        log.error("Post %s : échec extraction features (%s)", post["ig_media_id"], exc)
        return post, None, None


async def main():
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
    args = parser.parse_args()

    conn = get_conn()
    t0 = time.monotonic()

    log.info("=" * 55)
    log.info("Extraction features descripteur — split dev")
    log.info("=" * 55)

    # 1. Run d'extraction (réutilisé si existant, créé sinon)
    run_id = get_or_create_extraction_run(conn)

    # 2. Posts à traiter
    posts = load_annotated_dev_posts_without_features(
        conn, run_id, limit=args.limit, force=args.force,
    )
    log.info("Posts à traiter : %d (mode %s)", len(posts), "FORCE" if args.force else "incrémental")

    if not posts:
        log.info("Rien à faire — tous les posts annotés ont déjà des features cachées.")
        finish_extraction_run(conn, run_id, n_processed=0, n_skipped=0)
        conn.close()
        return

    # 3. Signature URLs GCS
    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(posts, load_post_media, conn, max_workers=20)

    # 4. Chargement des prompts descripteur v0
    descriptor_prompts = load_descriptor_prompts(conn)

    # 5. Boucle async d'extraction
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
                raw_response=features.model_dump(),
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
                n_done, len(tasks), n_ok, n_failed, rate, eta,
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


if __name__ == "__main__":
    asyncio.run(main())
