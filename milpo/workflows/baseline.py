"""Workflow d'évaluation MILPO sur le split test."""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from milpo.async_inference import async_classify_batch
from milpo.db import get_conn, load_post_media, load_posts_media
from milpo.gcs import sign_all_posts_media
from milpo.inference import PostInput
from milpo.persistence import create_run, finish_run, store_results
from milpo.prompting import (
    build_labels,
    build_prompt_set,
    load_prompt_bundle,
    prompt_contents_from_records,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("baseline")

RUN_LABELS = {
    "v0": ("B0", "v0 humain"),
    "active": ("BN", "actifs MILPO"),
    "dspy_constrained": ("B_dspy_in_milpo_constrained", "DSPy MIPROv2 contraint"),
    "dspy_free": ("B_dspy_in_milpo_free", "DSPy MIPROv2 libre"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Évalue la pipeline MILPO sur un split annoté")
    parser.add_argument(
        "--prompts",
        choices=tuple(RUN_LABELS.keys()),
        default="v0",
        help=(
            "Jeu de prompts à charger depuis la BDD. "
            "v0=humains seedés, active=actifs MILPO, "
            "dspy_constrained/dspy_free=issus de related_work/dspy_baseline."
        ),
    )
    parser.add_argument(
        "--split",
        choices=("test", "dev"),
        default="test",
        help="Split à évaluer (sample_posts.split). Défaut: test.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help=(
            "Filtre posts publiés à partir de cette date (YYYY-MM-DD). "
            "Ex: --since 2024-01-01 pour évaluer uniquement la prod."
        ),
    )
    parser.add_argument(
        "--eval-set",
        type=str,
        default=None,
        help="Nom du set d'évaluation (table eval_sets). Remplace --split.",
    )
    parser.add_argument(
        "--e2e",
        action="store_true",
        help=(
            "Mode end-to-end : un seul appel multimodal par post (images + caption → 3 axes). "
            "Utilise le modèle MILPO_MODEL_CLASSIFIER_VISUAL_FORMAT."
        ),
    )
    parser.add_argument(
        "--e2e-harness",
        action="store_true",
        help=(
            "Mode E2E + harness : k=3 appels à T=0.3, vote majoritaire, "
            "oracle Sonnet 4.6 sur vf medium/low confidence."
        ),
    )
    return parser


async def run_baseline(args) -> int:
    conn = get_conn()
    t0 = time.monotonic()
    run_label, prompt_label = RUN_LABELS[args.prompts]

    suffix = args.eval_set or args.split
    if args.since:
        suffix = f"{suffix}_since_{args.since}"
    log.info("=" * 55)
    log.info("%s — Évaluation %s sur %s", run_label, prompt_label, suffix)
    log.info("=" * 55)

    query_params: dict = {}
    if args.eval_set:
        query = """
            SELECT p.ig_media_id, p.caption,
                   p.media_type::text AS media_type,
                   p.media_product_type::text AS media_product_type,
                   p.timestamp AS posted_at
            FROM eval_sets es
            JOIN posts p ON p.ig_media_id = es.ig_media_id
            JOIN annotations a ON a.ig_media_id = p.ig_media_id
            WHERE es.set_name = %(eval_set)s
              AND a.visual_format_id IS NOT NULL
              AND a.doubtful = false
        """
        query_params["eval_set"] = args.eval_set
    else:
        query = """
            SELECT p.ig_media_id, p.caption,
                   p.media_type::text AS media_type,
                   p.media_product_type::text AS media_product_type,
                   p.timestamp AS posted_at
            FROM sample_posts sp
            JOIN posts p ON p.ig_media_id = sp.ig_media_id
            JOIN annotations a ON a.ig_media_id = p.ig_media_id
            WHERE sp.split = %(split)s
              AND a.visual_format_id IS NOT NULL
        """
        query_params["split"] = args.split
    if args.since:
        query += " AND p.timestamp >= %(since)s::timestamp"
        query_params["since"] = args.since
    query += " ORDER BY p.timestamp"

    raw_posts = conn.execute(query, query_params).fetchall()
    log.info("Posts %s : %d", suffix, len(raw_posts))

    from milpo.config import (
        MODEL_CLASSIFIER,
        MODEL_CLASSIFIER_VISUAL_FORMAT,
        MODEL_DESCRIPTOR_FEED,
        MODEL_DESCRIPTOR_REELS,
    )

    is_e2e = args.e2e or args.e2e_harness
    e2e_model = MODEL_CLASSIFIER_VISUAL_FORMAT if is_e2e else None
    if args.e2e:
        suffix = f"e2e_{suffix}"
    elif args.e2e_harness:
        suffix = f"e2e_harness_{suffix}"

    run_id = create_run(conn, {
        "name": f"{run_label}_{args.prompts}_{suffix}",
        "split": args.split,
        "since": args.since,
        "prompts": args.prompts,
        "e2e": args.e2e,
        "e2e_harness": args.e2e_harness,
        "models": {
            "descriptor_feed": MODEL_DESCRIPTOR_FEED,
            "descriptor_reels": MODEL_DESCRIPTOR_REELS,
            "classifier": MODEL_CLASSIFIER,
            **({"e2e": e2e_model} if e2e_model else {}),
        },
    })
    log.info("simulation_run id=%d", run_id)

    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(
        raw_posts,
        load_post_media,
        conn,
        max_workers=20,
        load_all_media_fn=load_posts_media,
    )

    post_inputs: list[PostInput] = []
    skipped = 0
    for post in raw_posts:
        signed = signed_by_post.get(post["ig_media_id"], [])
        if not signed:
            skipped += 1
            continue
        post_inputs.append(PostInput(
            ig_media_id=post["ig_media_id"],
            media_product_type=post["media_product_type"],
            media_urls=[url for url, _ in signed],
            media_types=[media_type for _, media_type in signed],
            caption=post["caption"],
            posted_at=post.get("posted_at"),
        ))

    feed = sum(1 for post in post_inputs if post.media_product_type == "FEED")
    reels = len(post_inputs) - feed
    log.info("Prêts : %d (FEED %d / REELS %d) — %d skippés", len(post_inputs), feed, reels, skipped)

    prompt_records, prompt_ids = load_prompt_bundle(conn, args.prompts)
    prompt_contents = prompt_contents_from_records(prompt_records)
    prompts_by_scope = {
        scope: build_prompt_set(conn, scope, prompt_contents)
        for scope in ("FEED", "REELS")
    }
    labels_by_scope = {scope: build_labels(conn, scope) for scope in ("FEED", "REELS")}

    log.info("Classification en cours%s...", " (E2E)" if args.e2e else "")

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
            end="",
            flush=True,
        )

    if args.e2e_harness:
        from milpo.e2e_inference import async_classify_e2e_harness_batch

        results = await async_classify_e2e_harness_batch(
            posts=post_inputs,
            prompts_by_scope=prompts_by_scope,
            labels_by_scope=labels_by_scope,
            model=e2e_model,
            max_concurrent=10,
            k=3,
            on_progress=on_progress,
        )
    elif args.e2e:
        from milpo.e2e_inference import async_classify_e2e_batch

        results = await async_classify_e2e_batch(
            posts=post_inputs,
            prompts_by_scope=prompts_by_scope,
            labels_by_scope=labels_by_scope,
            model=e2e_model,
            max_concurrent=10,
            on_progress=on_progress,
        )
    else:
        results = await async_classify_batch(
            posts=post_inputs,
            prompts_by_scope=prompts_by_scope,
            labels_by_scope=labels_by_scope,
            max_concurrent_api=20,
            max_concurrent_posts=10,
            on_progress=on_progress,
        )
    errors = len(post_inputs) - len(results)
    print()
    log.info("Classifiés : %d / %d (erreurs : %d)", len(results), len(post_inputs), errors)

    log.info("Stockage en BDD...")
    matches, total_api = store_results(conn, results, post_inputs, prompt_ids, run_id)
    n = len(results)
    acc = {axis: value / n if n else 0 for axis, value in matches.items()}

    finish_run(conn, run_id, {
        "accuracy_category": acc["category"],
        "accuracy_visual_format": acc["visual_format"],
        "accuracy_strategy": acc["strategy"],
        "prompt_iterations": None,
        "total_api_calls": total_api,
        "total_cost_usd": None,
    })

    elapsed = time.monotonic() - t0
    total_in = sum(call.input_tokens for result in results for call in result.api_calls)
    total_out = sum(call.output_tokens for result in results for call in result.api_calls)

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
    return run_id


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    return asyncio.run(run_baseline(args))


__all__ = ["build_parser", "main", "run_baseline"]
