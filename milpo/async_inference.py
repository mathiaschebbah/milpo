"""Pipeline d'inférence MILPO async — batch processing."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI

from milpo.agent_common import (
    build_classifier_messages,
    build_descriptor_messages,
    parse_classifier_arguments,
)
from milpo.config import LLM_API_KEY, LLM_BASE_URL, MODEL_CLASSIFIER
from milpo.inference import ApiCallLog, PipelineResult, PostInput
from milpo.inference_core import build_post_prediction
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
        timeout=120.0,
    )


async def async_call_descriptor(
    client: AsyncOpenAI,
    model: str,
    scope: str,
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    semaphore: asyncio.Semaphore,
) -> tuple[str, ApiCallLog]:
    messages = build_descriptor_messages(
        media_urls,
        media_types,
        caption,
        scope=scope,
    )

    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            start = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
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
    perceiver_output: str,
    caption: str | None,
    post_scope: str,
    semaphore: asyncio.Semaphore,
    posted_at: datetime | None = None,
    temperature: float = 0.0,
    reasoning_effort: str = "high",
) -> tuple[str, str, str, ApiCallLog]:
    """Appelle un classifieur via tool calling forcé.

    Retourne (label, confidence, reasoning, log). Le reasoning est le
    chain-of-thought structuré émis par le classifieur avant son label
    (Wei et al. 2022, forcé par l'ordre des champs dans le schéma tool).
    """
    messages = build_classifier_messages(
        axis,
        perceiver_output,
        caption,
        post_scope,
        posted_at=posted_at,
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
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
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
        arguments_raw: str | None = None

        if choice.message.tool_calls:
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
            arguments_raw = tool_call.function.arguments
        else:
            # Fallback : certains modèles (ex: gemini-3-flash-preview) ne
            # supportent pas bien le tool calling via l'endpoint OpenAI-compat
            # et renvoient le JSON comme plain text, potentiellement précédé
            # par du thinking/reasoning en texte brut, avec le JSON dans un
            # bloc markdown ```json...``` à la fin.
            #
            # Stratégie d'extraction :
            # 1. Chercher un bloc ```json...``` (priorité au dernier)
            # 2. Sinon, extraire de la première { à la dernière } matching
            import re

            content = (choice.message.content or "").strip()
            extracted: str | None = None

            # Dernier bloc ```json ... ``` ou ``` ... ``` avec JSON à l'intérieur
            code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if code_blocks:
                extracted = code_blocks[-1]
            else:
                # Fallback : premier {...} équilibré
                first_brace = content.find("{")
                last_brace = content.rfind("}")
                if first_brace != -1 and last_brace > first_brace:
                    extracted = content[first_brace : last_brace + 1]

            if extracted:
                arguments_raw = extracted
            else:
                log.warning(
                    "Classifier %s pas de tool_call ni content (attempt %d)",
                    axis,
                    attempt + 1,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Classifier {axis}: pas de tool_call ni content après retries")

        try:
            label, confidence, reasoning = parse_classifier_arguments(
                arguments_raw,
                axis,
                labels,
            )
        except Exception as exc:
            log.warning(
                "Classifier %s arguments invalides (attempt %d): %s — raw=%r",
                axis,
                attempt + 1,
                exc,
                arguments_raw,
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
        return label, confidence, reasoning, ApiCallLog(
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
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
) -> PipelineResult:
    post_scope = post.media_product_type.upper()
    axis_labels = {
        "category": category_labels,
        "visual_format": visual_format_labels,
        "strategy": strategy_labels,
    }

    async def _classify(axis: str, labels: list[str]):
        # Routage par axe : visual_format peut utiliser un modèle plus capable
        # (override via MILPO_MODEL_CLASSIFIER_VISUAL_FORMAT) parce que c'est
        # l'axe le plus difficile (42 classes long-tail, règles subtiles).
        # category et strategy restent sur MODEL_CLASSIFIER (Flash Lite).
        from milpo.config import MODEL_CLASSIFIER_VISUAL_FORMAT
        model_for_axis = (
            MODEL_CLASSIFIER_VISUAL_FORMAT if axis == "visual_format" else MODEL_CLASSIFIER
        )
        label, conf, reasoning, clf_log = await async_call_classifier(
            client,
            model_for_axis,
            axis,
            labels,
            features,
            post.caption,
            post_scope,
            semaphore,
            posted_at=post.posted_at,
            temperature=0.0,
            reasoning_effort="high",
        )
        return axis, (label, conf, reasoning, clf_log)

    classifier_results = await asyncio.gather(*[
        _classify(axis, labels) for axis, labels in axis_labels.items()
    ])

    predicted_labels: dict[str, str] = {}
    confidences: dict[str, str] = {}
    reasonings: dict[str, str] = {}
    extras: dict[str, dict] = {}
    for axis, (label, confidence, reasoning, clf_log) in classifier_results:
        predicted_labels[axis] = label
        confidences[axis] = confidence
        reasonings[axis] = reasoning
        extras[axis] = {}
        api_calls.append(clf_log)

    prediction = build_post_prediction(
        ig_media_id=post.ig_media_id,
        features=features,
        labels_by_axis=predicted_labels,
    )
    return PipelineResult(
        prediction=prediction,
        api_calls=api_calls,
        confidences=confidences,
        reasonings=reasonings,
        extras=extras,
    )


async def async_classify_post(
    post: PostInput,
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
        scope=post.media_product_type,
        media_urls=post.media_urls,
        media_types=post.media_types,
        caption=post.caption,
        semaphore=semaphore,
    )
    return await _async_classify_from_features(
        post,
        features=features,
        api_calls=[desc_log],
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
        category_labels=category_labels,
        visual_format_labels=visual_format_labels,
        strategy_labels=strategy_labels,
        client=client,
        semaphore=semaphore,
    )


async def async_classify_batch(
    posts: list[PostInput],
    labels_by_scope: dict[str, dict[str, list[str]]],
    max_concurrent_api: int = 20,
    max_concurrent_posts: int = 10,
    on_progress: Any = None,
    per_post_timeout: float = 480.0,
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
            labels = labels_by_scope[scope]

            try:
                results[idx] = await asyncio.wait_for(
                    async_classify_post(
                        post=post,
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
