"""Évaluation et persistance de la boucle de simulation MILPO."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable

from milpo.async_inference import (
    async_call_descriptor,
    async_classify_target_only,
    async_classify_with_features,
    get_async_client,
)
from milpo.db import store_api_call, store_prediction
from milpo.inference import ApiCallLog, PipelineResult, PostInput
from milpo.persistence import persist_api_calls, persist_pipeline_predictions, resolve_prompt_id
from milpo.prompting import build_prompt_set
from milpo.rewriter import ErrorCase
from milpo.router import route as route_post
from milpo.simulation.state import MatchRecord, MultiEvalResult, PromptState

log = logging.getLogger("simulation")

_desc_cache: dict[tuple[str, str], str] = {}


def _get_label_description(conn, axis: str, label: str) -> str:
    """Récupère la description d'un label depuis la BDD (avec cache)."""
    cache_key = (axis, label)
    if cache_key in _desc_cache:
        return _desc_cache[cache_key]

    table = {
        "category": "categories",
        "visual_format": "visual_formats",
        "strategy": "strategies",
    }[axis]
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

        matches.append(MatchRecord(axis=axis, match=is_match, cursor=0, scope=scope))

        if not is_match:
            errors.append(ErrorCase(
                ig_media_id=pred.ig_media_id,
                axis=axis,
                prompt_scope=scope if axis == "visual_format" else None,
                post_scope=scope,
                predicted=predicted,
                expected=expected,
                features_json=pred.features,
                caption=post.caption,
                desc_predicted=_get_label_description(conn, axis, predicted),
                desc_expected=_get_label_description(conn, axis, expected),
                confidence=result.confidences.get(axis, "unknown"),
            ))

    persist_pipeline_predictions(
        conn,
        post_id=pred.ig_media_id,
        scope=scope,
        result=result,
        prompt_ids=prompt_state.db_ids,
        run_id=run_id,
    )
    persist_api_calls(
        conn,
        post_id=pred.ig_media_id,
        scope=scope,
        api_calls=result.api_calls,
        prompt_ids=prompt_state.db_ids,
        run_id=run_id,
        call_type=call_type,
    )
    return errors, matches


def target_metric_matches(result: PipelineResult, annotation: dict, target_agent: str) -> list[bool]:
    """Retourne les matches pris en compte pour la promotion."""
    if target_agent == "descriptor":
        return [
            getattr(result.prediction, axis) == annotation[axis]
            for axis in ("category", "visual_format", "strategy")
        ]
    return [getattr(result.prediction, target_agent) == annotation[target_agent]]


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
    """Évalue N bras (incumbent + candidats) sur eval_posts en parallèle."""
    if incumbent_arm_id not in arms:
        raise ValueError(
            f"multi_evaluate: incumbent_arm_id={incumbent_arm_id} absent de arms"
        )

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

    mismatch_posts: list[tuple[int, PostInput, dict]] = []
    normal_posts: list[tuple[int, PostInput, dict]] = []
    for offset, post in enumerate(eval_posts):
        annotation = annotations.get(post.ig_media_id)
        if not annotation:
            continue
        if target_scope is not None and post.media_product_type != target_scope:
            mismatch_posts.append((offset, post, annotation))
        else:
            normal_posts.append((offset, post, annotation))

    matches_by_arm: dict[int, list[bool]] = {arm_id: [] for arm_id in arms}
    incumbent_records: list[MatchRecord] = []

    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent_api)
    scopes_needed = {post.media_product_type for _, post, _ in mismatch_posts + normal_posts}
    prompts_cache = {
        (arm_id, scope): build_prompt_set(conn, scope, arm_states[arm_id].instructions)
        for arm_id in arms
        for scope in scopes_needed
    }

    async def _describe_post(post: PostInput):
        scope = post.media_product_type
        prompts = prompts_cache[(incumbent_arm_id, scope)]
        routing = route_post(scope)
        features, desc_log = await async_call_descriptor(
            client=client,
            model=routing["model_descriptor"],
            media_urls=post.media_urls,
            media_types=post.media_types,
            caption=post.caption,
            instructions=prompts.descriptor_instructions,
            descriptions_taxonomiques=prompts.descriptor_descriptions,
            semaphore=semaphore,
        )
        return post.ig_media_id, features, desc_log

    all_posts = [post for _, post, _ in mismatch_posts + normal_posts]

    async def _describe_with_timeout(post: PostInput):
        return await asyncio.wait_for(_describe_post(post), timeout=120)

    desc_results = await asyncio.gather(
        *[_describe_with_timeout(post) for post in all_posts],
        return_exceptions=True,
    )

    features_by_id: dict[int, tuple[str, ApiCallLog]] = {}
    for item in desc_results:
        if isinstance(item, Exception):
            log.warning("Descripteur échoué dans multi_evaluate: %s", item)
            continue
        post_id, features, desc_log = item
        features_by_id[post_id] = (features, desc_log)

    is_descriptor_target = target_agent == "descriptor"
    target_labels_list = None if is_descriptor_target else labels_by_scope[target_scope or "FEED"][target_agent]

    async def classify_candidate_descriptor(offset: int, post: PostInput, annotation: dict, arm_id: int):
        """Re-describe + re-classify all 3 axes with candidate descriptor instructions."""
        prompts = prompts_cache[(arm_id, post.media_product_type)]
        routing = route_post(post.media_product_type)
        features, desc_log = await async_call_descriptor(
            client=client,
            model=routing["model_descriptor"],
            media_urls=post.media_urls,
            media_types=post.media_types,
            caption=post.caption,
            instructions=prompts.descriptor_instructions,
            descriptions_taxonomiques=prompts.descriptor_descriptions,
            semaphore=semaphore,
        )
        labels = labels_by_scope[post.media_product_type]
        result = await async_classify_with_features(
            post, features, desc_log, prompts,
            labels["category"], labels["visual_format"], labels["strategy"],
            client, semaphore,
        )
        return (offset, post, annotation, arm_id, result, False, False)

    async def classify_mismatch(offset: int, post: PostInput, annotation: dict):
        if post.ig_media_id not in features_by_id:
            return None
        features, desc_log = features_by_id[post.ig_media_id]
        labels = labels_by_scope[post.media_product_type]
        prompts = prompts_cache[(incumbent_arm_id, post.media_product_type)]
        result = await async_classify_with_features(
            post,
            features,
            desc_log,
            prompts,
            labels["category"],
            labels["visual_format"],
            labels["strategy"],
            client,
            semaphore,
        )
        return (offset, post, annotation, incumbent_arm_id, result, True, False)

    async def classify_incumbent(offset: int, post: PostInput, annotation: dict):
        if post.ig_media_id not in features_by_id:
            return None
        features, desc_log = features_by_id[post.ig_media_id]
        labels = labels_by_scope[post.media_product_type]
        prompts = prompts_cache[(incumbent_arm_id, post.media_product_type)]
        result = await async_classify_with_features(
            post,
            features,
            desc_log,
            prompts,
            labels["category"],
            labels["visual_format"],
            labels["strategy"],
            client,
            semaphore,
        )
        return (offset, post, annotation, incumbent_arm_id, result, False, False)

    async def classify_candidate(offset: int, post: PostInput, annotation: dict, arm_id: int):
        if post.ig_media_id not in features_by_id:
            return None
        features, _ = features_by_id[post.ig_media_id]
        prompts = prompts_cache[(arm_id, post.media_product_type)]
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
            post,
            features,
            target_agent,
            target_labels_list,
            target_instr,
            target_desc,
            client,
            semaphore,
        )
        return (offset, post, annotation, arm_id, label, clf_log, True)

    tasks = []
    for offset, post, annotation in mismatch_posts:
        tasks.append(classify_mismatch(offset, post, annotation))
    for offset, post, annotation in normal_posts:
        tasks.append(classify_incumbent(offset, post, annotation))
        for arm_id in arms:
            if arm_id != incumbent_arm_id:
                if is_descriptor_target:
                    tasks.append(classify_candidate_descriptor(offset, post, annotation, arm_id))
                else:
                    tasks.append(classify_candidate(offset, post, annotation, arm_id))

    eval_total = len(tasks) + len(all_posts)
    eval_done = len([item for item in desc_results if not isinstance(item, Exception)])
    if on_progress:
        on_progress(eval_done, eval_total)

    async def _track(coro):
        nonlocal eval_done
        try:
            result = await asyncio.wait_for(coro, timeout=120)
        except asyncio.TimeoutError:
            log.warning("Classification timeout (120s) dans multi_evaluate")
            result = None
        eval_done += 1
        if on_progress:
            on_progress(eval_done, eval_total)
        return result

    results = await asyncio.gather(*[_track(task) for task in tasks], return_exceptions=True)
    results_by_offset: dict[int, list] = defaultdict(list)
    for item in results:
        if isinstance(item, Exception):
            log.warning("Classification échouée dans multi_evaluate: %s", item)
            continue
        if item is None:
            continue
        results_by_offset[item[0]].append(item)

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
                label = item[4]
                clf_log = item[5]
                matches_by_arm[arm_id].append(label == annotation[target_agent])
                state = arm_states[arm_id]
                store_api_call(
                    conn,
                    "evaluation",
                    target_agent,
                    clf_log.model,
                    resolve_prompt_id(state.db_ids, target_agent, target_scope),
                    post.ig_media_id,
                    clf_log.input_tokens,
                    clf_log.output_tokens,
                    None,
                    clf_log.latency_ms,
                    run_id,
                )
                store_prediction(
                    conn,
                    post.ig_media_id,
                    target_agent,
                    resolve_prompt_id(state.db_ids, target_agent, target_scope),
                    label,
                    simulation_run_id=run_id,
                )
                continue

            result = item[4]
            is_mismatch = item[5]
            metric_matches = target_metric_matches(result, annotation, target_agent)
            if is_mismatch:
                for candidate_arm_id in arms:
                    matches_by_arm[candidate_arm_id].extend(metric_matches)
            else:
                matches_by_arm[arm_id].extend(metric_matches)

            state = arm_states[arm_id]
            persist_api_calls(
                conn,
                post_id=post.ig_media_id,
                scope=scope,
                api_calls=result.api_calls,
                prompt_ids=state.db_ids,
                run_id=run_id,
                call_type="evaluation",
            )
            persist_pipeline_predictions(
                conn,
                post_id=post.ig_media_id,
                scope=scope,
                result=result,
                prompt_ids=state.db_ids,
                run_id=run_id,
                store_descriptor=False,
            )
            for axis in ("category", "visual_format", "strategy"):
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
