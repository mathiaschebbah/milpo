"""Évaluation HILPO sur le split test.

Usage :
    .venv/bin/python scripts/run_baseline.py
    .venv/bin/python scripts/run_baseline.py --prompts active

Variables d'environnement (chargées depuis .env) :
    OPENROUTER_API_KEY          — clé API OpenRouter
    HILPO_GCS_SIGNING_SA_EMAIL  — service account pour signer les URLs GCS
    HILPO_DATABASE_DSN          — DSN PostgreSQL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass

from hilpo.async_inference import async_classify_batch
from hilpo.db import (
    format_descriptions,
    get_conn,
    get_active_prompt,
    get_prompt_version,
    load_categories,
    load_post_media,
    load_strategies,
    load_visual_formats,
    store_api_call,
    store_prediction,
)
from hilpo.gcs import sign_all_posts_media
from hilpo.inference import PostInput, PromptSet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Silence les logs HTTP de openai/httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger("baseline")


# ── Helpers BDD ────────────────────────────────────────────────


def create_run(conn, config: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO simulation_runs (seed, batch_size, config, status, started_at)
        VALUES (42, 0, %s::jsonb, 'running', NOW())
        RETURNING id
        """,
        (json.dumps(config),),
    ).fetchone()
    conn.commit()
    return row["id"]


def finish_run(conn, run_id: int, metrics: dict):
    conn.execute(
        """
        UPDATE simulation_runs SET
            status = 'completed', finished_at = NOW(),
            final_accuracy_category = %s,
            final_accuracy_visual_format = %s,
            final_accuracy_strategy = %s,
            total_api_calls = %s, total_cost_usd = %s
        WHERE id = %s
        """,
        (
            metrics["accuracy_category"],
            metrics["accuracy_visual_format"],
            metrics["accuracy_strategy"],
            metrics["total_api_calls"],
            metrics.get("total_cost_usd"),
            run_id,
        ),
    )
    conn.commit()


def _load_prompt_record(conn, agent: str, scope: str | None, prompt_mode: str) -> dict:
    """Charge un prompt depuis la BDD selon le mode demandé."""
    if prompt_mode == "active":
        row = get_active_prompt(conn, agent, scope)
    else:
        row = get_prompt_version(conn, agent, scope, version=0)

    if row is None:
        raise RuntimeError(
            f"Prompt introuvable en BDD pour {agent}/{scope or 'all'} (mode={prompt_mode})."
        )
    return row


def load_prompt_bundle(
    conn,
    prompt_mode: str,
) -> tuple[dict[tuple[str, str | None], dict], dict[tuple[str, str | None], int]]:
    """Charge les prompts requis depuis la BDD."""
    prompt_records: dict[tuple[str, str | None], dict] = {}
    prompt_ids: dict[tuple[str, str | None], int] = {}

    for key in (
        ("descriptor", "FEED"),
        ("descriptor", "REELS"),
        ("category", None),
        ("visual_format", "FEED"),
        ("visual_format", "REELS"),
        ("strategy", None),
    ):
        row = _load_prompt_record(conn, key[0], key[1], prompt_mode)
        prompt_records[key] = row
        prompt_ids[key] = row["id"]
        log.info(
            "  prompt chargé : %s/%s -> v%s (%s)",
            key[0],
            key[1] or "all",
            row["version"],
            row.get("status", "n/a"),
        )

    return prompt_records, prompt_ids


def build_prompts(conn, scope: str, prompt_records: dict[tuple[str, str | None], dict]) -> PromptSet:
    vf = load_visual_formats(conn, scope)
    cats = load_categories(conn)
    strats = load_strategies(conn)
    return PromptSet(
        descriptor_instructions=prompt_records[("descriptor", scope)]["content"],
        category_instructions=prompt_records[("category", None)]["content"],
        visual_format_instructions=prompt_records[("visual_format", scope)]["content"],
        strategy_instructions=prompt_records[("strategy", None)]["content"],
        descriptor_descriptions=format_descriptions(vf),
        category_descriptions=format_descriptions(cats),
        visual_format_descriptions=format_descriptions(vf),
        strategy_descriptions=format_descriptions(strats),
    )


def build_labels(conn, scope: str) -> dict[str, list[str]]:
    return {
        "category": [c["name"] for c in load_categories(conn)],
        "visual_format": [f["name"] for f in load_visual_formats(conn, scope)],
        "strategy": [s["name"] for s in load_strategies(conn)],
    }


# ── Stockage résultats ─────────────────────────────────────────


def store_results(conn, results, post_inputs, prompt_ids, run_id):
    """Stocke toutes les prédictions et api_calls en BDD."""
    # Index rapide post → scope
    scope_map = {p.ig_media_id: p.media_product_type for p in post_inputs}

    matches = {"category": 0, "visual_format": 0, "strategy": 0}
    total_api = 0

    for result in results:
        pred = result.prediction
        scope = scope_map[pred.ig_media_id]

        # 3 prédictions classifieurs
        for axis in ("category", "visual_format", "strategy"):
            scope_key = scope if axis == "visual_format" else None
            prompt_id = prompt_ids.get((axis, scope_key)) or prompt_ids.get((axis, None))

            pid = store_prediction(
                conn, pred.ig_media_id, axis, prompt_id,
                getattr(pred, axis),
                raw_response=pred.features.model_dump() if axis == "visual_format" else None,
                simulation_run_id=run_id,
            )

            row = conn.execute("SELECT match FROM predictions WHERE id = %s", (pid,)).fetchone()
            if row and row["match"]:
                matches[axis] += 1

        # Features descripteur
        desc_pid = prompt_ids.get(("descriptor", scope))
        if desc_pid:
            store_prediction(
                conn, pred.ig_media_id, "descriptor", desc_pid,
                "features_extracted",
                raw_response=pred.features.model_dump(),
                simulation_run_id=run_id,
            )

        # API calls
        for call in result.api_calls:
            scope_key = scope if call.agent in ("descriptor", "visual_format") else None
            prompt_id = prompt_ids.get((call.agent, scope_key)) or prompt_ids.get((call.agent, None))

            store_api_call(
                conn,
                call_type="classification",
                agent=call.agent,
                model_name=call.model,
                prompt_version_id=prompt_id,
                ig_media_id=pred.ig_media_id,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cost_usd=None,
                latency_ms=call.latency_ms,
                simulation_run_id=run_id,
            )
            total_api += 1

    return matches, total_api


# ── Main ───────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="Évalue la pipeline HILPO sur le split test")
    parser.add_argument(
        "--prompts",
        choices=("v0", "active"),
        default="v0",
        help="Jeu de prompts à charger depuis la BDD",
    )
    args = parser.parse_args()

    conn = get_conn()
    t0 = time.monotonic()
    run_label = "B0" if args.prompts == "v0" else "BN"
    prompt_label = "v0" if args.prompts == "v0" else "actifs"

    log.info("=" * 55)
    log.info("%s — Évaluation %s sur split test", run_label, prompt_label)
    log.info("=" * 55)

    # 1. Posts test
    raw_posts = conn.execute(
        """
        SELECT p.ig_media_id, p.caption,
               p.media_type::text AS media_type,
               p.media_product_type::text AS media_product_type
        FROM sample_posts sp
        JOIN posts p ON p.ig_media_id = sp.ig_media_id
        WHERE sp.split = 'test'
        ORDER BY sp.presentation_order
        """
    ).fetchall()
    log.info("Posts test : %d", len(raw_posts))

    # 2. Simulation run
    from hilpo.config import MODEL_DESCRIPTOR_FEED, MODEL_DESCRIPTOR_REELS, MODEL_CLASSIFIER
    run_id = create_run(conn, {
        "name": f"{run_label}_{args.prompts}_test",
        "split": "test",
        "prompts": args.prompts,
        "models": {
            "descriptor_feed": MODEL_DESCRIPTOR_FEED,
            "descriptor_reels": MODEL_DESCRIPTOR_REELS,
            "classifier": MODEL_CLASSIFIER,
        },
    })
    log.info("simulation_run id=%d", run_id)

    # 3. Signature URLs GCS (parallèle, 20 threads)
    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(raw_posts, load_post_media, conn, max_workers=20)

    post_inputs: list[PostInput] = []
    skipped = 0
    for post in raw_posts:
        mid = post["ig_media_id"]
        signed = signed_by_post.get(mid, [])
        if not signed:
            skipped += 1
            continue
        post_inputs.append(PostInput(
            ig_media_id=mid,
            media_product_type=post["media_product_type"],
            media_urls=[u for u, _ in signed],
            media_types=[m for _, m in signed],
            caption=post["caption"],
        ))

    feed = sum(1 for p in post_inputs if p.media_product_type == "FEED")
    reels = len(post_inputs) - feed
    log.info("Prêts : %d (FEED %d / REELS %d) — %d skippés", len(post_inputs), feed, reels, skipped)

    # 4. Prompts et labels
    prompt_records, prompt_ids = load_prompt_bundle(conn, args.prompts)
    prompts_by_scope = {}
    labels_by_scope = {}
    for scope in ("FEED", "REELS"):
        prompts_by_scope[scope] = build_prompts(conn, scope, prompt_records)
        labels_by_scope[scope] = build_labels(conn, scope)

    # 5. Classification async
    log.info("Classification en cours...")

    def on_progress(done: int, total: int, errors: int) -> None:
        elapsed = time.monotonic() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        bar = "█" * (done * 30 // total) + "░" * (30 - done * 30 // total)
        print(
            f"\r  {bar} {done:>3}/{total} "
            f"({done*100//total:>2}%) "
            f"| {rate:.1f} posts/s "
            f"| ETA {eta:.0f}s "
            f"| erreurs {errors}",
            end="", flush=True,
        )

    results = await async_classify_batch(
        posts=post_inputs,
        prompts_by_scope=prompts_by_scope,
        labels_by_scope=labels_by_scope,
        max_concurrent_api=20,
        max_concurrent_posts=10,
        on_progress=on_progress,
    )
    errors = len(post_inputs) - len(results)
    print()  # newline après la barre
    log.info("Classifiés : %d / %d (erreurs : %d)", len(results), len(post_inputs), errors)

    # 6. Stockage BDD
    log.info("Stockage en BDD...")
    matches, total_api = store_results(conn, results, post_inputs, prompt_ids, run_id)

    # 7. Métriques
    n = len(results)
    acc = {k: v / n if n else 0 for k, v in matches.items()}

    finish_run(conn, run_id, {
        "accuracy_category": acc["category"],
        "accuracy_visual_format": acc["visual_format"],
        "accuracy_strategy": acc["strategy"],
        "total_api_calls": total_api,
    })

    elapsed = time.monotonic() - t0
    total_in = sum(c.input_tokens for r in results for c in r.api_calls)
    total_out = sum(c.output_tokens for r in results for c in r.api_calls)

    log.info("")
    log.info("=" * 55)
    log.info("RÉSULTATS %s", run_label)
    log.info("=" * 55)
    log.info("  Posts          : %d", n)
    log.info("  Appels API     : %d", total_api)
    log.info("  Tokens         : %s in / %s out", f"{total_in:,}", f"{total_out:,}")
    log.info("  Durée          : %.0fs (%.1f min)", elapsed, elapsed / 60)
    log.info("")
    log.info("  Accuracy catégorie     : %.1f%% (%d/%d)", acc["category"] * 100, matches["category"], n)
    log.info("  Accuracy visual_format : %.1f%% (%d/%d)", acc["visual_format"] * 100, matches["visual_format"], n)
    log.info("  Accuracy stratégie     : %.1f%% (%d/%d)", acc["strategy"] * 100, matches["strategy"], n)
    log.info("")
    log.info("  simulation_run_id = %d", run_id)
    log.info("✓ %s terminé", run_label)

    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
