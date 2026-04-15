"""Pipeline d'inférence MILPO — modes ALMA (2 étages) et SIMPLE (1 appel multimodal).

Un seul module pour toute l'inférence. Deux batchs publics :
- `async_classify_alma_batch()`   : Alma (percepteur multimodal) → 3 classifieurs text-only
- `async_classify_simple_batch()` : 1 appel multimodal ASSIST par post (3 labels d'un coup)

Les modules historiques (`async_inference`, `e2e_inference`, `agent`, `inference_core`)
ré-exportent depuis ici en attendant leur suppression.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI

from milpo.agent_common import (
    build_classifier_messages,
    build_descriptor_messages,
    build_simple_messages,
    parse_classifier_arguments,
    parse_simple_arguments,
)
from milpo.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    MODEL_CLASSIFIER,
    MODEL_CLASSIFIER_VISUAL_FORMAT,
    MODEL_SIMPLE,
)
from milpo.router import route
from milpo.schemas import (
    PostPrediction,
    build_classifier_tool,
    build_simple_tool,
)

log = logging.getLogger("milpo")


# ─── Dataclasses publiques ──────────────────────────────────────────────────


@dataclass
class PostInput:
    """Données d'entrée pour classifier un post."""

    ig_media_id: int
    media_product_type: str
    media_urls: list[str]
    media_types: list[str]
    caption: str | None
    posted_at: datetime | None = None


@dataclass
class ApiCallLog:
    """Log d'un appel API pour traçabilité."""

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class PipelineResult:
    """Résultat complet du pipeline pour un post."""

    prediction: PostPrediction
    api_calls: list[ApiCallLog] = field(default_factory=list)
    confidences: dict[str, str] = field(default_factory=dict)
    reasonings: dict[str, str] = field(default_factory=dict)
    extras: dict[str, dict] = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.api_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.api_calls)

    @property
    def total_latency_ms(self) -> int:
        return sum(call.latency_ms for call in self.api_calls)


# ─── Client async + hook télémétrie ─────────────────────────────────────────

_on_api_call = None


def set_api_call_hook(hook):
    """Définit un callback appelé après chaque appel API (descriptor/classifier/simple)."""
    global _on_api_call
    _on_api_call = hook


def get_async_client() -> AsyncOpenAI:
    if not LLM_API_KEY:
        raise RuntimeError(
            "Aucune clé API configurée (GOOGLE_API_KEY ou OPENROUTER_API_KEY)."
        )
    # Timeout HTTP client : 120s. Calibré pour reasoning_effort=medium :
    # - classifier text medium : ~15-30s
    # - simple multimodal medium : ~30-60s
    # - carousels multimodaux lourds (10+ images) en medium : jusqu'à 90s
    # Coupure des hangs silencieux Google AI avant per_post_timeout (600s).
    # Avec 3 retries + backoff (1+2+4s), un post bloqué termine en ~370s max.
    return AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=120.0,
    )


# ─── Helpers partagés ───────────────────────────────────────────────────────


def _extract_json_from_text(text: str) -> str | None:
    """Extrait un JSON brut d'un texte (fallback quand pas de tool_call).

    Certains modèles (ex : gemini-3-flash-preview via OpenAI-compat) renvoient
    le JSON comme plain text, potentiellement précédé par du reasoning, avec
    le JSON dans un bloc markdown ```json ... ``` à la fin.
    """
    content = text.strip()
    code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if code_blocks:
        return code_blocks[-1]
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return content[first_brace : last_brace + 1]
    return None


def _build_post_prediction(
    *,
    ig_media_id: int,
    features: str,
    labels_by_axis: dict[str, str],
) -> PostPrediction:
    return PostPrediction(
        ig_media_id=ig_media_id,
        category=labels_by_axis["category"],
        visual_format=labels_by_axis["visual_format"],
        strategy=labels_by_axis["strategy"],
        features=features,
    )


# ─── Mode --alma : descripteur + 3 classifieurs text-only ──────────────────


async def async_call_descriptor(
    client: AsyncOpenAI,
    model: str,
    scope: str,
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    semaphore: asyncio.Semaphore,
) -> tuple[str, ApiCallLog]:
    """Appelle le percepteur Alma (multimodal, sortie texte libre structurée)."""
    messages = build_descriptor_messages(media_urls, media_types, caption, scope=scope)

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

        # Gemini facture reasoning au tarif output mais ne le compte pas
        # dans completion_tokens. Le vrai output = total - prompt (inclut
        # reasoning + completion visible). Sans cette correction, le coût
        # est sous-estimé de ~85% avec reasoning_effort=medium.
        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = (usage.total_tokens - usage.prompt_tokens) if usage else 0
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
    reasoning_effort: str = "medium",
) -> tuple[str, str, str, ApiCallLog]:
    """Appelle un classifieur text-only via tool calling forcé.

    Retourne (label, confidence, reasoning, log). Le reasoning est le
    chain-of-thought structuré (Wei et al. 2022) émis via `reasoning` placé
    en premier champ du tool schema.
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
            arguments_raw = _extract_json_from_text(choice.message.content or "")
            if not arguments_raw:
                log.warning(
                    "Classifier %s pas de tool_call ni content (attempt %d)",
                    axis,
                    attempt + 1,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    f"Classifier {axis}: pas de tool_call ni content après retries"
                )

        try:
            label, confidence, reasoning = parse_classifier_arguments(
                arguments_raw, axis, labels
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
            raise RuntimeError(
                f"Classifier {axis}: arguments invalides après retries"
            ) from exc

        # Gemini facture reasoning au tarif output mais ne le compte pas
        # dans completion_tokens. Le vrai output = total - prompt (inclut
        # reasoning + completion visible). Sans cette correction, le coût
        # est sous-estimé de ~85% avec reasoning_effort=medium.
        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = (usage.total_tokens - usage.prompt_tokens) if usage else 0
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
    classifier_model: str | None = None,
    classifier_vf_model: str | None = None,
) -> PipelineResult:
    """Lance les 3 classifieurs text-only en parallèle à partir de features déjà calculées."""
    post_scope = post.media_product_type.upper()
    axis_labels = {
        "category": category_labels,
        "visual_format": visual_format_labels,
        "strategy": strategy_labels,
    }

    base_classifier = classifier_model or MODEL_CLASSIFIER
    vf_classifier = classifier_vf_model or classifier_model or MODEL_CLASSIFIER_VISUAL_FORMAT

    async def _classify(axis: str, labels: list[str]):
        # visual_format peut utiliser un modèle plus capable (override env) :
        # c'est l'axe le plus difficile (42 classes long-tail, règles subtiles).
        model_for_axis = vf_classifier if axis == "visual_format" else base_classifier
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
        )
        return axis, (label, conf, reasoning, clf_log)

    classifier_results = await asyncio.gather(
        *[_classify(axis, labels) for axis, labels in axis_labels.items()]
    )

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

    prediction = _build_post_prediction(
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


async def async_classify_post_alma(
    post: PostInput,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    descriptor_model: str | None = None,
    classifier_model: str | None = None,
    classifier_vf_model: str | None = None,
) -> PipelineResult:
    """Pipeline ASSIST complet (Alma + 3 classifieurs) pour un post."""
    routing = route(post.media_product_type)
    features, desc_log = await async_call_descriptor(
        client=client,
        model=descriptor_model or routing["model_descriptor"],
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
        classifier_model=classifier_model,
        classifier_vf_model=classifier_vf_model,
    )


# ─── Mode --simple : 1 appel multimodal ASSIST ─────────────────────────────


async def async_call_simple(
    client: AsyncOpenAI,
    model: str,
    post: PostInput,
    vf_labels: list[str],
    cat_labels: list[str],
    strat_labels: list[str],
    semaphore: asyncio.Semaphore,
    temperature: float = 0.0,
    reasoning_effort: str = "medium",
) -> tuple[dict[str, str], str, str, ApiCallLog]:
    """Appelle le classifieur simple multimodal (1 appel → 3 labels).

    Retourne ({visual_format, category, strategy}, confidence, reasoning, log).
    """
    post_scope = post.media_product_type.upper()
    messages = build_simple_messages(
        media_urls=post.media_urls,
        media_types=post.media_types,
        caption=post.caption,
        post_scope=post_scope,
        posted_at=post.posted_at,
    )
    tool = build_simple_tool(vf_labels, cat_labels, strat_labels)
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
                log.warning("Simple appel échoué (attempt %d): %s", attempt + 1, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            latency_ms = int((time.monotonic() - start) * 1000)

        if not response.choices:
            log.warning("Simple réponse vide (attempt %d)", attempt + 1)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Simple: réponse vide après retries")

        choice = response.choices[0]
        arguments_raw: str | None = None

        if choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
            if tool_call.function.name != tool_name:
                log.warning(
                    "Simple nom de tool inattendu '%s' (attendu '%s')",
                    tool_call.function.name,
                    tool_name,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RuntimeError(
                    f"Simple: nom de tool inattendu '{tool_call.function.name}'"
                )
            arguments_raw = tool_call.function.arguments
        else:
            arguments_raw = _extract_json_from_text(choice.message.content or "")
            if not arguments_raw:
                log.warning(
                    "Simple pas de tool_call ni content (attempt %d)", attempt + 1
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RuntimeError("Simple: pas de tool_call ni content après retries")

        try:
            vf, cat, strat, confidence, reasoning = parse_simple_arguments(
                arguments_raw, vf_labels, cat_labels, strat_labels
            )
        except Exception as exc:
            log.warning(
                "Simple arguments invalides (attempt %d): %s — raw=%r",
                attempt + 1,
                exc,
                arguments_raw,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise RuntimeError("Simple: arguments invalides après retries") from exc

        # Gemini facture reasoning au tarif output mais ne le compte pas
        # dans completion_tokens. Le vrai output = total - prompt (inclut
        # reasoning + completion visible). Sans cette correction, le coût
        # est sous-estimé de ~85% avec reasoning_effort=medium.
        usage = response.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = (usage.total_tokens - usage.prompt_tokens) if usage else 0
        if _on_api_call:
            _on_api_call("simple", model, latency_ms, in_tok, out_tok, "ok")
        return (
            {"visual_format": vf, "category": cat, "strategy": strat},
            confidence,
            reasoning,
            ApiCallLog(
                agent="simple",
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
            ),
        )

    raise RuntimeError("Simple: épuisé les retries")


async def async_classify_post_simple(
    post: PostInput,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    model: str = MODEL_SIMPLE,
) -> PipelineResult:
    """Pipeline --simple : 1 appel multimodal ASSIST pour un post."""
    labels_by_axis, confidence, reasoning, clf_log = await async_call_simple(
        client=client,
        model=model,
        post=post,
        vf_labels=visual_format_labels,
        cat_labels=category_labels,
        strat_labels=strategy_labels,
        semaphore=semaphore,
    )
    prediction = _build_post_prediction(
        ig_media_id=post.ig_media_id,
        features="[simple — pas de features séparées]",
        labels_by_axis=labels_by_axis,
    )
    return PipelineResult(
        prediction=prediction,
        api_calls=[clf_log],
        confidences={axis: confidence for axis in labels_by_axis},
        reasonings={axis: reasoning for axis in labels_by_axis},
    )


# ─── Batches publics ────────────────────────────────────────────────────────


SLOW_POST_THRESHOLD_S: float = 60.0


async def _watchdog_slow_post(post_id: int, n_media: int) -> None:
    """Warn périodiquement quand un post dure plus que SLOW_POST_THRESHOLD_S.

    Annulé dès que le post termine (normalement, timeout, erreur).
    Utilisé pour diagnostiquer les posts qui traînent dans un batch.
    """
    elapsed = 0.0
    while True:
        await asyncio.sleep(SLOW_POST_THRESHOLD_S)
        elapsed += SLOW_POST_THRESHOLD_S
        log.warning(
            "Post %s toujours en cours après %ds (%d médias)",
            post_id,
            int(elapsed),
            n_media,
        )


async def async_classify_alma_batch(
    posts: list[PostInput],
    labels_by_scope: dict[str, dict[str, list[str]]],
    max_concurrent_api: int = 20,
    max_concurrent_posts: int = 5,
    on_progress: Any = None,
    per_post_timeout: float = 600.0,
    descriptor_model: str | None = None,
    classifier_model: str | None = None,
    classifier_vf_model: str | None = None,
) -> list[PipelineResult]:
    """Batch ASSIST : Alma (multimodal) + 3 classifieurs text-only par post."""
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
            watchdog = asyncio.create_task(
                _watchdog_slow_post(post.ig_media_id, len(post.media_urls))
            )
            try:
                results[idx] = await asyncio.wait_for(
                    async_classify_post_alma(
                        post=post,
                        category_labels=labels["category"],
                        visual_format_labels=labels["visual_format"],
                        strategy_labels=labels["strategy"],
                        client=client,
                        semaphore=semaphore,
                        descriptor_model=descriptor_model,
                        classifier_model=classifier_model,
                        classifier_vf_model=classifier_vf_model,
                    ),
                    timeout=per_post_timeout,
                )
            except asyncio.TimeoutError:
                error_count += 1
                log.warning("Post %s TIMEOUT (%ds)", post.ig_media_id, per_post_timeout)
                if _on_api_call:
                    _on_api_call(
                        "timeout", "—", int(per_post_timeout * 1000), 0, 0, "error"
                    )
            except Exception as exc:
                error_count += 1
                log.error("Post %s échoué: %s", post.ig_media_id, exc)
            finally:
                watchdog.cancel()

            done_count += 1
            if on_progress:
                on_progress(done_count, len(posts), error_count)

    await asyncio.gather(*[_process_one(i, p) for i, p in enumerate(posts)])
    return [result for result in results if result is not None]


async def async_classify_simple_batch(
    posts: list[PostInput],
    labels_by_scope: dict[str, dict[str, list[str]]],
    model: str = MODEL_SIMPLE,
    max_concurrent: int = 5,
    on_progress: Any = None,
    per_post_timeout: float = 600.0,
) -> list[PipelineResult]:
    """Batch --simple : 1 appel multimodal ASSIST par post (3 labels en une fois)."""
    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent)

    results: list[PipelineResult | None] = [None] * len(posts)
    done_count = 0
    error_count = 0

    async def _process_one(idx: int, post: PostInput):
        nonlocal done_count, error_count
        scope = post.media_product_type.upper()
        labels = labels_by_scope[scope]
        watchdog = asyncio.create_task(
            _watchdog_slow_post(post.ig_media_id, len(post.media_urls))
        )
        try:
            results[idx] = await asyncio.wait_for(
                async_classify_post_simple(
                    post=post,
                    category_labels=labels["category"],
                    visual_format_labels=labels["visual_format"],
                    strategy_labels=labels["strategy"],
                    client=client,
                    semaphore=semaphore,
                    model=model,
                ),
                timeout=per_post_timeout,
            )
        except asyncio.TimeoutError:
            error_count += 1
            log.warning("Post %s TIMEOUT (%ds)", post.ig_media_id, per_post_timeout)
            if _on_api_call:
                _on_api_call(
                    "timeout", "—", int(per_post_timeout * 1000), 0, 0, "error"
                )
        except Exception as exc:
            error_count += 1
            log.error("Post %s échoué: %s", post.ig_media_id, exc)
        finally:
            watchdog.cancel()

        done_count += 1
        if on_progress:
            on_progress(done_count, len(posts), error_count)

    await asyncio.gather(*[_process_one(i, p) for i, p in enumerate(posts)])
    return [result for result in results if result is not None]
