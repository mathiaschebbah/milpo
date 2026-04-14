"""Agents MILPO (sync) : descripteur multimodal et classifieurs text-only.

Version synchrone symétrique d'`async_inference` — utilisée par `inference.classify_post`
et les tests directs. La version async async_inference.async_classify_* est préférée
pour le batch processing.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from openai import OpenAI

from milpo.agent_common import (
    build_classifier_messages,
    build_descriptor_messages,
    parse_classifier_arguments,
)
from milpo.errors import LLMCallError
from milpo.schemas import build_classifier_tool

log = logging.getLogger("milpo")

MAX_SYNC_RETRIES = 3


def _sleep_before_retry(attempt: int) -> None:
    """Backoff exponentiel simple pour les appels sync."""
    time.sleep(2 ** attempt)


def call_descriptor(
    client: OpenAI,
    model: str,
    scope: str,
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
) -> tuple[str, dict]:
    """Appelle le descripteur multimodal et retourne l'analyse textuelle."""
    messages = build_descriptor_messages(
        media_urls,
        media_types,
        caption,
        scope=scope,
    )

    start = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(MAX_SYNC_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
            )
            if not response.choices:
                raise RuntimeError("Descriptor: réponse vide")

            raw = response.choices[0].message.content
            if not raw or not raw.strip():
                raise RuntimeError("Descriptor: content vide")

            latency_ms = int((time.monotonic() - start) * 1000)
            usage = response.usage
            return raw, {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "latency_ms": latency_ms,
                "model": model,
            }
        except Exception as exc:
            last_error = exc
            log.warning(
                "Descriptor appel échoué (attempt %d/%d): %s",
                attempt + 1,
                MAX_SYNC_RETRIES,
                exc,
            )
            if attempt < MAX_SYNC_RETRIES - 1:
                _sleep_before_retry(attempt)
                continue

    raise LLMCallError("Descriptor: épuisé les retries") from last_error


def call_classifier(
    client: OpenAI,
    model: str,
    axis: str,
    labels: list[str],
    perceiver_output: str,
    caption: str | None,
    post_scope: str,
    posted_at: datetime | None = None,
) -> tuple[str, str, dict]:
    """Appelle un classifieur text-only via tool calling."""
    messages = build_classifier_messages(
        axis,
        perceiver_output,
        caption,
        post_scope,
        posted_at=posted_at,
    )
    tool = build_classifier_tool(axis, labels)
    tool_name = tool["function"]["name"]

    start = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(MAX_SYNC_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[tool],
                tool_choice="auto",
                temperature=0.0,
            )
            if not response.choices:
                raise RuntimeError(f"Classifier {axis}: réponse vide")

            choice = response.choices[0]
            if not choice.message.tool_calls:
                raise RuntimeError(
                    f"Classifier {axis}: pas de tool_call dans la réponse "
                    f"(content={choice.message.content!r})"
                )

            tool_call = choice.message.tool_calls[0]
            if tool_call.function.name != tool_name:
                raise RuntimeError(
                    f"Classifier {axis}: nom de tool inattendu '{tool_call.function.name}'"
                )

            label, confidence, reasoning = parse_classifier_arguments(
                tool_call.function.arguments,
                axis,
                labels,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            usage = response.usage
            return label, confidence, {
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "latency_ms": latency_ms,
                "model": model,
                "reasoning": reasoning,
            }
        except Exception as exc:
            last_error = exc
            log.warning(
                "Classifier %s appel échoué (attempt %d/%d): %s",
                axis,
                attempt + 1,
                MAX_SYNC_RETRIES,
                exc,
            )
            if attempt < MAX_SYNC_RETRIES - 1:
                _sleep_before_retry(attempt)
                continue

    raise LLMCallError(f"Classifier {axis}: épuisé les retries") from last_error


__all__ = [
    "build_classifier_messages",
    "build_descriptor_messages",
    "call_classifier",
    "call_descriptor",
    "parse_classifier_arguments",
]
