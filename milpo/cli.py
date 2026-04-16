"""Entry point CLI MILPO — classification d'un set sur un mode d'inférence.

Un seul point d'entrée pour évaluer la pipeline MILPO sur un dataset annoté.

Usage (via le binaire `classification` défini dans pyproject.toml) :

    uv run classification --alma --alpha
    uv run classification --simple --test
    uv run classification --alma --dev --limit 20 --no-persist

Modes d'inférence (mutuellement exclusifs, obligatoire) :
- `--alma`   : pipeline ASSIST 2 étages (Alma multimodal + 3 classifieurs text-only)
- `--simple` : 1 appel multimodal ASSIST par post (3 labels d'un coup)

Dataset (mutuellement exclusifs, obligatoire) :
- `--dev`   : `sample_posts.split = 'dev'`
- `--test`  : `sample_posts.split = 'test'`
- `--alpha` : `eval_sets.set_name = 'alpha'`

Options :
- `--limit N`        : limite le nombre de posts (smoke test)
- `--since YYYY-MM-DD`: ne garde que les posts publiés à partir de la date
- `--no-persist`     : dry run, rien n'est écrit en BDD
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from milpo.config import (
    MODEL_CLASSIFIER,
    MODEL_CLASSIFIER_VISUAL_FORMAT,
    MODEL_DESCRIPTOR_FEED,
    MODEL_DESCRIPTOR_REELS,
    MODEL_SIMPLE,
    compute_cost_usd,
)
from milpo.db import get_conn, load_post_media, load_posts_media
from milpo.gcs import sign_all_posts_media
from milpo.inference import (
    PipelineResult,
    PostInput,
    async_classify_alma_batch,
    async_classify_simple_batch,
)
from milpo.persistence import create_run, finish_run, store_results
from milpo.prompting import build_labels

# Modèles de référence
_FLASH_LITE = "gemini-3.1-flash-lite-preview"
_FLASH = "gemini-3-flash-preview"
# Tiers de modèles pour le flag --model (ablation 2×2).
#
# - flash-lite : tout en gemini-3.1-flash-lite-preview ($0.25/$1.50).
# - flash      : pour --alma, flash UNIQUEMENT sur visual_format (l'axe
#                difficile, 57 classes long-tail) ; descripteur et
#                classifieurs category/strategy restent en flash-lite.
#                Pour --simple, l'unique appel multimodal est en flash.
MODEL_TIERS: tuple[str, ...] = ("flash-lite", "flash")


def _resolve_tier(mode: str, tier: str) -> dict[str, str]:
    """Retourne le mapping {descriptor, classifier, classifier_vf, simple} pour un tier."""
    if tier == "flash-lite":
        return {
            "descriptor": _FLASH_LITE,
            "classifier": _FLASH_LITE,
            "classifier_vf": _FLASH_LITE,
            "simple": _FLASH_LITE,
        }
    if tier == "flash":
        return {
            "descriptor": _FLASH_LITE,   # descripteur reste léger (cf. runs 90-91)
            "classifier": _FLASH_LITE,   # category + strategy légers
            "classifier_vf": _FLASH,     # seul axe qui swap vers Flash
            "simple": _FLASH,            # unique appel multimodal E2E
        }
    raise ValueError(f"Tier inconnu : {tier!r}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("classification")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="classification",
        description="Classifie les posts d'un set d'évaluation via la pipeline MILPO.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--alma",
        action="store_true",
        help="Pipeline ASSIST 2 étages (Alma multimodal + 3 classifieurs text-only).",
    )
    mode.add_argument(
        "--simple",
        action="store_true",
        help="Pipeline 1 appel multimodal ASSIST (3 labels en un coup).",
    )

    dataset = parser.add_mutually_exclusive_group(required=True)
    dataset.add_argument(
        "--dev", action="store_true", help="Split dev (sample_posts.split='dev')."
    )
    dataset.add_argument(
        "--test", action="store_true", help="Split test (sample_posts.split='test')."
    )
    dataset.add_argument(
        "--alpha",
        action="store_true",
        help="Set alpha (eval_sets.set_name='alpha').",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre de posts (smoke test).",
    )
    parser.add_argument(
        "--post",
        type=str,
        default=None,
        help=(
            "ID(s) de post spécifiques à classifier, séparés par virgule. "
            "Ex: --post 17923657672548231,18081992584828369. "
            "Bypass le filtrage --dev/--test/--alpha : prend les posts tels quels si annotés."
        ),
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Filtre posts publiés à partir de YYYY-MM-DD.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Désactive l'écriture en BDD (dry run).",
    )
    parser.add_argument(
        "--model",
        choices=MODEL_TIERS,
        default=None,
        help=(
            "Tier de modèle. flash-lite = tout flash-lite. flash = flash sur "
            "descripteur+visual_format (et l'unique appel pour --simple), "
            "flash-lite ailleurs. Sans ce flag : MODEL_* de l'environnement."
        ),
    )

    return parser


def _pick_mode(args) -> str:
    return "alma" if args.alma else "simple"


def _pick_dataset(args) -> str:
    if args.dev:
        return "dev"
    if args.test:
        return "test"
    return "alpha"


def _pick_model(args) -> str | None:
    return args.model  # None ou "flash" / "flash-lite"


def _resolve_models(mode: str, tier: str | None) -> dict[str, str | None]:
    """Retourne les modèles à utiliser pour chaque rôle (None = défaut env)."""
    if tier is None:
        return {
            "descriptor": None,
            "classifier": None,
            "classifier_vf": None,
            "simple": None,
        }
    return _resolve_tier(mode, tier)


_BASE_SELECT = """
    p.ig_media_id, p.caption,
    p.media_type::text AS media_type,
    p.media_product_type::text AS media_product_type,
    p.timestamp AS posted_at,
    cat.name AS gt_category,
    vf.name AS gt_visual_format,
    a.strategy::text AS gt_strategy
"""

_GT_JOINS = """
    JOIN annotations a ON a.ig_media_id = p.ig_media_id
    LEFT JOIN categories cat ON cat.id = a.category_id
    LEFT JOIN visual_formats vf ON vf.id = a.visual_format_id
"""


def _load_posts(
    conn,
    dataset: str,
    since: str | None,
    limit: int | None,
    post_ids: list[int] | None = None,
) -> list[dict]:
    """Charge les posts annotés d'un dataset, avec leur ground truth."""
    params: dict = {}
    if post_ids:
        # Mode ciblé : on ignore dataset/since/limit et on prend les IDs fournis.
        query = f"""
            SELECT {_BASE_SELECT}
            FROM posts p
            {_GT_JOINS}
            WHERE p.ig_media_id = ANY(%(ids)s)
              AND a.visual_format_id IS NOT NULL
            ORDER BY p.timestamp
        """
        params["ids"] = post_ids
        return conn.execute(query, params).fetchall()

    if dataset == "alpha":
        query = f"""
            SELECT {_BASE_SELECT}
            FROM eval_sets es
            JOIN posts p ON p.ig_media_id = es.ig_media_id
            {_GT_JOINS}
            WHERE es.set_name = 'alpha'
              AND a.visual_format_id IS NOT NULL
              AND a.doubtful = false
        """
    else:
        query = f"""
            SELECT {_BASE_SELECT}
            FROM sample_posts sp
            JOIN posts p ON p.ig_media_id = sp.ig_media_id
            {_GT_JOINS}
            WHERE sp.split = %(split)s
              AND a.visual_format_id IS NOT NULL
              AND a.doubtful = false
        """
        params["split"] = dataset

    if since:
        query += " AND p.timestamp >= %(since)s::timestamp"
        params["since"] = since

    query += " ORDER BY p.timestamp"
    if limit:
        query += f" LIMIT {int(limit)}"

    return conn.execute(query, params).fetchall()


def _compute_matches_in_memory(
    results: list[PipelineResult], gt_by_post: dict[int, dict[str, str | None]]
) -> dict[str, int]:
    """Calcule les matches axe par axe depuis les GT chargées (sans BDD)."""
    matches = {"category": 0, "visual_format": 0, "strategy": 0}
    for result in results:
        gt = gt_by_post.get(result.prediction.ig_media_id, {})
        for axis in matches:
            if getattr(result.prediction, axis) == gt.get(axis):
                matches[axis] += 1
    return matches


def _build_progress(t0: float):
    def on_progress(done: int, total: int, errors: int) -> None:
        elapsed = time.monotonic() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        filled = done * 30 // total if total else 0
        bar = "█" * filled + "░" * (30 - filled)
        print(
            f"\r  {bar} {done:>3}/{total} "
            f"({(done * 100 // total) if total else 0:>2}%) "
            f"| {rate:.1f} posts/s "
            f"| ETA {eta:.0f}s "
            f"| erreurs {errors}",
            end="",
            flush=True,
        )

    return on_progress


def _models_config(mode: str, tier: str | None) -> dict[str, str]:
    """Construit le bloc 'models' inscrit dans simulation_runs.config."""
    resolved = _resolve_models(mode, tier)
    if mode == "alma":
        return {
            "descriptor_feed": resolved["descriptor"] or MODEL_DESCRIPTOR_FEED,
            "descriptor_reels": resolved["descriptor"] or MODEL_DESCRIPTOR_REELS,
            "classifier": resolved["classifier"] or MODEL_CLASSIFIER,
            "classifier_visual_format": (
                resolved["classifier_vf"] or MODEL_CLASSIFIER_VISUAL_FORMAT
            ),
        }
    return {"simple": resolved["simple"] or MODEL_SIMPLE}


async def run_classification(args) -> int:
    mode = _pick_mode(args)
    dataset = _pick_dataset(args)
    model_tier = _pick_model(args)
    resolved_models = _resolve_models(mode, model_tier)

    conn = get_conn()
    t0 = time.monotonic()

    suffix = "_".join(
        [mode, dataset]
        + ([f"model_{model_tier}"] if model_tier else [])
        + ([f"since_{args.since}"] if args.since else [])
        + ([f"limit_{args.limit}"] if args.limit else [])
    )

    log.info("=" * 55)
    log.info("MILPO classification — %s", suffix)
    log.info("=" * 55)

    post_ids = None
    if args.post:
        post_ids = [int(pid.strip()) for pid in args.post.split(",") if pid.strip()]
        log.info("Mode ciblé : %d post(s) demandés", len(post_ids))

    raw_posts = _load_posts(conn, dataset, args.since, args.limit, post_ids=post_ids)
    log.info("Posts chargés : %d", len(raw_posts))

    gt_by_post = {
        row["ig_media_id"]: {
            "category": row["gt_category"],
            "visual_format": row["gt_visual_format"],
            "strategy": row["gt_strategy"],
        }
        for row in raw_posts
    }

    run_id: int | None = None
    if not args.no_persist:
        run_id = create_run(
            conn,
            {
                "name": f"classification_{suffix}",
                "pipeline_mode": mode,
                "dataset": dataset,
                "model_tier": model_tier,
                "since": args.since,
                "limit": args.limit,
                "models": _models_config(mode, model_tier),
            },
        )
        log.info("simulation_run id=%d", run_id)
    else:
        log.info("--no-persist activé : aucune écriture BDD")

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
        post_inputs.append(
            PostInput(
                ig_media_id=post["ig_media_id"],
                media_product_type=post["media_product_type"],
                media_urls=[url for url, _ in signed],
                media_types=[media_type for _, media_type in signed],
                caption=post["caption"],
                posted_at=post.get("posted_at"),
            )
        )

    feed = sum(1 for post in post_inputs if post.media_product_type == "FEED")
    reels = len(post_inputs) - feed
    log.info(
        "Prêts : %d (FEED %d / REELS %d) — %d skippés",
        len(post_inputs),
        feed,
        reels,
        skipped,
    )

    labels_by_scope = {scope: build_labels(conn, scope) for scope in ("FEED", "REELS")}
    on_progress = _build_progress(t0)

    log.info(
        "Classification en cours (mode %s%s)...",
        mode,
        f", modèle {model_tier}" if model_tier else "",
    )

    if mode == "alma":
        results = await async_classify_alma_batch(
            posts=post_inputs,
            labels_by_scope=labels_by_scope,
            max_concurrent_api=20,
            max_concurrent_posts=10,
            on_progress=on_progress,
            descriptor_model=resolved_models["descriptor"],
            classifier_model=resolved_models["classifier"],
            classifier_vf_model=resolved_models["classifier_vf"],
        )
    else:
        results = await async_classify_simple_batch(
            posts=post_inputs,
            labels_by_scope=labels_by_scope,
            model=resolved_models["simple"] or MODEL_SIMPLE,
            max_concurrent=10,
            on_progress=on_progress,
        )

    errors = len(post_inputs) - len(results)
    print()
    log.info(
        "Classifiés : %d / %d (erreurs : %d)",
        len(results),
        len(post_inputs),
        errors,
    )

    n = len(results)
    total_api = sum(len(result.api_calls) for result in results)
    matches = _compute_matches_in_memory(results, gt_by_post)
    total_in = sum(call.input_tokens for r in results for call in r.api_calls)
    total_out = sum(call.output_tokens for r in results for call in r.api_calls)
    cost_usd = 0.0
    unknown_models: set[str] = set()
    for r in results:
        for call in r.api_calls:
            c = compute_cost_usd(call.model, call.input_tokens, call.output_tokens)
            if c is None:
                unknown_models.add(call.model)
            else:
                cost_usd += c

    if not args.no_persist and run_id is not None:
        log.info("Stockage en BDD...")
        # store_results recompte les matches via le trigger SQL — autoritative.
        matches, total_api = store_results(conn, results, post_inputs, run_id)
        acc = {axis: (value / n if n else 0) for axis, value in matches.items()}
        finish_run(
            conn,
            run_id,
            {
                "accuracy_category": acc["category"],
                "accuracy_visual_format": acc["visual_format"],
                "accuracy_strategy": acc["strategy"],
                "prompt_iterations": None,
                "total_api_calls": total_api,
                "total_cost_usd": round(cost_usd, 4) if cost_usd else None,
            },
        )

    elapsed = time.monotonic() - t0

    log.info("")
    log.info("=" * 55)
    log.info("RÉSULTATS")
    log.info("=" * 55)
    log.info("  Mode           : %s", mode)
    log.info("  Dataset        : %s", dataset)
    if model_tier:
        models_used = _models_config(mode, model_tier)
        log.info("  Tier modèle    : %s", model_tier)
        for role, model_name in models_used.items():
            log.info("    - %-26s %s", role + " :", model_name)
    log.info("  Posts          : %d", n)
    log.info("  Appels API     : %d", total_api)
    log.info("  Tokens         : %s in / %s out", f"{total_in:,}", f"{total_out:,}")
    log.info("  Coût           : $%.3f%s", cost_usd,
             f" (modèles sans prix : {sorted(unknown_models)})" if unknown_models else "")
    log.info("  Durée          : %.0fs (%.1f min)", elapsed, elapsed / 60)
    if n:
        log.info("")
        log.info(
            "  Accuracy catégorie     : %.1f%% (%d/%d)",
            matches["category"] * 100 / n,
            matches["category"],
            n,
        )
        log.info(
            "  Accuracy visual_format : %.1f%% (%d/%d)",
            matches["visual_format"] * 100 / n,
            matches["visual_format"],
            n,
        )
        log.info(
            "  Accuracy stratégie     : %.1f%% (%d/%d)",
            matches["strategy"] * 100 / n,
            matches["strategy"],
            n,
        )
        if run_id is not None:
            log.info("")
            log.info("  simulation_run_id = %d", run_id)
    log.info("✓ Classification terminée")

    conn.close()
    return run_id or 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run_classification(args))


if __name__ == "__main__":
    raise SystemExit(main())
