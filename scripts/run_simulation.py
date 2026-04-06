"""Simulation HILPO prequential — boucle d'optimisation de prompt.

Usage :
    uv run python scripts/run_simulation.py
    uv run python scripts/run_simulation.py --batch-size 10 --limit 200
    uv run python scripts/run_simulation.py --dry-run  # B0-on-dev, pas de rewrite

Variables d'environnement (chargées depuis .env) :
    OPENROUTER_API_KEY          — clé API OpenRouter
    HILPO_GCS_SIGNING_SA_EMAIL  — service account pour signer les URLs GCS
    HILPO_DATABASE_DSN          — DSN PostgreSQL
    HILPO_MODEL_REWRITER        — modèle rewriter (défaut: openai/gpt-5.4)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from hilpo.config import MODEL_REWRITER
from hilpo.db import (
    format_descriptions,
    get_active_prompt,
    get_conn,
    insert_prompt_version,
    load_categories,
    load_dev_annotations,
    load_dev_posts,
    load_post_media,
    load_strategies,
    load_visual_formats,
    promote_prompt,
    store_api_call,
    store_prediction,
    store_rewrite_log,
)
from hilpo.eval import accuracy
from hilpo.errors import LLMCallError
from hilpo.gcs import sign_all_posts_media
from hilpo.inference import ApiCallLog, PipelineResult, PostInput, PromptSet, classify_post
from hilpo.rewriter import ErrorCase, RewriteResult, rewrite_prompt

# Les 6 couples (agent, scope) qui pilotent l'optimisation HILPO.
# Source de vérité du contenu : BDD (migration 006_seed_prompts_v0.sql).
PROMPT_KEYS: list[tuple[str, str | None]] = [
    ("descriptor", "FEED"),
    ("descriptor", "REELS"),
    ("category", None),
    ("visual_format", "FEED"),
    ("visual_format", "REELS"),
    ("strategy", None),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("simulation")


# ── Structures d'état ─────────────────────────────────────────


@dataclass
class PromptState:
    """Prompt actif par (agent, scope)."""

    instructions: dict[tuple[str, str | None], str] = field(default_factory=dict)
    db_ids: dict[tuple[str, str | None], int] = field(default_factory=dict)
    versions: dict[tuple[str, str | None], int] = field(default_factory=dict)


@dataclass
class MatchRecord:
    """Enregistrement d'un match/mismatch par axe."""

    axis: str
    match: bool
    cursor: int


@dataclass
class DoubleEvalResult:
    """Résultats détaillés de la double évaluation."""

    incumbent_matches: list[bool] = field(default_factory=list)
    candidate_matches: list[bool] = field(default_factory=list)
    incumbent_records: list[MatchRecord] = field(default_factory=list)


# ── Helpers BDD ───────────────────────────────────────────────


def create_run(conn, config: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO simulation_runs (seed, batch_size, config, status, started_at)
        VALUES (42, %s, %s::jsonb, 'running', NOW())
        RETURNING id
        """,
        (config.get("batch_size", 30), json.dumps(config)),
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
            prompt_iterations = %s,
            total_api_calls = %s, total_cost_usd = %s
        WHERE id = %s
        """,
        (
            metrics["accuracy_category"],
            metrics["accuracy_visual_format"],
            metrics["accuracy_strategy"],
            metrics["prompt_iterations"],
            metrics["total_api_calls"],
            metrics.get("total_cost_usd"),
            run_id,
        ),
    )
    conn.commit()


def fail_run(conn, run_id: int, error_message: str, metrics: dict):
    """Marque un run comme échoué en conservant les métriques partielles."""
    conn.execute(
        """
        UPDATE simulation_runs SET
            status = 'failed', finished_at = NOW(),
            final_accuracy_category = %s,
            final_accuracy_visual_format = %s,
            final_accuracy_strategy = %s,
            prompt_iterations = %s,
            total_api_calls = %s, total_cost_usd = %s,
            config = COALESCE(config, '{}'::jsonb) || jsonb_build_object('failure_reason', %s)
        WHERE id = %s
        """,
        (
            metrics["accuracy_category"],
            metrics["accuracy_visual_format"],
            metrics["accuracy_strategy"],
            metrics["prompt_iterations"],
            metrics["total_api_calls"],
            metrics.get("total_cost_usd"),
            error_message[:1000],
            run_id,
        ),
    )
    conn.commit()


def build_run_metrics(
    matches_by_axis: dict[str, int],
    n_processed: int,
    rewrite_count: int,
    total_api_calls: int,
) -> dict:
    """Construit le payload de métriques final ou partiel pour simulation_runs."""
    return {
        "accuracy_category": matches_by_axis["category"] / n_processed if n_processed else 0,
        "accuracy_visual_format": matches_by_axis["visual_format"] / n_processed if n_processed else 0,
        "accuracy_strategy": matches_by_axis["strategy"] / n_processed if n_processed else 0,
        "prompt_iterations": rewrite_count,
        "total_api_calls": total_api_calls,
        "total_cost_usd": None,
    }


def load_prompt_state_from_db(conn) -> PromptState:
    """Charge l'état initial du PromptState depuis la BDD.

    Lit les 6 prompts actifs (un par (agent, scope)) via get_active_prompt().
    Aucune source de vérité en dur : si un prompt manque, échec explicite
    pointant vers la migration 006_seed_prompts_v0.sql.
    """
    instructions: dict[tuple[str, str | None], str] = {}
    db_ids: dict[tuple[str, str | None], int] = {}
    versions: dict[tuple[str, str | None], int] = {}

    for agent, scope in PROMPT_KEYS:
        row = get_active_prompt(conn, agent, scope)
        if row is None:
            raise RuntimeError(
                f"Prompt actif introuvable en BDD pour {agent}/{scope or 'all'}. "
                "Appliquer apps/backend/migrations/006_seed_prompts_v0.sql avant de lancer la simulation."
            )
        key = (agent, scope)
        instructions[key] = row["content"]
        db_ids[key] = row["id"]
        versions[key] = row["version"]
        log.info(
            "  prompt chargé : %s/%s -> v%s (id=%d)",
            agent,
            scope or "all",
            row["version"],
            row["id"],
        )

    return PromptState(instructions=instructions, db_ids=db_ids, versions=versions)


# ── Construction des prompts ──────────────────────────────────


def build_prompts_from_state(
    prompt_state: PromptState,
    conn,
    scope: str,
) -> PromptSet:
    """Construit un PromptSet à partir de l'état courant des prompts."""
    vf = load_visual_formats(conn, scope)
    cats = load_categories(conn)
    strats = load_strategies(conn)
    return PromptSet(
        descriptor_instructions=prompt_state.instructions[("descriptor", scope)],
        category_instructions=prompt_state.instructions[("category", None)],
        visual_format_instructions=prompt_state.instructions[("visual_format", scope)],
        strategy_instructions=prompt_state.instructions[("strategy", None)],
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


# ── Classification + stockage d'un post ──────────────────────


def classify_and_store(
    post: PostInput,
    annotation: dict,
    prompts: PromptSet,
    labels: dict[str, list[str]],
    prompt_state: PromptState,
    conn,
    run_id: int,
    call_type: str = "classification",
) -> tuple[PipelineResult, list[ErrorCase], list[MatchRecord]]:
    """Classifie un post, stocke les résultats, retourne les erreurs et matches."""
    scope = post.media_product_type
    result = classify_post(
        post, prompts,
        labels["category"], labels["visual_format"], labels["strategy"],
    )
    pred = result.prediction

    errors: list[ErrorCase] = []
    matches: list[MatchRecord] = []

    for axis in ("category", "visual_format", "strategy"):
        predicted = getattr(pred, axis)
        expected = annotation[axis]
        is_match = predicted == expected

        # Prompt id pour cet axe
        scope_key = scope if axis in ("visual_format", "descriptor") else None
        prompt_id = prompt_state.db_ids.get((axis, scope_key)) or prompt_state.db_ids.get((axis, None))

        store_prediction(
            conn, pred.ig_media_id, axis, prompt_id,
            predicted,
            raw_response=pred.features.model_dump() if axis == "visual_format" else None,
            simulation_run_id=run_id,
        )
        matches.append(MatchRecord(axis=axis, match=is_match, cursor=0))

        if not is_match:
            # Charger les descriptions des labels
            desc_predicted = _get_label_description(conn, axis, predicted, scope)
            desc_expected = _get_label_description(conn, axis, expected, scope)
            errors.append(ErrorCase(
                ig_media_id=pred.ig_media_id,
                axis=axis,
                prompt_scope=scope if axis == "visual_format" else None,
                post_scope=scope,
                predicted=predicted,
                expected=expected,
                features_json=pred.features.model_dump_json(indent=2),
                caption=post.caption,
                desc_predicted=desc_predicted,
                desc_expected=desc_expected,
            ))

    # Stocker descripteur
    desc_prompt_id = prompt_state.db_ids.get(("descriptor", scope))
    if desc_prompt_id:
        store_prediction(
            conn, pred.ig_media_id, "descriptor", desc_prompt_id,
            "features_extracted",
            raw_response=pred.features.model_dump(),
            simulation_run_id=run_id,
        )

    # Stocker api_calls
    for call in result.api_calls:
        scope_key = scope if call.agent in ("descriptor", "visual_format") else None
        prompt_id = prompt_state.db_ids.get((call.agent, scope_key)) or prompt_state.db_ids.get((call.agent, None))
        store_api_call(
            conn, call_type, call.agent, call.model, prompt_id,
            pred.ig_media_id,
            call.input_tokens, call.output_tokens, None, call.latency_ms,
            run_id,
        )

    return result, errors, matches


_desc_cache: dict[tuple[str, str], str] = {}


def _get_label_description(conn, axis: str, label: str, scope: str) -> str:
    """Récupère la description d'un label depuis la BDD (avec cache)."""
    cache_key = (axis, label)
    if cache_key in _desc_cache:
        return _desc_cache[cache_key]

    table = {"category": "categories", "visual_format": "visual_formats", "strategy": "strategies"}[axis]
    row = conn.execute(
        f"SELECT description FROM {table} WHERE name = %s",  # noqa: S608
        (label,),
    ).fetchone()
    desc = row["description"] if row and row["description"] else "(pas de description)"
    _desc_cache[cache_key] = desc
    return desc


# ── Sélection de la cible du rewrite ─────────────────────────


def pick_rewrite_target(
    error_buffer: list[ErrorCase],
) -> tuple[str, str | None]:
    """Choisit (agent, scope) avec le plus d'erreurs dans le buffer."""
    counts: Counter[tuple[str, str | None]] = Counter()
    grouped_by_post: dict[tuple[int, str], list[ErrorCase]] = defaultdict(list)

    for e in error_buffer:
        counts[(e.axis, e.prompt_scope)] += 1
        grouped_by_post[(e.ig_media_id, e.post_scope)].append(e)

    # Le descripteur n'a pas de label GT propre. On ne le cible que quand
    # plusieurs axes échouent sur un même post, signal d'un problème amont.
    for (_, scope), grouped_errors in grouped_by_post.items():
        if len(grouped_errors) >= 2:
            counts[("descriptor", scope)] += len(grouped_errors)

    return counts.most_common(1)[0][0]


def get_target_errors(
    error_buffer: list[ErrorCase],
    target_agent: str,
    target_scope: str | None,
) -> list[ErrorCase]:
    """Filtre les erreurs pertinentes pour la cible du rewrite."""
    if target_agent != "descriptor":
        return [
            e for e in error_buffer
            if e.axis == target_agent and e.prompt_scope == target_scope
        ]

    grouped_by_post: dict[int, list[ErrorCase]] = defaultdict(list)
    for error in error_buffer:
        if error.post_scope == target_scope:
            grouped_by_post[error.ig_media_id].append(error)

    target_errors: list[ErrorCase] = []
    for grouped_errors in grouped_by_post.values():
        if len(grouped_errors) >= 2:
            target_errors.extend(grouped_errors)
    return target_errors


def _store_eval_predictions_for_target(
    conn,
    post_id: int,
    prompt_version_id: int,
    target_agent: str,
    prediction,
    run_id: int,
) -> None:
    """Persiste les prédictions utiles à l'audit du prompt évalué."""
    if target_agent == "descriptor":
        # Le descripteur n'a pas de label GT propre. On journalise donc l'effet
        # downstream de ce prompt sur les 3 axes supervisés.
        for axis in ("category", "visual_format", "strategy"):
            store_prediction(
                conn,
                post_id,
                axis,
                prompt_version_id,
                getattr(prediction, axis),
                simulation_run_id=run_id,
            )
        return

    store_prediction(
        conn,
        post_id,
        target_agent,
        prompt_version_id,
        getattr(prediction, target_agent),
        simulation_run_id=run_id,
    )


def _target_metric_matches(result: PipelineResult, annotation: dict, target_agent: str) -> list[bool]:
    """Retourne les matches pris en compte pour la promotion."""
    if target_agent == "descriptor":
        return [
            getattr(result.prediction, axis) == annotation[axis]
            for axis in ("category", "visual_format", "strategy")
        ]
    return [getattr(result.prediction, target_agent) == annotation[target_agent]]


# ── Double évaluation ─────────────────────────────────────────


def double_evaluate(
    eval_posts: list[PostInput],
    annotations: dict[int, dict],
    start_cursor: int,
    prompt_state: PromptState,
    target_agent: str,
    target_scope: str | None,
    candidate_instructions: str,
    candidate_db_id: int,
    conn,
    run_id: int,
    labels_by_scope: dict[str, dict[str, list[str]]],
) -> DoubleEvalResult:
    """Évalue incumbent vs candidate sur les eval_posts.

    Retourne les matches utilisés pour la promotion et les matches incumbent
    à réinjecter dans les métriques finales de la simulation.
    """
    result = DoubleEvalResult()

    for offset, post in enumerate(eval_posts):
        annotation = annotations.get(post.ig_media_id)
        if not annotation:
            continue

        scope = post.media_product_type
        labels = labels_by_scope[scope]

        # ── Incumbent ──
        prompts_inc = build_prompts_from_state(prompt_state, conn, scope)
        result_inc = classify_post(
            post, prompts_inc,
            labels["category"], labels["visual_format"], labels["strategy"],
        )

        # Stocker predictions incumbent (call_type=evaluation)
        for axis in ("category", "visual_format", "strategy"):
            scope_key = scope if axis in ("visual_format", "descriptor") else None
            pid = prompt_state.db_ids.get((axis, scope_key)) or prompt_state.db_ids.get((axis, None))
            store_prediction(conn, post.ig_media_id, axis, pid,
                             getattr(result_inc.prediction, axis),
                             simulation_run_id=run_id)
            result.incumbent_records.append(MatchRecord(
                axis=axis,
                match=getattr(result_inc.prediction, axis) == annotation[axis],
                cursor=start_cursor + offset,
            ))
        for call in result_inc.api_calls:
            scope_key = scope if call.agent in ("descriptor", "visual_format") else None
            pid = prompt_state.db_ids.get((call.agent, scope_key)) or prompt_state.db_ids.get((call.agent, None))
            store_api_call(conn, "evaluation", call.agent, call.model, pid,
                           post.ig_media_id, call.input_tokens, call.output_tokens,
                           None, call.latency_ms, run_id)

        if target_agent == "descriptor":
            _store_eval_predictions_for_target(
                conn=conn,
                post_id=post.ig_media_id,
                prompt_version_id=prompt_state.db_ids[(target_agent, target_scope)],
                target_agent=target_agent,
                prediction=result_inc.prediction,
                run_id=run_id,
            )

        # ── Candidate ──
        # Construire le PromptSet avec les instructions candidate pour la cible
        candidate_state = PromptState(
            instructions={**prompt_state.instructions, (target_agent, target_scope): candidate_instructions},
            db_ids={**prompt_state.db_ids, (target_agent, target_scope): candidate_db_id},
            versions=prompt_state.versions.copy(),
        )
        prompts_cand = build_prompts_from_state(candidate_state, conn, scope)

        # Si la cible est scopée et le scope ne matche pas, skip candidate
        if target_scope is not None and scope != target_scope:
            # Même résultat que incumbent (le candidate ne change rien pour ce scope)
            metric_matches = _target_metric_matches(result_inc, annotation, target_agent)
            result.incumbent_matches.extend(metric_matches)
            result.candidate_matches.extend(metric_matches)
            continue

        result_cand = classify_post(
            post, prompts_cand,
            labels["category"], labels["visual_format"], labels["strategy"],
        )

        # Stocker predictions candidate (call_type=evaluation)
        for call in result_cand.api_calls:
            scope_key = scope if call.agent in ("descriptor", "visual_format") else None
            pid = candidate_state.db_ids.get((call.agent, scope_key)) or candidate_state.db_ids.get((call.agent, None))
            store_api_call(conn, "evaluation", call.agent, call.model, pid,
                           post.ig_media_id, call.input_tokens, call.output_tokens,
                           None, call.latency_ms, run_id)

        _store_eval_predictions_for_target(
            conn=conn,
            post_id=post.ig_media_id,
            prompt_version_id=candidate_db_id,
            target_agent=target_agent,
            prediction=result_cand.prediction,
            run_id=run_id,
        )

        result.incumbent_matches.extend(_target_metric_matches(result_inc, annotation, target_agent))
        result.candidate_matches.extend(_target_metric_matches(result_cand, annotation, target_agent))

    return result


# ── Display ───────────────────────────────────────────────────


def display_progress(cursor, total, matches_by_axis, n_processed, error_count, batch_size, prompt_versions, cost, t0):
    elapsed = time.monotonic() - t0
    rate = n_processed / elapsed if elapsed > 0 else 0
    eta = (total - cursor) / rate if rate > 0 else 0
    pct = cursor * 100 // total if total else 0
    bar = "█" * (cursor * 30 // total) + "░" * (30 - cursor * 30 // total)

    acc_vf = matches_by_axis["visual_format"] / n_processed * 100 if n_processed else 0
    acc_cat = matches_by_axis["category"] / n_processed * 100 if n_processed else 0
    acc_str = matches_by_axis["strategy"] / n_processed * 100 if n_processed else 0

    # Version max affichée
    max_v = max(prompt_versions.values()) if prompt_versions else 0

    print(
        f"\r  {bar} {cursor:>4}/{total} ({pct:>2}%) "
        f"| vf={acc_vf:.1f}% cat={acc_cat:.1f}% str={acc_str:.1f}% "
        f"| v{max_v} "
        f"| err={error_count}/{batch_size} "
        f"| {rate:.1f}p/s ETA {eta:.0f}s "
        f"| est~${cost:.2f}",
        end="", flush=True,
    )


def display_rolling(cursor, all_matches, window=50):
    """Affiche l'accuracy rolling toutes les 50 positions."""
    if cursor % window != 0 or cursor == 0:
        return
    recent = all_matches[-window:]
    by_axis = {"category": [], "visual_format": [], "strategy": []}
    for m in recent:
        by_axis[m.axis].append(m.match)
    parts = []
    for axis in ("category", "visual_format", "strategy"):
        if by_axis[axis]:
            acc = sum(by_axis[axis]) / len(by_axis[axis]) * 100
            short = {"category": "cat", "visual_format": "vf", "strategy": "str"}[axis]
            parts.append(f"{short}={acc:.1f}%")
    print(f"\n  [ACC @{cursor}] {' | '.join(parts)} (rolling {window})")


# ── Main ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Simulation HILPO prequential")
    parser.add_argument("-B", "--batch-size", type=int, default=30)
    parser.add_argument("--delta", type=float, default=0.02)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--eval-window", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Pas de rewrite (B0-on-dev)")
    parser.add_argument("--no-rollback", action="store_true", help="Ablation A5")
    parser.add_argument("--limit", type=int, default=None, help="Nombre de posts max")
    parser.add_argument("--rewriter-model", type=str, default=MODEL_REWRITER)
    args = parser.parse_args()

    conn = get_conn()
    run_id: int | None = None
    t0 = time.monotonic()
    matches_by_axis = {"category": 0, "visual_format": 0, "strategy": 0}
    n_processed = 0
    total_api_calls = 0
    live_cost_estimate_usd = 0.0
    rewrite_count = 0
    skipped_classification_posts = 0
    failed_rewrite_attempts = 0

    try:
        # ── Header ──
        log.info("=" * 60)
        log.info("  HILPO — Simulation prequential")
        log.info("  B=%d  delta=%.0f%%  patience=%d  eval_window=%d",
                 args.batch_size, args.delta * 100, args.patience, args.eval_window)
        if args.dry_run:
            log.info("  MODE: dry-run (pas de rewrite)")
        if args.no_rollback:
            log.info("  MODE: no-rollback (ablation A5)")
        log.info("=" * 60)

        # ── 1. Charger les posts dev ──
        raw_posts = load_dev_posts(conn, limit=args.limit)
        log.info("Posts dev chargés : %d", len(raw_posts))

        # ── 2. Charger les annotations ──
        annotations = load_dev_annotations(conn)
        log.info("Annotations dev : %d", len(annotations))

        # Filtrer les posts non annotés
        annotated_ids = set(annotations.keys())
        raw_posts = [p for p in raw_posts if p["ig_media_id"] in annotated_ids]
        if len(raw_posts) < len(annotated_ids):
            log.warning("  %d posts sans annotation — ignorés", len(annotated_ids) - len(raw_posts))
        log.info("Posts à traiter : %d", len(raw_posts))

        if not raw_posts:
            log.error("Aucun post annoté dans le split dev. Annote d'abord !")
            sys.exit(1)

        # ── 3. Simulation run ──
        run_id = create_run(conn, {
            "name": f"HILPO_B{args.batch_size}" + ("_dryrun" if args.dry_run else ""),
            "split": "dev",
            "batch_size": args.batch_size,
            "delta": args.delta,
            "patience": args.patience,
            "eval_window": args.eval_window,
            "dry_run": args.dry_run,
            "no_rollback": args.no_rollback,
            "rewriter_model": args.rewriter_model,
        })
        log.info("simulation_run id=%d", run_id)

        # ── 4. Signer les URLs GCS ──
        log.info("Signature des URLs GCS (expiration 120min)...")
        signed_by_post = sign_all_posts_media(raw_posts, load_post_media, conn, max_workers=20)

        post_inputs: list[PostInput] = []
        skipped_signed_urls = 0
        for post in raw_posts:
            mid = post["ig_media_id"]
            signed = signed_by_post.get(mid, [])
            if not signed:
                skipped_signed_urls += 1
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
        log.info("Prêts : %d (FEED %d / REELS %d) — %d skippés", len(post_inputs), feed, reels, skipped_signed_urls)

        # ── 5. Initialiser les prompts depuis la BDD ──
        log.info("Chargement des prompts actifs depuis la BDD...")
        prompt_state = load_prompt_state_from_db(conn)

        # ── 6. Labels et descriptions par scope (cache) ──
        labels_by_scope: dict[str, dict[str, list[str]]] = {}
        for scope in ("FEED", "REELS"):
            labels_by_scope[scope] = build_labels(conn, scope)

        # ── 7. Boucle principale ──
        log.info("Classification en cours...")

        error_buffer: list[ErrorCase] = []
        all_matches: list[MatchRecord] = []
        cursor = 0
        consecutive_failures = 0
        rewrites_stopped = False

        total = len(post_inputs)

        while cursor < total:
            post = post_inputs[cursor]
            annotation = annotations[post.ig_media_id]
            scope = post.media_product_type

            # Classifier un post
            prompts = build_prompts_from_state(prompt_state, conn, scope)
            labels = labels_by_scope[scope]

            try:
                result, errors, matches = classify_and_store(
                    post, annotation, prompts, labels, prompt_state, conn, run_id,
                )
            except LLMCallError as exc:
                skipped_classification_posts += 1
                cursor += 1
                print()
                log.warning(
                    "[POST %d/%d] Classification échouée pour ig_media_id=%s après retries. Post ignoré: %s",
                    cursor, total, post.ig_media_id, exc,
                )
                display_progress(
                    cursor, total, matches_by_axis, n_processed,
                    len(error_buffer), args.batch_size, prompt_state.versions, live_cost_estimate_usd, t0,
                )
                continue

            for m in matches:
                m.cursor = cursor
                all_matches.append(m)
                if m.match:
                    matches_by_axis[m.axis] += 1

            error_buffer.extend(errors)
            n_processed += 1
            total_api_calls += len(result.api_calls)
            # Estimation live rough pour le monitoring local uniquement.
            # Ne pas utiliser pour le mémoire : pricing variable selon provider/modèle/date.
            live_cost_estimate_usd += sum(
                c.input_tokens * 0.0001 / 1000 + c.output_tokens * 0.0003 / 1000
                for c in result.api_calls
            )

            cursor += 1

            display_progress(cursor, total, matches_by_axis, n_processed,
                             len(error_buffer), args.batch_size, prompt_state.versions, live_cost_estimate_usd, t0)
            display_rolling(cursor, all_matches)

            # ── Trigger rewrite ? ──
            if (
                not args.dry_run
                and not rewrites_stopped
                and len(error_buffer) >= args.batch_size
            ):
                target_agent, target_scope = pick_rewrite_target(error_buffer)
                target_errors = get_target_errors(error_buffer, target_agent, target_scope)

                if not target_errors:
                    log.warning("[REWRITE] Aucune erreur exploitable pour %s/%s. Buffer reset.",
                                target_agent, target_scope or "all")
                    error_buffer.clear()
                    continue

                rewrite_count += 1
                print()  # newline après la progress bar
                log.info("[REWRITE #%d] Buffer plein (%d erreurs). Cible: %s/%s (%d erreurs)",
                         rewrite_count, len(error_buffer), target_agent, target_scope or "all", len(target_errors))

                try:
                    # Descriptions pour le scope de la cible
                    effective_scope = target_scope or "FEED"  # fallback pour category/strategy
                    if target_agent == "descriptor":
                        all_descs = (
                            "## Formats visuels\n\n"
                            + format_descriptions(load_visual_formats(conn, effective_scope))
                            + "\n\n## Catégories\n\n"
                            + format_descriptions(load_categories(conn))
                            + "\n\n## Stratégies\n\n"
                            + format_descriptions(load_strategies(conn))
                        )
                    else:
                        all_descs = format_descriptions(
                            load_visual_formats(conn, effective_scope) if target_agent == "visual_format"
                            else load_categories(conn) if target_agent == "category"
                            else load_strategies(conn)
                        )

                    log.info("[REWRITE #%d] Appel rewriter (%s)...", rewrite_count, args.rewriter_model)
                    current_key = (target_agent, target_scope)
                    rewrite_result = rewrite_prompt(
                        target_agent=target_agent,
                        target_scope=target_scope,
                        current_instructions=prompt_state.instructions[current_key],
                        errors=target_errors,
                        all_descriptions=all_descs,
                        model=args.rewriter_model,
                    )

                    store_api_call(
                        conn, "rewrite", target_agent, rewrite_result.model, prompt_state.db_ids[current_key],
                        None, rewrite_result.input_tokens, rewrite_result.output_tokens, None,
                        rewrite_result.latency_ms, run_id,
                    )
                    total_api_calls += 1

                    log.info("[REWRITE #%d] Candidate généré (%.1fs, %dK tokens). Évaluation sur %d posts...",
                             rewrite_count, rewrite_result.latency_ms / 1000,
                             (rewrite_result.input_tokens + rewrite_result.output_tokens) // 1000,
                             args.eval_window)

                    new_version = prompt_state.versions[current_key] + 1
                    candidate_id = insert_prompt_version(
                        conn, target_agent, target_scope, new_version,
                        rewrite_result.new_instructions,
                        status="draft",
                        parent_id=prompt_state.db_ids[current_key],
                        simulation_run_id=run_id,
                    )

                    eval_end = min(cursor + args.eval_window, total)
                    eval_posts = post_inputs[cursor:eval_end]

                    if len(eval_posts) < 5:
                        log.warning("[REWRITE #%d] Pas assez de posts pour évaluer (%d). Skip.", rewrite_count, len(eval_posts))
                        error_buffer.clear()
                        continue

                    double_eval_result = double_evaluate(
                        eval_posts, annotations, cursor, prompt_state,
                        target_agent, target_scope,
                        rewrite_result.new_instructions, candidate_id,
                        conn, run_id, labels_by_scope,
                    )

                    inc_acc = accuracy(double_eval_result.incumbent_matches)
                    cand_acc = accuracy(double_eval_result.candidate_matches)
                    delta_actual = cand_acc - inc_acc

                    # Compter les api calls de l'évaluation
                    eval_api_count = len(eval_posts) * 4 * 2  # 4 agents × 2 runs (rough)
                    total_api_calls += eval_api_count

                    promoted = cand_acc >= inc_acc + args.delta
                    if args.no_rollback:
                        promoted = cand_acc > inc_acc  # ablation A5 : promote si strictement mieux

                    store_rewrite_log(
                        conn,
                        prompt_before_id=prompt_state.db_ids[current_key],
                        prompt_after_id=candidate_id,
                        error_batch=[{
                            "axis": e.axis,
                            "predicted": e.predicted,
                            "expected": e.expected,
                            "ig_media_id": e.ig_media_id,
                            "post_scope": e.post_scope,
                        } for e in target_errors],
                        rewriter_reasoning=rewrite_result.reasoning,
                        accepted=promoted,
                        simulation_run_id=run_id,
                        target_agent=target_agent,
                        target_scope=target_scope,
                        incumbent_accuracy=inc_acc,
                        candidate_accuracy=cand_acc,
                        eval_sample_size=len(eval_posts),
                        iteration=rewrite_count,
                    )

                    if promoted:
                        promote_prompt(conn, target_agent, target_scope, candidate_id)

                        prompt_state.instructions[current_key] = rewrite_result.new_instructions
                        prompt_state.db_ids[current_key] = candidate_id
                        prompt_state.versions[current_key] = new_version
                        consecutive_failures = 0

                        log.info("[REWRITE #%d] Incumbent %.1f%% vs Candidate %.1f%% (Δ=+%.1f%%)",
                                 rewrite_count, inc_acc * 100, cand_acc * 100, delta_actual * 100)
                        log.info("[REWRITE #%d] >>> PROMOTED (v%d → v%d %s/%s) <<<",
                                 rewrite_count, new_version - 1, new_version, target_agent, target_scope or "all")
                    else:
                        consecutive_failures += 1
                        log.info("[REWRITE #%d] Incumbent %.1f%% vs Candidate %.1f%% (Δ=%.1f%%)",
                                 rewrite_count, inc_acc * 100, cand_acc * 100, delta_actual * 100)
                        log.info("[REWRITE #%d] <<< ROLLBACK (patience %d/%d) <<<",
                                 rewrite_count, consecutive_failures, args.patience)

                    for match_record in double_eval_result.incumbent_records:
                        all_matches.append(match_record)
                        if match_record.match:
                            matches_by_axis[match_record.axis] += 1

                    n_processed += len(eval_posts)
                    cursor = eval_end
                    error_buffer.clear()
                except LLMCallError as exc:
                    failed_rewrite_attempts += 1
                    consecutive_failures += 1
                    log.warning(
                        "[REWRITE #%d] Échec pour %s/%s après retries. Buffer reset: %s",
                        rewrite_count, target_agent, target_scope or "all", exc,
                    )
                    error_buffer.clear()

                if consecutive_failures >= args.patience:
                    log.info("[STOP] Patience épuisée (%d/%d). Poursuite sans rewrite.",
                             consecutive_failures, args.patience)
                    rewrites_stopped = True

        print()  # newline finale

        metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
        finish_run(conn, run_id, metrics)

        elapsed = time.monotonic() - t0

        log.info("")
        log.info("=" * 60)
        log.info("  RÉSULTATS SIMULATION HILPO")
        log.info("=" * 60)
        log.info("  Posts scorés   : %d", n_processed)
        log.info("  Posts ignorés  : %d (échec LLM après retries)", skipped_classification_posts)
        log.info("  Appels API     : %d", total_api_calls)
        log.info("  Durée          : %.0fs (%.1f min)", elapsed, elapsed / 60)
        log.info("  Coût live est. : ~$%.2f (monitoring only, non reporté)", live_cost_estimate_usd)
        log.info("")
        log.info("  Prompts finaux :")
        for (agent, scope), version in sorted(prompt_state.versions.items()):
            log.info("    %s/%s : v%d", agent, scope or "all", version)
        log.info("")
        log.info("  Rewrites       : %d tentés, %d promus, %d échoués",
                 rewrite_count,
                 sum(prompt_state.versions.values()),
                 failed_rewrite_attempts)
        log.info("")
        log.info("  Accuracy (tout le dev scoré) :")
        log.info("    Catégorie      : %.1f%% (%d/%d)", metrics["accuracy_category"] * 100, matches_by_axis["category"], n_processed)
        log.info("    Visual_format  : %.1f%% (%d/%d)", metrics["accuracy_visual_format"] * 100, matches_by_axis["visual_format"], n_processed)
        log.info("    Stratégie      : %.1f%% (%d/%d)", metrics["accuracy_strategy"] * 100, matches_by_axis["strategy"], n_processed)
        log.info("")
        log.info("  simulation_run_id = %d", run_id)
        log.info("✓ Simulation terminée")
    except Exception as exc:
        print()
        log.exception("[FATAL] Simulation interrompue: %s", exc)
        if run_id is not None:
            metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
            fail_run(conn, run_id, str(exc), metrics)
            log.info("  simulation_run_id = %d", run_id)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
