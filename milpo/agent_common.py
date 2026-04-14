"""Builders et validateurs partagés par les adaptateurs sync/async.

Les blocs de prompt ASSIST vivent dans `milpo.prompts` ; ce module ne fait
que l'adaptation vers le format OpenAI `messages` (list[dict] avec roles,
images inlinées comme image_url).
"""

from __future__ import annotations

from datetime import datetime

from milpo.prompts import alma, classifier
from milpo.schemas import ClassifierDecision
from milpo.taxonomy_renderer import render_questions_for_scope


def build_descriptor_messages(
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    scope: str = "FEED",
) -> list[dict]:
    """Construit les messages ASSIST pour le descripteur multimodal."""
    del instructions, descriptions_taxonomiques, media_types

    rendered_questions = render_questions_for_scope(scope.upper())

    content: list[dict] = [{"type": "text", "text": alma.build_user_intro(rendered_questions)}]
    for url in media_urls:
        # Gemini via l'endpoint OpenAI-compatible accepte les vidéos comme image_url
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": alma.build_user_caption(caption)})

    return [
        {"role": "system", "content": alma.build_system()},
        {"role": "user", "content": content},
    ]


def build_classifier_messages(
    axis: str,
    perceiver_output: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    posted_at: datetime | None = None,
) -> list[dict]:
    """Construit les messages ASSIST pour un classifieur text-only."""
    del instructions

    return [
        {"role": "system", "content": classifier.build_system(axis)},
        {
            "role": "user",
            "content": classifier.build_user(
                axis=axis,
                perceiver_output=perceiver_output,
                caption=caption,
                descriptions_taxonomiques=descriptions_taxonomiques,
                posted_at=posted_at,
            ),
        },
    ]


def _normalize_label(label: str) -> str:
    """Normalise un label pour comparaison : retire accents + lowercase.

    Gemini Flash Lite ne respecte pas toujours strictement les enums du tool
    schema (ex : génère "société" au lieu de "societe"). On tente une
    normalisation accent-insensible avant de lever une erreur.
    """
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", label)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.lower()


def parse_classifier_arguments(arguments: str, axis: str, labels: list[str]) -> tuple[str, str, str]:
    """Parse et valide les arguments d'un tool_call de classifieur.

    Retourne (label, confidence, reasoning). Le reasoning est optionnel
    pour rétrocompatibilité (anciens schemas sans CoT) — défaut "".

    Tolère une petite imprécision du LLM sur les accents via une
    normalisation accent-insensible (ex : "société" → matche "societe").
    """
    parsed = ClassifierDecision.model_validate_json(arguments)
    if parsed.label in labels:
        return parsed.label, parsed.confidence, parsed.reasoning

    # Fallback : match accent-insensible
    normalized_target = _normalize_label(parsed.label)
    for valid_label in labels:
        if _normalize_label(valid_label) == normalized_target:
            return valid_label, parsed.confidence, parsed.reasoning

    raise RuntimeError(f"Classifier {axis}: label invalide '{parsed.label}' (hors enum)")
