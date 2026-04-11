"""Helpers de persistance des résultats de classification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from milpo.db import store_api_call, store_prediction
from milpo.inference import ApiCallLog, PipelineResult, PostInput

PromptIdMap = Mapping[tuple[str, str | None], int]


def resolve_prompt_id(prompt_ids: PromptIdMap, agent: str, scope: str | None) -> int | None:
    scope_key = scope if agent in ("descriptor", "visual_format") else None
    return prompt_ids.get((agent, scope_key)) or prompt_ids.get((agent, None))


def persist_pipeline_predictions(
    conn,
    *,
    post_id: int,
    scope: str,
    result: PipelineResult,
    prompt_ids: PromptIdMap,
    run_id: int,
    store_descriptor: bool = True,
) -> None:
    pred = result.prediction
    confidences = getattr(result, "confidences", {}) or {}
    reasonings = getattr(result, "reasonings", {}) or {}
    extras = getattr(result, "extras", {}) or {}
    for axis in ("category", "visual_format", "strategy"):
        prompt_id = resolve_prompt_id(prompt_ids, axis, scope)
        if prompt_id is None:
            continue
        axis_extra = extras.get(axis) or {}
        raw: dict = {
            "confidence": confidences.get(axis),
            "reasoning": reasonings.get(axis),
        }
        # Structured self-consistency data : samples + majority + oracle
        if axis_extra.get("samples"):
            raw["samples"] = axis_extra["samples"]
        if "majority_label" in axis_extra:
            raw["classifier_majority_label"] = axis_extra["majority_label"]
        if axis_extra.get("oracle_info") is not None:
            raw["oracle"] = axis_extra["oracle_info"]
        if axis == "visual_format":
            raw["text"] = pred.features
        store_prediction(
            conn,
            post_id,
            axis,
            prompt_id,
            getattr(pred, axis),
            raw_response=raw,
            simulation_run_id=run_id,
        )

    if store_descriptor:
        desc_prompt_id = resolve_prompt_id(prompt_ids, "descriptor", scope)
        if desc_prompt_id is not None:
            store_prediction(
                conn,
                post_id,
                "descriptor",
                desc_prompt_id,
                "features_extracted",
                raw_response={"text": pred.features},
                simulation_run_id=run_id,
            )


def persist_api_calls(
    conn,
    *,
    post_id: int | None,
    scope: str | None,
    api_calls: Sequence[ApiCallLog],
    prompt_ids: PromptIdMap,
    run_id: int,
    call_type: str,
) -> int:
    total_api = 0
    for call in api_calls:
        prompt_id = resolve_prompt_id(prompt_ids, call.agent, scope)
        store_api_call(
            conn,
            call_type=call_type,
            agent=call.agent,
            model_name=call.model,
            prompt_version_id=prompt_id,
            ig_media_id=post_id,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=None,
            latency_ms=call.latency_ms,
            simulation_run_id=run_id,
        )
        total_api += 1
    return total_api


def persist_pipeline_result(
    conn,
    *,
    post: PostInput,
    result: PipelineResult,
    prompt_ids: PromptIdMap,
    run_id: int,
    call_type: str = "classification",
    store_descriptor: bool = True,
) -> int:
    persist_pipeline_predictions(
        conn,
        post_id=post.ig_media_id,
        scope=post.media_product_type,
        result=result,
        prompt_ids=prompt_ids,
        run_id=run_id,
        store_descriptor=store_descriptor,
    )
    return persist_api_calls(
        conn,
        post_id=post.ig_media_id,
        scope=post.media_product_type,
        api_calls=result.api_calls,
        prompt_ids=prompt_ids,
        run_id=run_id,
        call_type=call_type,
    )


def store_results(
    conn,
    results: Sequence[PipelineResult],
    post_inputs: Sequence[PostInput],
    prompt_ids: PromptIdMap,
    run_id: int,
) -> tuple[dict[str, int], int]:
    """Stocke toutes les prédictions et api_calls d'un lot baseline."""
    scope_map = {post.ig_media_id: post.media_product_type for post in post_inputs}
    matches = {"category": 0, "visual_format": 0, "strategy": 0}
    total_api = 0

    for result in results:
        pred = result.prediction
        scope = scope_map[pred.ig_media_id]
        total_api += persist_pipeline_result(
            conn,
            post=PostInput(
                ig_media_id=pred.ig_media_id,
                media_product_type=scope,
                media_urls=[],
                media_types=[],
                caption=None,
            ),
            result=result,
            prompt_ids=prompt_ids,
            run_id=run_id,
        )
        for axis in ("category", "visual_format", "strategy"):
            row = conn.execute(
                """
                SELECT match FROM predictions
                WHERE ig_media_id = %s AND agent = %s::agent_type AND simulation_run_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (pred.ig_media_id, axis, run_id),
            ).fetchone()
            if row and row["match"]:
                matches[axis] += 1

    return matches, total_api
