"""Pipeline d'inférence HILPO async — batch processing."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from hilpo.config import (
    MODEL_CLASSIFIER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)
from hilpo.agent import build_classifier_messages, build_classifier_tool, build_descriptor_messages
from hilpo.inference import ApiCallLog, PostInput, PromptSet, PipelineResult
from hilpo.router import route
from hilpo.schemas import DescriptorFeatures, PostPrediction


def get_async_client() -> AsyncOpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY non définie.")
    return AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)


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
    response_schema = DescriptorFeatures.model_json_schema()

    async with semaphore:
        start = time.monotonic()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "descriptor_features",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            temperature=0.1,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

    raw = response.choices[0].message.content
    features = DescriptorFeatures.model_validate_json(raw)
    usage = response.usage

    log = ApiCallLog(
        agent="descriptor",
        model=model,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
    )
    return features, log


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
    messages = build_classifier_messages(
        features_json, caption, instructions, descriptions_taxonomiques,
    )
    tool = build_classifier_tool(axis, labels)

    async with semaphore:
        start = time.monotonic()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[tool],
            tool_choice="auto",
            temperature=0.1,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

    choice = response.choices[0]
    if choice.message.tool_calls:
        tool_call = choice.message.tool_calls[0]
        result = json.loads(tool_call.function.arguments)
        label = result["label"]
        confidence = result.get("confidence", "medium")
    else:
        raw_text = choice.message.content or ""
        label = raw_text.strip().split("\n")[0].strip()
        confidence = "low"

    usage = response.usage
    log = ApiCallLog(
        agent=axis,
        model=model,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        latency_ms=latency_ms,
    )
    return label, confidence, log


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
        on_progress: Callback(done, total) appelé après chaque post.
    """
    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent_api)
    post_semaphore = asyncio.Semaphore(max_concurrent_posts)

    results: list[PipelineResult | None] = [None] * len(posts)
    done_count = 0

    async def _process_one(idx: int, post: PostInput):
        nonlocal done_count
        async with post_semaphore:
            scope = post.media_product_type.upper()
            prompts = prompts_by_scope[scope]
            labels = labels_by_scope[scope]

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
            done_count += 1
            if on_progress:
                on_progress(done_count, len(posts))

    await asyncio.gather(*[_process_one(i, p) for i, p in enumerate(posts)])
    return [r for r in results if r is not None]
