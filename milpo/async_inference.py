"""Pipeline d'inférence MILPO async — batch processing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger("milpo")

from milpo.config import (
    MODEL_CLASSIFIER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)
from milpo.agent import (
    build_classifier_messages,
    build_descriptor_messages,
    parse_classifier_arguments,
)
from milpo.inference import ApiCallLog, PostInput, PromptSet, PipelineResult
from milpo.router import route
from milpo.schemas import (
    DescriptorFeatures,
    PostPrediction,
    build_classifier_tool,
    build_json_schema_response_format,
)


def get_async_client() -> AsyncOpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY non définie.")
    return AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
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
) -> tuple[DescriptorFeatures, ApiCallLog]:
    messages = build_descriptor_messages(
        media_urls, media_types, caption,
        instructions, descriptions_taxonomiques,
    )
    response_format = build_json_schema_response_format(
        "descriptor_features",
        DescriptorFeatures.model_json_schema(),
    )

    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            start = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    temperature=0.1,
                )
            except Exception as e:
                log.warning("Descriptor appel échoué (attempt %d): %s", attempt + 1, e)
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
        if not raw:
            log.warning("Descriptor content vide (attempt %d)", attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Descriptor: content vide après retries")

        try:
            features = DescriptorFeatures.model_validate_json(raw)
        except Exception as e:
            log.warning("Descriptor JSON invalide (attempt %d): %s", attempt + 1, e)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Descriptor: JSON invalide après retries") from e
        usage = response.usage

        api_log = ApiCallLog(
            agent="descriptor",
            model=model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
        return features, api_log

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
    """Appelle un classifieur via tool calling forcé (universal OpenRouter).

    Voir hilpo/agent.py:call_classifier pour les motivations.
    """
    messages = build_classifier_messages(
        features_json, caption, instructions, descriptions_taxonomiques,
    )
    tool = build_classifier_tool(axis, labels)
    tool_name = tool["function"]["name"]

    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            start = time.monotonic()
            try:
                # tool_choice="auto" : voir hilpo/agent.py:call_classifier
                # pour la motivation (seul mode supporté par les providers Qwen 3.5 Flash).
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=[tool],
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                log.warning("Classifier %s échoué (attempt %d): %s", axis, attempt + 1, e)
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
                axis, attempt + 1, choice.message.content,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Classifier {axis}: pas de tool_call après retries")

        tool_call = choice.message.tool_calls[0]
        if tool_call.function.name != tool_name:
            log.warning(
                "Classifier %s nom de tool inattendu '%s' (attendu '%s')",
                axis, tool_call.function.name, tool_name,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"Classifier {axis}: nom de tool inattendu '{tool_call.function.name}'"
            )

        try:
            label, confidence = parse_classifier_arguments(
                tool_call.function.arguments, axis, labels,
            )
        except Exception as e:
            log.warning(
                "Classifier %s arguments invalides (attempt %d): %s — raw=%r",
                axis, attempt + 1, e, tool_call.function.arguments,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Classifier {axis}: arguments invalides après retries") from e

        usage = response.usage
        api_log = ApiCallLog(
            agent=axis,
            model=model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency_ms,
        )
        return label, confidence, api_log

    raise RuntimeError(f"Classifier {axis}: épuisé les retries")


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
    api_calls: list[ApiCallLog] = []
    routing = route(post.media_product_type)

    # 1. Descripteur
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
    api_calls.append(desc_log)
    features_json = features.model_dump_json(indent=2)

    # 2. 3 classifieurs en parallèle
    classifiers = {
        "category": (category_labels, prompts.category_instructions, prompts.category_descriptions),
        "visual_format": (visual_format_labels, prompts.visual_format_instructions, prompts.visual_format_descriptions),
        "strategy": (strategy_labels, prompts.strategy_instructions, prompts.strategy_descriptions),
    }

    async def _classify(axis: str, labels: list[str], instr: str, desc: str):
        return axis, await async_call_classifier(
            client, MODEL_CLASSIFIER, axis, labels,
            features_json, post.caption, instr, desc, semaphore,
        )

    tasks = [_classify(ax, lb, ins, ds) for ax, (lb, ins, ds) in classifiers.items()]
    classifier_results = await asyncio.gather(*tasks)

    results: dict[str, str] = {}
    for axis, (label, confidence, clf_log) in classifier_results:
        results[axis] = label
        api_calls.append(clf_log)

    prediction = PostPrediction(
        ig_media_id=post.ig_media_id,
        category=results["category"],
        visual_format=results["visual_format"],
        strategy=results["strategy"],
        features=features,
    )
    return PipelineResult(prediction=prediction, api_calls=api_calls)


async def async_classify_batch(
    posts: list[PostInput],
    prompts_by_scope: dict[str, PromptSet],
    labels_by_scope: dict[str, dict[str, list[str]]],
    max_concurrent_api: int = 20,
    max_concurrent_posts: int = 10,
    on_progress: Any = None,
) -> list[PipelineResult]:
    """Classifie un batch de posts en parallèle.

    Args:
        posts: Liste de posts à classifier.
        prompts_by_scope: {scope: PromptSet}.
        labels_by_scope: {scope: {"category": [...], "visual_format": [...], "strategy": [...]}}.
        max_concurrent_api: Max d'appels API simultanés.
        max_concurrent_posts: Max de posts traités en parallèle.
        on_progress: Callback(done, total, errors) appelé après chaque post.
    """
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
                result = await async_classify_post(
                    post=post,
                    prompts=prompts,
                    category_labels=labels["category"],
                    visual_format_labels=labels["visual_format"],
                    strategy_labels=labels["strategy"],
                    client=client,
                    semaphore=semaphore,
                )
                results[idx] = result
            except Exception as e:
                error_count += 1
                log.error("Post %s échoué: %s", post.ig_media_id, e)
            done_count += 1
            if on_progress:
                on_progress(done_count, len(posts), error_count)

    await asyncio.gather(*[_process_one(i, p) for i, p in enumerate(posts)])
    return [r for r in results if r is not None]
