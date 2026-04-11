"""Builders et validateurs partagés par les adaptateurs sync/async."""

from __future__ import annotations

from datetime import datetime

from milpo.schemas import ClassifierDecision


def build_descriptor_messages(
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
) -> list[dict]:
    """Construit les messages pour le descripteur multimodal."""
    system = (
        f"{instructions}\n\n"
        f"## Critères discriminants à observer\n\n"
        f"{descriptions_taxonomiques}"
    )

    content: list[dict] = []
    for url, media_type in zip(media_urls, media_types):
        # Gemini via l'endpoint OpenAI-compatible accepte les vidéos comme image_url
        content.append({"type": "image_url", "image_url": {"url": url}})

    content.append({
        "type": "text",
        "text": f"Caption du post :\n{caption or '(pas de caption)'}",
    })

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def parse_classifier_arguments(arguments: str, axis: str, labels: list[str]) -> tuple[str, str, str]:
    """Parse et valide les arguments d'un tool_call de classifieur.

    Retourne (label, confidence, reasoning). Le reasoning est optionnel
    pour rétrocompatibilité (anciens schemas sans CoT) — défaut "".
    """
    parsed = ClassifierDecision.model_validate_json(arguments)
    if parsed.label not in labels:
        raise RuntimeError(f"Classifier {axis}: label invalide '{parsed.label}' (hors enum)")
    return parsed.label, parsed.confidence, parsed.reasoning


def build_classifier_messages(
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    posted_at: datetime | None = None,
) -> list[dict]:
    """Construit les messages pour un classifieur text-only."""
    system = (
        f"{instructions}\n\n"
        f"## Descriptions des labels\n\n"
        f"{descriptions_taxonomiques}"
    )

    date_block = ""
    if posted_at is not None:
        date_block = f"## Date de publication\n\n{posted_at.date().isoformat()}\n\n"

    user_text = (
        f"## Analyse du post\n\n"
        f"{features_json}\n\n"
        f"{date_block}"
        f"## Caption du post\n\n"
        f"{caption or '(pas de caption)'}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
