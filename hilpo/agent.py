"""Agents HILPO : descripteur multimodal et classifieurs text-only."""

from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from hilpo.schemas import DescriptorFeatures


# ── Descripteur multimodal ─────────────────────────────────────


def build_descriptor_messages(
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
) -> list[dict]:
    """Construit les messages pour le descripteur multimodal.

    Args:
        media_urls: URLs signées GCS (images ou vidéos).
        media_types: Type de chaque média ('IMAGE' ou 'VIDEO').
        caption: Caption du post Instagram.
        instructions: Instructions I_t optimisables par HILPO.
        descriptions_taxonomiques: Critères discriminants Δ^m.
    """
    system = (
        f"{instructions}\n\n"
        f"## Critères discriminants à observer\n\n"
        f"{descriptions_taxonomiques}"
    )

    content: list[dict] = []

    # Médias (images et vidéos)
    for url, mtype in zip(media_urls, media_types):
        if mtype == "VIDEO":
            content.append({
                "type": "video_url",
                "video_url": {"url": url},
            })
        else:
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

    # Caption
    caption_text = caption or "(pas de caption)"
    content.append({
        "type": "text",
        "text": f"Caption du post :\n{caption_text}",
    })

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def call_descriptor(
    client: OpenAI,
    model: str,
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
) -> tuple[DescriptorFeatures, dict]:
    """Appelle le descripteur multimodal et retourne les features.

    Returns:
        Tuple (features, api_usage) avec les métriques d'appel.
    """
    messages = build_descriptor_messages(
        media_urls, media_types, caption,
        instructions, descriptions_taxonomiques,
    )

    # Schema JSON pour structured output
    response_schema = DescriptorFeatures.model_json_schema()

    start = time.monotonic()
    response = client.chat.completions.create(
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
    api_usage = {
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "latency_ms": latency_ms,
        "model": model,
    }

    return features, api_usage


# ── Classifieur text-only (tool use avec enum fermé) ──────────


def build_classifier_tool(
    axis: str,
    labels: list[str],
) -> dict:
    """Construit la définition du tool pour un classifieur.

    Args:
        axis: Nom de l'axe (category, visual_format, strategy).
        labels: Liste des labels valides (enum fermé).
    """
    return {
        "type": "function",
        "function": {
            "name": f"classify_{axis}",
            "description": f"Classifie le post sur l'axe '{axis}'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": labels,
                        "description": f"Le label {axis} prédit.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Niveau de confiance.",
                    },
                },
                "required": ["label", "confidence"],
                "additionalProperties": False,
            },
        },
    }


def build_classifier_messages(
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
) -> list[dict]:
    """Construit les messages pour un classifieur text-only."""
    system = (
        f"{instructions}\n\n"
        f"## Descriptions des labels\n\n"
        f"{descriptions_taxonomiques}"
    )

    user_text = (
        f"## Features extraites du post\n\n"
        f"```json\n{features_json}\n```\n\n"
        f"## Caption du post\n\n"
        f"{caption or '(pas de caption)'}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]


def call_classifier(
    client: OpenAI,
    model: str,
    axis: str,
    labels: list[str],
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
) -> tuple[str, str, dict]:
    """Appelle un classifieur text-only avec tool use.

    Returns:
        Tuple (label, confidence, api_usage).
    """
    messages = build_classifier_messages(
        features_json, caption,
        instructions, descriptions_taxonomiques,
    )
    tool = build_classifier_tool(axis, labels)

    start = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": f"classify_{axis}"}},
        temperature=0.1,
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    # Extraire le tool call
    choice = response.choices[0]
    tool_call = choice.message.tool_calls[0]
    result = json.loads(tool_call.function.arguments)
    label = result["label"]
    confidence = result.get("confidence", "medium")

    usage = response.usage
    api_usage = {
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
        "latency_ms": latency_ms,
        "model": model,
    }

    return label, confidence, api_usage
