"""Simulation MILPO prequential — boucle d'optimisation de prompt ProTeGi.

Implémentation fidèle de Pryzant et al. 2023 (EMNLP, arxiv 2305.03495) :
gradient textuel (LLM_∇) + édition (LLM_δ) + paraphrase monte-carlo (LLM_mc)
+ Successive Rejects (Audibert & Bubeck 2010) pour la sélection.

Usage :
    uv run python scripts/run_simulation.py
    uv run python scripts/run_simulation.py --batch-size 10 --limit 200
    uv run python scripts/run_simulation.py --dry-run  # B0-on-dev, pas de rewrite

Variables d'environnement (chargées depuis .env) :
    OPENROUTER_API_KEY          — clé API OpenRouter
    HILPO_GCS_SIGNING_SA_EMAIL  — service account pour signer les URLs GCS
    HILPO_DATABASE_DSN          — DSN PostgreSQL
    HILPO_MODEL_CRITIC          — modèle LLM_∇ (défaut: openai/gpt-5.4)
    HILPO_MODEL_EDITOR          — modèle LLM_δ (défaut: openai/gpt-5.4)
    HILPO_MODEL_PARAPHRASER     — modèle LLM_mc (défaut: openai/gpt-5.4)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable

from dataclasses import dataclass, field

from rich.console import Console
from rich.live import Live
from websockets.sync.client import connect as ws_connect

from milpo.async_inference import (
    async_call_descriptor,
    async_classify_batch,
    async_classify_target_only,
    async_classify_with_features,
    get_async_client,
)
from milpo.bandits import successive_rejects
from milpo.config import MODEL_CRITIC, MODEL_EDITOR, MODEL_PARAPHRASER
from milpo.db import (
    format_descriptions,
    get_active_prompt,
    get_conn,
    insert_prompt_version,
    load_categories,
    load_dev_annotations,
    load_dev_posts,
    load_posts_media,
    load_post_media,
    load_strategies,
    load_visual_formats,
    promote_prompt,
    store_api_call,
    store_beam_candidate,
    store_gradient,
    store_prediction,
    store_rewrite_log,
    update_beam_candidate_eval,
    update_beam_candidate_sr,
)
from milpo.eval import accuracy
from milpo.errors import LLMCallError
from milpo.gcs import sign_all_posts_media
from milpo.inference import ApiCallLog, PipelineResult, PostInput, PromptSet, classify_post
from milpo.router import route as route_post
from milpo.schemas import DescriptorFeatures
from milpo.rewriter import (
    ErrorCase,
    ProtegiStepResult,
    protegi_step,
)

# Les 6 couples (agent, scope) qui pilotent l'optimisation MILPO.
# Source de vérité du contenu : BDD (migration 006_seed_prompts_v0.sql).
PROMPT_KEYS: list[tuple[str, str | None]] = [
    ("descriptor", "FEED"),
    ("descriptor", "REELS"),
    ("category", None),
    ("visual_format", "FEED"),
    ("visual_format", "REELS"),
    ("strategy", None),
]

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("milpo").setLevel(logging.WARNING)
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
    scope: str | None = None


@dataclass
class MultiEvalResult:
    """Résultats détaillés de la multi évaluation ProTeGi.

    matches_by_arm : {arm_id (= row id dans rewrite_beam_candidates ou
                      sentinelle INCUMBENT_ARM_ID = 0 pour l'incumbent):
                      list[bool] des matches sur eval_window posts}
    incumbent_records : à réinjecter dans all_matches
    incumbent_arm_id  : valeur sentinelle pour identifier l'incumbent
    """

    matches_by_arm: dict[int, list[bool]] = field(default_factory=dict)
    incumbent_records: list[MatchRecord] = field(default_factory=list)
    incumbent_arm_id: int = 0


@dataclass
class RewriteOutcome:
    """Résultat d'une tentative de rewrite ProTeGi."""

    triggered: bool                       # True si rewrite tenté
    promoted: bool                        # True si promotion validée
    winner_db_id: int | None              # id du winner promu (ou tenté)
    incumbent_acc: float | None
    candidate_acc: float | None           # accuracy du winner
    eval_window_consumed: int             # cursor advance après éval
    incumbent_records: list[MatchRecord]  # à réinjecter dans all_matches
    failed: bool = False                  # True si LLMCallError


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
            config = COALESCE(config, '{}'::jsonb) || jsonb_build_object('failure_reason', %s::text)
        WHERE id = %s
        """,
        (
            metrics["accuracy_category"],
            metrics["accuracy_visual_format"],
            metrics["accuracy_strategy"],
            metrics["prompt_iterations"],
            metrics["total_api_calls"],
            metrics.get("total_cost_usd"),
            error_message[:1000] or "unknown error",
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


def evaluate_result_and_store(
    post: PostInput,
    result: PipelineResult,
    annotation: dict,
    prompt_state: PromptState,
    conn,
    run_id: int,
    call_type: str = "classification",
) -> tuple[list[ErrorCase], list[MatchRecord]]:
    """Évalue un résultat déjà classifié et stocke en BDD."""
    scope = post.media_product_type
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
        matches.append(MatchRecord(axis=axis, match=is_match, cursor=0, scope=scope))

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

    return errors, matches


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


# ── Helpers ProTeGi ───────────────────────────────────────────


def _build_all_descriptions_for_target(
    conn,
    target_agent: str,
    target_scope: str | None,
) -> str:
    """Charge les descriptions taxonomiques pertinentes pour la cible du rewrite.

    Pour le descripteur : toutes les taxonomies (vf scope + cats + strats).
    Pour un classifieur : uniquement la taxonomie de l'axe ciblé.
    """
    effective_scope = target_scope or "FEED"  # fallback pour category/strategy
    if target_agent == "descriptor":
        return (
            "## Formats visuels\n\n"
            + format_descriptions(load_visual_formats(conn, effective_scope))
            + "\n\n## Catégories\n\n"
            + format_descriptions(load_categories(conn))
            + "\n\n## Stratégies\n\n"
            + format_descriptions(load_strategies(conn))
        )
    if target_agent == "visual_format":
        return format_descriptions(load_visual_formats(conn, effective_scope))
    if target_agent == "category":
        return format_descriptions(load_categories(conn))
    if target_agent == "strategy":
        return format_descriptions(load_strategies(conn))
    raise ValueError(f"target_agent inconnu: {target_agent}")


# ── Multi-évaluation pour le mode protegi ─────────────────────


async def async_multi_evaluate(
    eval_posts: list[PostInput],
    annotations: dict[int, dict],
    start_cursor: int,
    base_prompt_state: PromptState,
    target_agent: str,
    target_scope: str | None,
    arms: dict[int, tuple[str, int]],
    incumbent_arm_id: int,
    conn,
    run_id: int,
    labels_by_scope: dict[str, dict[str, list[str]]],
    max_concurrent_api: int = 20,
    on_progress: Callable[[int, int], None] | None = None,
) -> MultiEvalResult:
    """Évalue N bras (incumbent + candidats) sur eval_posts en parallèle.

    Optimisé : le descripteur est appelé UNE SEULE FOIS par post (les features
    sont partagées entre les bras). Seuls les classifieurs sont dupliqués par bras.
    Gain : ~600 calls → ~210 calls pour 5 bras × 30 posts.
    """
    if incumbent_arm_id not in arms:
        raise ValueError(
            f"multi_evaluate: incumbent_arm_id={incumbent_arm_id} absent de arms"
        )

    # Construire un PromptState par bras
    arm_states: dict[int, PromptState] = {}
    for arm_id, (instructions, db_id) in arms.items():
        arm_states[arm_id] = PromptState(
            instructions={
                **base_prompt_state.instructions,
                (target_agent, target_scope): instructions,
            },
            db_ids={
                **base_prompt_state.db_ids,
                (target_agent, target_scope): db_id,
            },
            versions=base_prompt_state.versions.copy(),
        )

    # Séparer posts par cas : scope-mismatch (incumbent seul) vs normal (tous les bras)
    mismatch_posts: list[tuple[int, PostInput, dict]] = []
    normal_posts: list[tuple[int, PostInput, dict]] = []

    for offset, post in enumerate(eval_posts):
        annotation = annotations.get(post.ig_media_id)
        if not annotation:
            continue
        scope = post.media_product_type
        if target_scope is not None and scope != target_scope:
            mismatch_posts.append((offset, post, annotation))
        else:
            normal_posts.append((offset, post, annotation))

    matches_by_arm: dict[int, list[bool]] = {arm_id: [] for arm_id in arms}
    incumbent_records: list[MatchRecord] = []

    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent_api)

    # Pré-calcul des prompts par (arm_id, scope)
    scopes_needed = {post.media_product_type for _, post, _ in mismatch_posts + normal_posts}
    prompts_cache: dict[tuple[int, str], PromptSet] = {}
    for arm_id in arms:
        for sc in scopes_needed:
            prompts_cache[(arm_id, sc)] = build_prompts_from_state(arm_states[arm_id], conn, sc)

    # ── Phase 1 : pré-calculer les features descripteur (1 appel par post) ──
    async def _describe_post(post: PostInput):
        scope = post.media_product_type
        inc_prompts = prompts_cache[(incumbent_arm_id, scope)]
        routing = route_post(scope)
        features, desc_log = await async_call_descriptor(
            client=client,
            model=routing["model_descriptor"],
            media_urls=post.media_urls,
            media_types=post.media_types,
            caption=post.caption,
            instructions=inc_prompts.descriptor_instructions,
            descriptions_taxonomiques=inc_prompts.descriptor_descriptions,
            semaphore=semaphore,
        )
        return (post.ig_media_id, features, desc_log)

    all_posts = [post for _, post, _ in mismatch_posts + normal_posts]
    desc_results = await asyncio.gather(
        *[_describe_post(p) for p in all_posts],
        return_exceptions=True,
    )

    # Indexer les features par post id
    features_by_id: dict[int, tuple[DescriptorFeatures, ApiCallLog]] = {}
    for r in desc_results:
        if isinstance(r, Exception):
            log.warning("Descripteur échoué dans multi_evaluate: %s", r)
            continue
        post_id, features, desc_log = r
        features_by_id[post_id] = (features, desc_log)

    # ── Phase 2 : classifier avec features pré-calculées ──
    # Résoudre les labels/instructions cible pour les candidats
    _target_scope_for_labels = target_scope or "FEED"
    target_labels_list = labels_by_scope[_target_scope_for_labels][target_agent]

    # Mismatch : incumbent seul, pipeline complet (3 classifieurs)
    async def classify_mismatch(offset: int, post: PostInput, annotation: dict):
        if post.ig_media_id not in features_by_id:
            return None
        features, desc_log = features_by_id[post.ig_media_id]
        scope = post.media_product_type
        labels = labels_by_scope[scope]
        prompts = prompts_cache[(incumbent_arm_id, scope)]
        result = await async_classify_with_features(
            post, features, desc_log, prompts,
            labels["category"], labels["visual_format"], labels["strategy"],
            client, semaphore,
        )
        return (offset, post, annotation, incumbent_arm_id, result, True, False)

    # Normal-incumbent : pipeline complet (3 classifieurs, pour métriques globales)
    async def classify_incumbent(offset: int, post: PostInput, annotation: dict):
        if post.ig_media_id not in features_by_id:
            return None
        features, desc_log = features_by_id[post.ig_media_id]
        scope = post.media_product_type
        labels = labels_by_scope[scope]
        prompts = prompts_cache[(incumbent_arm_id, scope)]
        result = await async_classify_with_features(
            post, features, desc_log, prompts,
            labels["category"], labels["visual_format"], labels["strategy"],
            client, semaphore,
        )
        return (offset, post, annotation, incumbent_arm_id, result, False, False)

    # Normal-candidat : UN SEUL classifieur (l'axe cible)
    async def classify_candidate(offset: int, post: PostInput, annotation: dict, arm_id: int):
        if post.ig_media_id not in features_by_id:
            return None
        features, _ = features_by_id[post.ig_media_id]
        scope = post.media_product_type
        prompts = prompts_cache[(arm_id, scope)]
        # Résoudre les instructions/descriptions de l'axe cible pour ce bras
        target_instr = {
            "category": prompts.category_instructions,
            "visual_format": prompts.visual_format_instructions,
            "strategy": prompts.strategy_instructions,
        }[target_agent]
        target_desc = {
            "category": prompts.category_descriptions,
            "visual_format": prompts.visual_format_descriptions,
            "strategy": prompts.strategy_descriptions,
        }[target_agent]
        label, clf_log = await async_classify_target_only(
            post, features, target_agent, target_labels_list,
            target_instr, target_desc, client, semaphore,
        )
        # Retourner le label cible + api_call (pas un PipelineResult complet)
        return (offset, post, annotation, arm_id, label, clf_log, True)  # True = target_only

    tasks = []
    for offset, post, annotation in mismatch_posts:
        tasks.append(classify_mismatch(offset, post, annotation))
    for offset, post, annotation in normal_posts:
        tasks.append(classify_incumbent(offset, post, annotation))
        for arm_id in arms:
            if arm_id == incumbent_arm_id:
                continue  # déjà traité par classify_incumbent
            tasks.append(classify_candidate(offset, post, annotation, arm_id))

    eval_done = 0
    eval_total = len(tasks) + len(all_posts)  # descripteurs + classifieurs

    # Compter les descripteurs déjà terminés
    eval_done = len([r for r in desc_results if not isinstance(r, Exception)])
    if on_progress:
        on_progress(eval_done, eval_total)

    async def _track(coro):
        nonlocal eval_done
        result = await coro
        eval_done += 1
        if on_progress:
            on_progress(eval_done, eval_total)
        return result

    results = await asyncio.gather(*[_track(t) for t in tasks], return_exceptions=True)

    # ── 3. Post-traitement séquentiel (stockage BDD + agrégation matches) ──
    # Deux formats de résultats :
    #   incumbent/mismatch : (offset, post, ann, arm_id, PipelineResult, is_mismatch, False)
    #   candidat target_only : (offset, post, ann, arm_id, label_str, clf_log, True)
    results_by_offset: dict[int, list] = defaultdict(list)
    for r in results:
        if isinstance(r, Exception):
            log.warning("Classification échouée dans multi_evaluate: %s", r)
            continue
        if r is None:
            continue
        results_by_offset[r[0]].append(r)

    for offset in sorted(results_by_offset.keys()):
        items = results_by_offset[offset]
        if not items:
            continue

        post = items[0][1]
        annotation = items[0][2]
        scope = post.media_product_type

        for item in items:
            arm_id = item[3]
            is_target_only = item[6]

            if is_target_only:
                # Candidat : un seul label cible (pas de PipelineResult)
                label = item[4]
                clf_log = item[5]
                is_match = label == annotation[target_agent]
                matches_by_arm[arm_id].append(is_match)

                state = arm_states[arm_id]
                store_api_call(
                    conn, "evaluation", target_agent, clf_log.model,
                    state.db_ids.get((target_agent, target_scope)),
                    post.ig_media_id,
                    clf_log.input_tokens, clf_log.output_tokens,
                    None, clf_log.latency_ms, run_id,
                )
                store_prediction(
                    conn, post.ig_media_id, target_agent,
                    state.db_ids.get((target_agent, target_scope)),
                    label,
                    simulation_run_id=run_id,
                )
            else:
                # Incumbent ou mismatch : PipelineResult complet
                result = item[4]
                is_mismatch = item[5]

                if is_mismatch:
                    # Mismatch : propager les mêmes matches à TOUS les bras
                    metric_matches = _target_metric_matches(result, annotation, target_agent)
                    for aid in arms:
                        matches_by_arm[aid].extend(metric_matches)
                else:
                    # Incumbent normal
                    metric_matches = _target_metric_matches(result, annotation, target_agent)
                    matches_by_arm[arm_id].extend(metric_matches)

                # Persister les 3 axes + api_calls (incumbent)
                state = arm_states[arm_id]
                for call in result.api_calls:
                    scope_key = scope if call.agent in ("descriptor", "visual_format") else None
                    pid = (
                        state.db_ids.get((call.agent, scope_key))
                        or state.db_ids.get((call.agent, None))
                    )
                    store_api_call(
                        conn, "evaluation", call.agent, call.model, pid,
                        post.ig_media_id, call.input_tokens, call.output_tokens,
                        None, call.latency_ms, run_id,
                    )
                for axis in ("category", "visual_format", "strategy"):
                    scope_key = scope if axis in ("visual_format", "descriptor") else None
                    pid = (
                        state.db_ids.get((axis, scope_key))
                        or state.db_ids.get((axis, None))
                    )
                    store_prediction(
                        conn, post.ig_media_id, axis, pid,
                        getattr(result.prediction, axis),
                        simulation_run_id=run_id,
                    )
                    incumbent_records.append(MatchRecord(
                        axis=axis,
                        match=getattr(result.prediction, axis) == annotation[axis],
                        cursor=start_cursor + offset,
                        scope=scope,
                    ))

    return MultiEvalResult(
        matches_by_arm=matches_by_arm,
        incumbent_records=incumbent_records,
        incumbent_arm_id=incumbent_arm_id,
    )


# ── Helpers de persistance ProTeGi ────────────────────────────


@dataclass
class ProtegiArm:
    """Un bras du bandit ProTeGi (edit ou paraphrase) prêt à être évalué."""

    beam_row_id: int          # row id dans rewrite_beam_candidates
    prompt_db_id: int         # row id dans prompt_versions
    version: int
    kind: str                 # 'edit' | 'paraphrase'
    instructions: str


def _persist_protegi_artifacts(
    conn,
    *,
    run_id: int,
    iteration: int,
    target_agent: str,
    target_scope: str | None,
    incumbent_db_id: int,
    incumbent_version: int,
    step_result: ProtegiStepResult,
    p: int,
) -> tuple[int, list[ProtegiArm]]:
    """Persiste le gradient + insère les prompt_versions des candidats + crée
    les rows beam_candidates.

    Retourne (gradient_id, list[ProtegiArm]) pour les bras qui iront dans le
    bandit (edits si p<=1, paraphrases si p>=2). Les edits sont toujours
    matérialisés en BDD pour traçabilité même quand p>=2 — ils servent alors
    de parent_prompt_id pour leurs paraphrases.
    """
    # 1. Persister le gradient
    gradient_id = store_gradient(
        conn,
        simulation_run_id=run_id,
        iteration=iteration,
        target_agent=target_agent,
        target_scope=target_scope,
        prompt_id=incumbent_db_id,
        gradient_text=step_result.gradient.gradient_text,
        n_critiques=step_result.gradient.n_critiques,
        model=step_result.gradient.model,
        input_tokens=step_result.gradient.input_tokens,
        output_tokens=step_result.gradient.output_tokens,
        latency_ms=step_result.gradient.latency_ms,
    )

    # 2. Insérer les prompt_versions pour chaque edit candidate
    next_version = incumbent_version + 1
    edit_arms: list[ProtegiArm] = []

    for i, ec in enumerate(step_result.edit.candidates):
        edit_version = next_version + i
        edit_id = insert_prompt_version(
            conn, target_agent, target_scope, edit_version,
            ec.new_instructions,
            status="draft",
            parent_id=incumbent_db_id,
            simulation_run_id=run_id,
        )
        beam_row = store_beam_candidate(
            conn,
            simulation_run_id=run_id,
            iteration=iteration,
            target_agent=target_agent,
            target_scope=target_scope,
            parent_prompt_id=incumbent_db_id,
            candidate_prompt_id=edit_id,
            gradient_id=gradient_id,
            generation_kind="edit",
        )
        edit_arms.append(ProtegiArm(
            beam_row_id=beam_row,
            prompt_db_id=edit_id,
            version=edit_version,
            kind="edit",
            instructions=ec.new_instructions,
        ))

    # 3. Si p >= 2, paraphraser et insérer
    if p >= 2 and step_result.paraphrases:
        para_arms: list[ProtegiArm] = []
        para_offset = next_version + len(edit_arms)
        idx = 0
        for i, pp_result in enumerate(step_result.paraphrases):
            edit = edit_arms[i]
            for paraphrase_text in pp_result.paraphrases:
                pp_version = para_offset + idx
                pp_id = insert_prompt_version(
                    conn, target_agent, target_scope, pp_version,
                    paraphrase_text,
                    status="draft",
                    parent_id=edit.prompt_db_id,
                    simulation_run_id=run_id,
                )
                pp_beam_row = store_beam_candidate(
                    conn,
                    simulation_run_id=run_id,
                    iteration=iteration,
                    target_agent=target_agent,
                    target_scope=target_scope,
                    parent_prompt_id=edit.prompt_db_id,
                    candidate_prompt_id=pp_id,
                    gradient_id=gradient_id,
                    generation_kind="paraphrase",
                )
                para_arms.append(ProtegiArm(
                    beam_row_id=pp_beam_row,
                    prompt_db_id=pp_id,
                    version=pp_version,
                    kind="paraphrase",
                    instructions=paraphrase_text,
                ))
                idx += 1
        return gradient_id, para_arms

    return gradient_id, edit_arms


# ── Tentative de rewrite (boucle ProTeGi) ─────────────────────


# Sentinelle pour identifier l'incumbent dans multi_evaluate.
INCUMBENT_ARM_ID = 0


async def run_protegi_rewrite(
    args,
    conn,
    run_id: int,
    rewrite_count: int,
    target_agent: str,
    target_scope: str | None,
    target_errors: list[ErrorCase],
    prompt_state: PromptState,
    eval_posts: list[PostInput],
    eval_start_cursor: int,
    annotations: dict[int, dict],
    labels_by_scope: dict[str, dict[str, list[str]]],
    on_status: Callable[[str], None] | None = None,
) -> RewriteOutcome:
    """Boucle ProTeGi (Pryzant et al. 2023, EMNLP) : gradient + edit + paraphrase + Successive Rejects.

    1. compute_textual_gradient (LLM_∇) → gradient persisté
    2. apply_gradient_edit (LLM_δ) → c candidats édités
    3. Si p>=2 : paraphrase_candidate (LLM_mc) → c×p paraphrases
    4. multi_evaluate sur eval_posts en parallèle
    5. successive_rejects (Audibert & Bubeck 2010) → winner
    6. promote/rollback selon delta vs incumbent
    """
    current_key = (target_agent, target_scope)
    incumbent_db_id = prompt_state.db_ids[current_key]
    incumbent_version = prompt_state.versions[current_key]
    incumbent_instructions = prompt_state.instructions[current_key]

    all_descs = _build_all_descriptions_for_target(conn, target_agent, target_scope)

    log.info(
        "[REWRITE #%d] (protegi) gradient → edit → %s eval × %d posts",
        rewrite_count,
        "paraphrase →" if args.protegi_p >= 2 else "(skip paraphrase) →",
        len(eval_posts),
    )

    try:
        step_result = protegi_step(
            target_agent=target_agent,
            target_scope=target_scope,
            current_instructions=incumbent_instructions,
            errors=target_errors,
            all_descriptions=all_descs,
            m=args.protegi_m,
            c=args.protegi_c,
            p=args.protegi_p,
            on_phase=on_status,
        )
    except LLMCallError as exc:
        log.warning("[REWRITE #%d] (protegi) Échec %s/%s : %s",
                    rewrite_count, target_agent, target_scope or "all", exc)
        return RewriteOutcome(
            triggered=True, promoted=False, winner_db_id=None,
            incumbent_acc=None, candidate_acc=None,
            eval_window_consumed=0, incumbent_records=[],
            failed=True,
        )

    # Logger les coûts des appels LLM ProTeGi
    store_api_call(
        conn, "rewrite", target_agent, step_result.gradient.model,
        incumbent_db_id, None,
        step_result.gradient.input_tokens, step_result.gradient.output_tokens,
        None, step_result.gradient.latency_ms, run_id,
    )
    store_api_call(
        conn, "rewrite", target_agent, step_result.edit.model,
        incumbent_db_id, None,
        step_result.edit.input_tokens, step_result.edit.output_tokens,
        None, step_result.edit.latency_ms, run_id,
    )
    for pp in step_result.paraphrases:
        store_api_call(
            conn, "rewrite", target_agent, pp.model,
            incumbent_db_id, None,
            pp.input_tokens, pp.output_tokens,
            None, pp.latency_ms, run_id,
        )

    # Persister gradient + insérer prompt_versions + créer beam_candidates
    gradient_id, arms_to_eval = _persist_protegi_artifacts(
        conn,
        run_id=run_id,
        iteration=rewrite_count,
        target_agent=target_agent,
        target_scope=target_scope,
        incumbent_db_id=incumbent_db_id,
        incumbent_version=incumbent_version,
        step_result=step_result,
        p=args.protegi_p,
    )

    if not arms_to_eval:
        log.warning("[REWRITE #%d] (protegi) aucun candidat à évaluer.", rewrite_count)
        return RewriteOutcome(
            triggered=True, promoted=False, winner_db_id=None,
            incumbent_acc=None, candidate_acc=None,
            eval_window_consumed=0, incumbent_records=[],
            failed=True,
        )

    # Construire les bras pour multi_evaluate
    # arm_id = beam_row_id du candidat (jamais 0). L'incumbent prend INCUMBENT_ARM_ID = 0.
    arms: dict[int, tuple[str, int]] = {
        INCUMBENT_ARM_ID: (incumbent_instructions, incumbent_db_id),
    }
    for arm in arms_to_eval:
        arms[arm.beam_row_id] = (arm.instructions, arm.prompt_db_id)

    log.info("[REWRITE #%d] (protegi) multi_evaluate %d bras × %d posts",
             rewrite_count, len(arms), len(eval_posts))

    if on_status:
        on_status(f"eval {len(arms)} bras \u00d7 {len(eval_posts)} posts...")

    def _on_eval_progress(done: int, total: int):
        if on_status:
            on_status(f"eval {done}/{total}")

    try:
        multi_result = await async_multi_evaluate(
            eval_posts=eval_posts,
            annotations=annotations,
            start_cursor=eval_start_cursor,
            base_prompt_state=prompt_state,
            target_agent=target_agent,
            target_scope=target_scope,
            arms=arms,
            incumbent_arm_id=INCUMBENT_ARM_ID,
            conn=conn,
            run_id=run_id,
            labels_by_scope=labels_by_scope,
            on_progress=_on_eval_progress,
        )
    except LLMCallError as exc:
        log.warning("[REWRITE #%d] (protegi) Échec multi_evaluate : %s", rewrite_count, exc)
        return RewriteOutcome(
            triggered=True, promoted=False, winner_db_id=None,
            incumbent_acc=None, candidate_acc=None,
            eval_window_consumed=0, incumbent_records=[],
            failed=True,
        )

    # Mettre à jour eval_accuracy pour chaque candidat (pas l'incumbent)
    incumbent_matches = multi_result.matches_by_arm[INCUMBENT_ARM_ID]
    inc_acc = accuracy(incumbent_matches)

    candidate_arms = {
        arm_id: matches
        for arm_id, matches in multi_result.matches_by_arm.items()
        if arm_id != INCUMBENT_ARM_ID
    }
    for beam_row_id, matches in candidate_arms.items():
        update_beam_candidate_eval(
            conn,
            candidate_row_id=beam_row_id,
            eval_accuracy=accuracy(matches),
            eval_sample_size=len(matches),
        )

    # Successive Rejects sur les candidats (l'incumbent n'est pas un bras du SR :
    # il sert de référence pour la décision promote/rollback ensuite).
    sr_input = candidate_arms
    if not sr_input:
        log.warning("[REWRITE #%d] (protegi) aucun bras candidat évaluable.", rewrite_count)
        return RewriteOutcome(
            triggered=True, promoted=False, winner_db_id=None,
            incumbent_acc=inc_acc, candidate_acc=None,
            eval_window_consumed=len(eval_posts),
            incumbent_records=multi_result.incumbent_records,
            failed=False,
        )

    if on_status:
        on_status("bandit SR...")
    sr_result = successive_rejects(sr_input, k=1)
    winner_beam_row_id = sr_result.winner_arm_id
    winner_acc = sr_result.winner_score
    winner_db_id = arms[winner_beam_row_id][1]

    # Persister les résultats SR par bras
    for phase in sr_result.phases:
        update_beam_candidate_sr(
            conn,
            candidate_row_id=phase.eliminated_arm_id,
            sr_phase=phase.phase,
            sr_eliminated=True,
            is_winner=False,
        )
    update_beam_candidate_sr(
        conn,
        candidate_row_id=winner_beam_row_id,
        sr_phase=None,
        sr_eliminated=False,
        is_winner=True,
    )

    delta_actual = winner_acc - inc_acc
    promoted = winner_acc >= inc_acc + args.delta
    if args.no_rollback:
        promoted = winner_acc > inc_acc

    # Log rewrite (winner = candidat post-SR)
    store_rewrite_log(
        conn,
        prompt_before_id=incumbent_db_id,
        prompt_after_id=winner_db_id,
        error_batch=[{
            "axis": e.axis,
            "predicted": e.predicted,
            "expected": e.expected,
            "ig_media_id": e.ig_media_id,
            "post_scope": e.post_scope,
        } for e in target_errors],
        rewriter_reasoning=(
            f"[protegi] gradient_id={gradient_id} "
            f"({step_result.gradient.n_critiques} critiques) | "
            f"{len(arms_to_eval)} candidats évalués, SR winner = beam_row_id={winner_beam_row_id}"
        ),
        accepted=promoted,
        simulation_run_id=run_id,
        target_agent=target_agent,
        target_scope=target_scope,
        incumbent_accuracy=inc_acc,
        candidate_accuracy=winner_acc,
        eval_sample_size=len(eval_posts),
        iteration=rewrite_count,
    )

    if promoted:
        promote_prompt(conn, target_agent, target_scope, winner_db_id)
        # Récupère la version depuis arms_to_eval (évite roundtrip BDD)
        new_version = next(
            (a.version for a in arms_to_eval if a.beam_row_id == winner_beam_row_id),
            incumbent_version + 1,
        )
        prompt_state.instructions[current_key] = arms[winner_beam_row_id][0]
        prompt_state.db_ids[current_key] = winner_db_id
        prompt_state.versions[current_key] = new_version
        log.info("[REWRITE #%d] (protegi) Incumbent %.1f%% vs Winner %.1f%% (Δ=+%.1f%%)",
                 rewrite_count, inc_acc * 100, winner_acc * 100, delta_actual * 100)
        log.info("[REWRITE #%d] >>> PROMOTED (v%d → v%d %s/%s) <<<",
                 rewrite_count, incumbent_version, new_version,
                 target_agent, target_scope or "all")
    else:
        log.info("[REWRITE #%d] (protegi) Incumbent %.1f%% vs Winner %.1f%% (Δ=%.1f%%)",
                 rewrite_count, inc_acc * 100, winner_acc * 100, delta_actual * 100)
        log.info("[REWRITE #%d] <<< ROLLBACK <<<", rewrite_count)

    return RewriteOutcome(
        triggered=True,
        promoted=promoted,
        winner_db_id=winner_db_id,
        incumbent_acc=inc_acc,
        candidate_acc=winner_acc,
        eval_window_consumed=len(eval_posts),
        incumbent_records=multi_result.incumbent_records,
        failed=False,
    )


# ── Display (Rich Live TUI) ──────────────────────────────────

from milpo.tui import SimulationDisplay

# ── WebSocket télémétrie ─────────────────────────────────────

_ws = None
_init_t0 = 0.0
_init_stage = ""
_init_stage_t0 = 0.0


def init_telemetry():
    """Connecte au WS server de la TUI TypeScript avec retry."""
    global _ws
    host = os.environ.get("MILPO_WS_HOST", "127.0.0.1")
    port = os.environ.get("MILPO_WS_PORT")
    if port is None:
        # Pas de TUI — mode standalone, pas de télémétrie
        return
    for attempt in range(5):
        try:
            _ws = ws_connect(f"ws://{host}:{port}")
            return
        except (ConnectionRefusedError, OSError):
            if attempt < 4:
                time.sleep(0.5)
    log.warning(
        "Impossible de se connecter au WS server TUI sur %s:%s — télémétrie désactivée",
        host,
        port,
    )


def emit_telemetry(display: SimulationDisplay):
    """Envoie l'état complet au WS server."""
    if _ws is not None:
        try:
            _ws.send(json.dumps(display.to_json()))
        except Exception:
            pass


def _reset_init_telemetry():
    global _init_t0, _init_stage, _init_stage_t0
    _init_t0 = time.monotonic()
    _init_stage = ""
    _init_stage_t0 = _init_t0


def _emit_init_status(
    phase: str,
    *,
    stage: str | None = None,
    done: int | None = None,
    total: int | None = None,
    unit: str | None = None,
):
    """Envoie un message d'initialisation léger à la TUI (avant que le display existe)."""
    global _init_stage, _init_stage_t0
    if _ws is not None:
        try:
            now = time.monotonic()
            if stage is not None and stage != _init_stage:
                _init_stage = stage
                _init_stage_t0 = now

            payload: dict[str, object] = {"init": True, "phase": phase}
            if stage is not None:
                payload["stage"] = stage
            if done is not None:
                payload["done"] = done
            if total is not None:
                payload["total"] = total
            if unit is not None:
                payload["unit"] = unit
            payload["elapsedSec"] = round(now - _init_t0, 1)
            payload["stageElapsedSec"] = round(now - _init_stage_t0, 1)
            if done is not None and total is not None and done > 0:
                elapsed = max(now - _init_stage_t0, 1e-6)
                rate = done / elapsed
                payload["rate"] = round(rate, 2)
                if total >= done and rate > 0:
                    payload["etaSec"] = round((total - done) / rate, 1)
            _ws.send(json.dumps(payload))
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────

MICRO_BATCH_SIZE = 10  # Posts classifiés en parallèle entre les checks de trigger


async def main():
    parser = argparse.ArgumentParser(
        description="Simulation MILPO prequential — boucle ProTeGi (Pryzant et al. 2023)",
    )
    parser.add_argument("-B", "--batch-size", type=int, default=30)
    parser.add_argument("--delta", type=float, default=0.02)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--eval-window", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Pas de rewrite (B0-on-dev)")
    parser.add_argument("--no-rollback", action="store_true", help="Ablation A5")
    parser.add_argument("--limit", type=int, default=None, help="Nombre de posts max")
    parser.add_argument("--micro-batch", type=int, default=MICRO_BATCH_SIZE,
                        help="Posts classifiés en parallèle (défaut 10)")
    # ── Hyperparams ProTeGi ────────────────────────────────────
    parser.add_argument("-m", "--protegi-m", type=int, default=3,
                        help="critiques par appel critic LLM_∇ (paper m=4, défaut 3)")
    parser.add_argument("-c", "--protegi-c", type=int, default=4,
                        help="candidats édités par appel editor LLM_δ (paper c=8, défaut 4)")
    parser.add_argument("-p", "--protegi-p", type=int, default=1,
                        help="paraphrases par candidat LLM_mc (paper p=2, défaut 1 = skip étape MC)")
    parser.add_argument("--protegi-paper-defaults", action="store_true",
                        help="Convenience : applique m=4 c=8 p=2 (hyperparams paper Pryzant et al.)")
    args = parser.parse_args()

    if args.protegi_paper_defaults:
        args.protegi_m, args.protegi_c, args.protegi_p = 4, 8, 2
        log.info("[PROTEGI] paper defaults appliqués : m=4 c=8 p=2")

    conn = get_conn()
    run_id: int | None = None
    t0 = time.monotonic()
    matches_by_axis = {"category": 0, "visual_format": 0, "strategy": 0}
    n_processed = 0
    total_api_calls = 0
    live_cost_estimate_usd = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    matches_by_scope: dict[str, dict[str, int]] = {
        "FEED": {"category": 0, "visual_format": 0, "strategy": 0},
        "REELS": {"category": 0, "visual_format": 0, "strategy": 0},
    }
    n_by_scope: dict[str, int] = {"FEED": 0, "REELS": 0}
    rewrite_count = 0
    promoted_rewrite_count = 0
    rollback_rewrite_count = 0
    skipped_rewrite_count = 0
    skipped_classification_posts = 0
    failed_rewrite_attempts = 0

    # Connecter la télémétrie WS
    init_telemetry()
    _reset_init_telemetry()

    # Silence TOUT le logging pendant l'exécution (la TUI remplace les logs)
    import warnings
    warnings.filterwarnings("ignore")
    logging.getLogger().setLevel(logging.ERROR)

    # Envoyer un signal "init" immédiat à la TUI pour éviter le "waiting" prolongé
    _emit_init_status("loading posts & annotations...", stage="bootstrap")

    try:
        # ── 1-5. Setup ──
        raw_posts = load_dev_posts(conn, limit=args.limit)
        annotations = load_dev_annotations(conn)
        annotated_ids = set(annotations.keys())
        raw_posts = [p for p in raw_posts if p["ig_media_id"] in annotated_ids]
        if not raw_posts:
            console.print("[red]Aucun post annoté dans le split dev.[/red]")
            sys.exit(1)

        run_config: dict = {
            "name": f"MILPO_protegi_B{args.batch_size}"
                    + ("_dryrun" if args.dry_run else ""),
            "split": "dev",
            "batch_size": args.batch_size,
            "delta": args.delta,
            "patience": args.patience,
            "eval_window": args.eval_window,
            "dry_run": args.dry_run,
            "no_rollback": args.no_rollback,
            "protegi": {
                "m": args.protegi_m,
                "c": args.protegi_c,
                "p": args.protegi_p,
                "critic_model": MODEL_CRITIC,
                "editor_model": MODEL_EDITOR,
                "paraphraser_model": MODEL_PARAPHRASER,
            },
        }
        run_id = create_run(conn, run_config)

        def _on_sign_progress(phase: str, done: int, total: int):
            if phase == "loading_media":
                _emit_init_status(
                    f"loading media from DB ({done}/{total} posts)...",
                    stage="loading_media",
                    done=done,
                    total=total,
                    unit="posts",
                )
            elif phase == "collecting_urls":
                _emit_init_status(
                    f"collected {done} unique media URLs...",
                    stage="collecting_urls",
                    done=done,
                    total=total,
                    unit="urls",
                )
            else:
                _emit_init_status(
                    f"signing GCS URLs ({done}/{total})...",
                    stage="signing",
                    done=done,
                    total=total,
                    unit="urls",
                )

        _emit_init_status(
            f"loading media from DB (0/{len(raw_posts)} posts)...",
            stage="loading_media",
            done=0,
            total=len(raw_posts),
            unit="posts",
        )
        signed_by_post = sign_all_posts_media(
            raw_posts,
            load_post_media,
            conn,
            max_workers=20,
            load_all_media_fn=load_posts_media,
            on_progress=_on_sign_progress,
        )

        post_inputs: list[PostInput] = []
        for post in raw_posts:
            mid = post["ig_media_id"]
            signed = signed_by_post.get(mid, [])
            if not signed:
                continue
            post_inputs.append(PostInput(
                ig_media_id=mid,
                media_product_type=post["media_product_type"],
                media_urls=[u for u, _ in signed],
                media_types=[m for _, m in signed],
                caption=post["caption"],
            ))

        prompt_state = load_prompt_state_from_db(conn)

        # ── 6. Labels et descriptions par scope (cache) ──
        labels_by_scope: dict[str, dict[str, list[str]]] = {}
        for scope in ("FEED", "REELS"):
            labels_by_scope[scope] = build_labels(conn, scope)

        # ── 7. Boucle principale (async micro-batches + Rich Live TUI) ──
        error_buffer: list[ErrorCase] = []
        all_matches: list[MatchRecord] = []
        cursor = 0
        consecutive_failures = 0
        rewrites_stopped = False

        total = len(post_inputs)
        feed = sum(1 for p in post_inputs if p.media_product_type == "FEED")
        display = SimulationDisplay(run_id=run_id, total=total, batch_size=args.batch_size)
        display.add_event(f"Loaded {total} posts (FEED {feed} / REELS {total - feed})")
        display.add_event(
            f"Config B={args.batch_size} delta={args.delta*100:.0f}% "
            f"patience={args.patience} m={args.protegi_m} c={args.protegi_c} p={args.protegi_p}"
        )
        display.heartbeat("ready to classify")
        display.sync(
            cursor,
            n_processed,
            matches_by_axis,
            len(error_buffer),
            live_cost_estimate_usd,
            prompt_state.versions,
        )
        display.total_input_tokens = total_input_tokens
        display.total_output_tokens = total_output_tokens
        display.matches_by_scope = matches_by_scope
        display.n_by_scope = n_by_scope
        emit_telemetry(display)

        BATCH_TIMEOUT = 120  # secondes max par micro-batch avant skip

        with Live(display.build(), refresh_per_second=2, console=console, screen=True) as live:
          while cursor < total:
            # Construire les prompts par scope pour ce batch (basé sur prompt_state actuel)
            prompts_by_scope: dict[str, PromptSet] = {}
            for scope in ("FEED", "REELS"):
                prompts_by_scope[scope] = build_prompts_from_state(prompt_state, conn, scope)

            # Déterminer la taille du micro-batch
            batch_end = min(cursor + args.micro_batch, total)
            micro_batch = post_inputs[cursor:batch_end]

            # Classifier le micro-batch en parallèle (avec timeout global)
            display.heartbeat("classifying batch")
            def _on_post_done(done: int, total_batch: int, errors: int):
                display.heartbeat(f"post {cursor + done}/{total}")
                live.update(display.build()); emit_telemetry(display)

            try:
                batch_results = await asyncio.wait_for(
                    async_classify_batch(
                        posts=micro_batch,
                        prompts_by_scope=prompts_by_scope,
                        labels_by_scope=labels_by_scope,
                        max_concurrent_api=20,
                        max_concurrent_posts=args.micro_batch,
                        on_progress=_on_post_done,
                    ),
                    timeout=BATCH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                display.add_event(f"TIMEOUT batch {cursor}-{batch_end} ({BATCH_TIMEOUT}s) — skipped")
                skipped_classification_posts += len(micro_batch)
                cursor = batch_end
                live.update(display.build()); emit_telemetry(display)
                continue

            # Créer un mapping post -> result pour gérer les échecs
            results_by_id = {r.prediction.ig_media_id: r for r in batch_results}

            # Post-traitement séquentiel : stocker, évaluer, accumuler erreurs
            batch_cursor = cursor
            batch_skipped = 0
            for post in micro_batch:
                result = results_by_id.get(post.ig_media_id)
                if result is None:
                    skipped_classification_posts += 1
                    batch_skipped += 1
                    batch_cursor += 1
                    continue

                annotation = annotations[post.ig_media_id]
                errors, matches = evaluate_result_and_store(
                    post, result, annotation, prompt_state, conn, run_id,
                )

                for m in matches:
                    m.cursor = batch_cursor
                    all_matches.append(m)
                    if m.match:
                        matches_by_axis[m.axis] += 1
                        if m.scope:
                            matches_by_scope[m.scope][m.axis] += 1

                error_buffer.extend(errors)
                n_processed += 1
                n_by_scope[post.media_product_type] += 1
                total_api_calls += len(result.api_calls)
                total_input_tokens += result.total_input_tokens
                total_output_tokens += result.total_output_tokens
                live_cost_estimate_usd += sum(
                    c.input_tokens * 0.0001 / 1000 + c.output_tokens * 0.0003 / 1000
                    for c in result.api_calls
                )
                batch_cursor += 1

            cursor = batch_cursor
            if batch_skipped:
                display.skipped = skipped_classification_posts
                display.add_event(f"{batch_skipped} post(s) skipped (LLM error)")

            # Mettre à jour le display
            display.heartbeat(f"batch done {cursor}/{total}")
            display.sync(cursor, n_processed, matches_by_axis,
                         len(error_buffer), live_cost_estimate_usd, prompt_state.versions)
            display.total_input_tokens = total_input_tokens
            display.total_output_tokens = total_output_tokens
            display.matches_by_scope = matches_by_scope
            display.n_by_scope = n_by_scope
            display.update_rolling(all_matches)
            live.update(display.build()); emit_telemetry(display)

            # ── Trigger rewrite ? ──
            if (
                not args.dry_run
                and not rewrites_stopped
                and len(error_buffer) >= args.batch_size
            ):
                target_agent, target_scope = pick_rewrite_target(error_buffer)
                target_errors = get_target_errors(error_buffer, target_agent, target_scope)

                if not target_errors:
                    display.add_event(f"No exploitable errors for {target_agent}/{target_scope or 'all'}")
                    error_buffer.clear()
                    live.update(display.build()); emit_telemetry(display)
                    continue

                eval_end = min(cursor + args.eval_window, total)
                eval_posts = post_inputs[cursor:eval_end]

                if len(eval_posts) < 5:
                    skipped_rewrite_count += 1
                    display.add_event(f"Rewrite skipped (only {len(eval_posts)} posts left for eval)")
                    error_buffer.clear()
                    live.update(display.build()); emit_telemetry(display)
                    continue

                rewrite_count += 1
                display.phase = f"rewrite #{rewrite_count} — {target_agent}/{target_scope or 'all'}"
                display.add_event(
                    f"REWRITE #{rewrite_count} triggered — {target_agent}/{target_scope or 'all'} "
                    f"({len(target_errors)} errors)"
                )
                live.update(display.build()); emit_telemetry(display)

                def _on_rewrite_status(msg: str):
                    display.set_rewrite_phase(msg)
                    live.update(display.build()); emit_telemetry(display)

                outcome = await run_protegi_rewrite(
                    args, conn, run_id, rewrite_count,
                    target_agent, target_scope, target_errors,
                    prompt_state, eval_posts, cursor,
                    annotations, labels_by_scope,
                    on_status=_on_rewrite_status,
                )

                if outcome.failed:
                    failed_rewrite_attempts += 1
                    consecutive_failures += 1
                    display.add_event(f"REWRITE #{rewrite_count} FAILED")
                    error_buffer.clear()
                else:
                    if outcome.promoted:
                        promoted_rewrite_count += 1
                        consecutive_failures = 0
                        delta = (outcome.candidate_acc - outcome.incumbent_acc) * 100
                        display.add_event(
                            f"REWRITE #{rewrite_count} PROMOTED "
                            f"({outcome.incumbent_acc*100:.1f}% -> {outcome.candidate_acc*100:.1f}%, +{delta:.1f}%)"
                        )
                    else:
                        rollback_rewrite_count += 1
                        consecutive_failures += 1
                        delta = (outcome.candidate_acc - outcome.incumbent_acc) * 100
                        display.add_event(
                            f"REWRITE #{rewrite_count} ROLLBACK "
                            f"({outcome.incumbent_acc*100:.1f}% vs {outcome.candidate_acc*100:.1f}%, {delta:+.1f}%)"
                        )

                    for match_record in outcome.incumbent_records:
                        all_matches.append(match_record)
                        if match_record.match:
                            matches_by_axis[match_record.axis] += 1

                    # Accumuler scope depuis les incumbent_records
                    rewrite_scope_posts: dict[str, int] = {}
                    for mr in outcome.incumbent_records:
                        if mr.scope:
                            if mr.match:
                                matches_by_scope[mr.scope][mr.axis] += 1
                            rewrite_scope_posts[mr.scope] = rewrite_scope_posts.get(mr.scope, 0) + 1
                    for sc, cnt in rewrite_scope_posts.items():
                        n_by_scope[sc] += cnt // 3  # 3 axes par post

                    n_processed += outcome.eval_window_consumed
                    n_arms = 1 + (
                        args.protegi_c if args.protegi_p < 2
                        else args.protegi_c * args.protegi_p
                    )
                    total_api_calls += outcome.eval_window_consumed * 4 * n_arms
                    cursor += outcome.eval_window_consumed
                    error_buffer.clear()

                display.set_rewrite_phase(None)
                display.phase = "classification"
                display.rewrites_promoted = promoted_rewrite_count
                display.rewrites_rollback = rollback_rewrite_count
                display.sync(cursor, n_processed, matches_by_axis,
                             len(error_buffer), live_cost_estimate_usd, prompt_state.versions)
                display.total_input_tokens = total_input_tokens
                display.total_output_tokens = total_output_tokens
                display.matches_by_scope = matches_by_scope
                display.n_by_scope = n_by_scope
                live.update(display.build()); emit_telemetry(display)

                if consecutive_failures >= args.patience:
                    display.add_event(f"Patience exhausted ({consecutive_failures}/{args.patience})")
                    live.update(display.build()); emit_telemetry(display)
                    rewrites_stopped = True

        # Restaurer le logging pour le résumé final (hors Live / plein écran)
        logging.getLogger().setLevel(logging.INFO)
        log.setLevel(logging.INFO)

        metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
        finish_run(conn, run_id, metrics)

        elapsed = time.monotonic() - t0

        log.info("")
        log.info("=" * 60)
        log.info("  RÉSULTATS SIMULATION MILPO")
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
        log.info("  Rewrites       : %d tentés, %d promus, %d rollback, %d erreurs rewriter, %d skip eval",
                 rewrite_count,
                 promoted_rewrite_count,
                 rollback_rewrite_count,
                 failed_rewrite_attempts,
                 skipped_rewrite_count)
        log.info("")
        log.info("  Accuracy (tout le dev scoré) :")
        log.info("    Catégorie      : %.1f%% (%d/%d)", metrics["accuracy_category"] * 100, matches_by_axis["category"], n_processed)
        log.info("    Visual_format  : %.1f%% (%d/%d)", metrics["accuracy_visual_format"] * 100, matches_by_axis["visual_format"], n_processed)
        log.info("    Stratégie      : %.1f%% (%d/%d)", metrics["accuracy_strategy"] * 100, matches_by_axis["strategy"], n_processed)
        log.info("")
        log.info("  simulation_run_id = %d", run_id)
        log.info("✓ Simulation terminée")
    except BaseException as exc:
        print()
        log.setLevel(logging.INFO)
        log.exception("[FATAL] Simulation interrompue: %s", exc)
        if run_id is not None:
            try:
                conn.rollback()
                metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
                fail_run(conn, run_id, str(exc), metrics)
            except Exception as db_exc:
                log.warning("fail_run échoué: %s", db_exc)
            log.info("  simulation_run_id = %d", run_id)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
