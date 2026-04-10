"""Pipeline d'inférence MILPO async — batch processing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import AsyncOpenAI

from milpo.agent_common import (
    build_classifier_messages,
    build_descriptor_messages,
    parse_classifier_arguments,
)
from milpo.config import LLM_API_KEY, LLM_BASE_URL, MODEL_CLASSIFIER
from milpo.inference import ApiCallLog, PipelineResult, PostInput, PromptSet
from milpo.inference_core import (
    build_classifier_specs,
    build_post_prediction,
    features_to_json,
)
from milpo.router import route
from milpo.schemas import build_classifier_tool

log = logging.getLogger("milpo")

_on_api_call = None


def set_api_call_hook(hook):
    """Définit un callback appelé après chaque appel API async (descriptor/classifier)."""
    global _on_api_call
    _on_api_call = hook


def get_async_client() -> AsyncOpenAI:
    if not LLM_API_KEY:
        raise RuntimeError("Aucune clé API configurée (GOOGLE_API_KEY ou OPENROUTER_API_KEY).")
    return AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=20.0,
    )


async def async_call_descriptor(
    client: AsyncOpenAI,
    model: str,
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, ApiCallLog]:
    messages = build_descriptor_messages(
        media_urls,
        media_types,
        caption,
        instructions,
        descriptions_taxonomiques,
    )

    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            start = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.1,
                )
            except Exception as exc:
                log.warning("Descriptor appel échoué (attempt %d): %s", attempt + 1, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            latency_ms = int((time.monotonic() - start) * 1000)

        if not response.choices:
            log.warning("Descriptor réponse vide (attempt %d)", attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Descriptor: réponse vide après retries")

        raw = response.choices[0].message.content
        if not raw or not raw.strip():
            log.warning("Descriptor content vide (attempt %d)", attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Descriptor: content vide après retries")

        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0
        if _on_api_call:
            _on_api_call("descriptor", model, latency_ms, in_tok, out_tok, "ok")
        return raw, ApiCallLog(
            agent="descriptor",
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
        )

    raise RuntimeError("Descriptor: épuisé les retries")


async def async_call_classifier(
    client: AsyncOpenAI,
    model: str,
    axis: str,
    labels: list[str],
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str, ApiCallLog]:
    """Appelle un classifieur via tool calling forcé."""
    messages = build_classifier_messages(
        features_json,
        caption,
        instructions,
        descriptions_taxonomiques,
    )
    tool = build_classifier_tool(axis, labels)
    tool_name = tool["function"]["name"]

    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            start = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=[tool],
                    tool_choice="auto",
                    temperature=0.1,
                    reasoning_effort="low",
                )
            except Exception as exc:
                log.warning("Classifier %s échoué (attempt %d): %s", axis, attempt + 1, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            latency_ms = int((time.monotonic() - start) * 1000)

        if not response.choices:
            log.warning("Classifier %s réponse vide (attempt %d)", axis, attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Classifier {axis}: réponse vide après retries")

        choice = response.choices[0]
        if not choice.message.tool_calls:
            log.warning(
                "Classifier %s pas de tool_call (attempt %d) — content=%r",
                axis,
                attempt + 1,
                choice.message.content,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Classifier {axis}: pas de tool_call après retries")

        tool_call = choice.message.tool_calls[0]
        if tool_call.function.name != tool_name:
            log.warning(
                "Classifier %s nom de tool inattendu '%s' (attendu '%s')",
                axis,
                tool_call.function.name,
                tool_name,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"Classifier {axis}: nom de tool inattendu '{tool_call.function.name}'"
            )

        try:
            label, confidence = parse_classifier_arguments(
                tool_call.function.arguments,
                axis,
                labels,
            )
        except Exception as exc:
            log.warning(
                "Classifier %s arguments invalides (attempt %d): %s — raw=%r",
                axis,
                attempt + 1,
                exc,
                tool_call.function.arguments,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Classifier {axis}: arguments invalides après retries") from exc

        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0
        if _on_api_call:
            _on_api_call(axis, model, latency_ms, in_tok, out_tok, "ok")
        return label, confidence, ApiCallLog(
            agent=axis,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
        )

    raise RuntimeError(f"Classifier {axis}: épuisé les retries")


async def _async_classify_from_features(
    post: PostInput,
    *,
    features: str,
    api_calls: list[ApiCallLog],
    prompts: PromptSet,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> PipelineResult:
    features_json = features_to_json(features)
    classifiers = build_classifier_specs(
        prompts,
        category_labels,
        visual_format_labels,
        strategy_labels,
    )

    async def _classify(axis: str, labels: list[str], instructions: str, descriptions: str):
        return axis, await async_call_classifier(
            client,
            MODEL_CLASSIFIER,
            axis,
            labels,
            features_json,
            post.caption,
            instructions,
            descriptions,
            semaphore,
        )

    classifier_results = await asyncio.gather(*[
        _classify(axis, labels, instructions, descriptions)
        for axis, (labels, instructions, descriptions) in classifiers.items()
    ])

    predicted_labels: dict[str, str] = {}
    confidences: dict[str, str] = {}
    for axis, (label, confidence, clf_log) in classifier_results:
        predicted_labels[axis] = label
        confidences[axis] = confidence
        api_calls.append(clf_log)

    prediction = build_post_prediction(
        ig_media_id=post.ig_media_id,
        features=features,
        labels_by_axis=predicted_labels,
    )
    return PipelineResult(prediction=prediction, api_calls=api_calls, confidences=confidences)


async def async_classify_post(
    post: PostInput,
    prompts: PromptSet,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> PipelineResult:
    """Pipeline async pour un post : descripteur → 3 classifieurs en //."""
    routing = route(post.media_product_type)
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
    return await _async_classify_from_features(
        post,
        features=features,
        api_calls=[desc_log],
        prompts=prompts,
        category_labels=category_labels,
        visual_format_labels=visual_format_labels,
        strategy_labels=strategy_labels,
        client=client,
        semaphore=semaphore,
    )


async def async_classify_with_features(
    post: PostInput,
    features: str,
    desc_log: ApiCallLog,
    prompts: PromptSet,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> PipelineResult:
    """Pipeline async sans appel descripteur — réutilise des features pré-calculées."""
    return await _async_classify_from_features(
        post,
        features=features,
        api_calls=[desc_log],
        prompts=prompts,
        category_labels=category_labels,
        visual_format_labels=visual_format_labels,
        strategy_labels=strategy_labels,
        client=client,
        semaphore=semaphore,
    )


async def async_classify_target_only(
    post: PostInput,
    features: str,
    target_axis: str,
    target_labels: list[str],
    target_instructions: str,
    target_descriptions: str,
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> tuple[str, ApiCallLog]:
    """Classifie un seul axe cible — pour les bras candidats du bandit ProTeGi."""
    label, _confidence, clf_log = await async_call_classifier(
        client,
        MODEL_CLASSIFIER,
        target_axis,
        target_labels,
        features_to_json(features),
        post.caption,
        target_instructions,
        target_descriptions,
        semaphore,
    )
    return label, clf_log


async def async_classify_batch(
    posts: list[PostInput],
    prompts_by_scope: dict[str, PromptSet],
    labels_by_scope: dict[str, dict[str, list[str]]],
    max_concurrent_api: int = 20,
    max_concurrent_posts: int = 10,
    on_progress: Any = None,
    per_post_timeout: float = 120.0,
) -> list[PipelineResult]:
    """Classifie un batch de posts en parallèle (best effort per-post)."""
    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent_api)
    post_semaphore = asyncio.Semaphore(max_concurrent_posts)

    results: list[PipelineResult | None] = [None] * len(posts)
    done_count = 0
    error_count = 0

    async def _process_one(idx: int, post: PostInput):
        nonlocal done_count, error_count
        async with post_semaphore:
            scope = post.media_product_type.upper()
            prompts = prompts_by_scope[scope]
            labels = labels_by_scope[scope]

            try:
                results[idx] = await asyncio.wait_for(
                    async_classify_post(
                        post=post,
                        prompts=prompts,
                        category_labels=labels["category"],
                        visual_format_labels=labels["visual_format"],
                        strategy_labels=labels["strategy"],
                        client=client,
                        semaphore=semaphore,
                    ),
                    timeout=per_post_timeout,
                )
            except asyncio.TimeoutError:
                error_count += 1
                log.warning("Post %s TIMEOUT (%ds)", post.ig_media_id, per_post_timeout)
                if _on_api_call:
                    _on_api_call("timeout", "—", int(per_post_timeout * 1000), 0, 0, "error")
            except Exception as exc:
                error_count += 1
                log.error("Post %s échoué: %s", post.ig_media_id, exc)

            done_count += 1
            if on_progress:
                on_progress(done_count, len(posts), error_count)

    await asyncio.gather(*[_process_one(i, post) for i, post in enumerate(posts)])
    return [result for result in results if result is not None]
