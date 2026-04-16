"""Builders et validateurs partagés par les adaptateurs sync/async.

Les blocs de prompt ASSIST vivent dans `milpo.prompts` ; ce module ne fait
que l'adaptation vers le format OpenAI `messages` (list[dict] avec roles,
images inlinées comme image_url). La taxonomie et les questions ASSIST
viennent des YAML du vault via `milpo.taxonomy_renderer`.
"""

from __future__ import annotations

import re
from datetime import datetime

from milpo.prompts import alma, classifier, simple
from milpo.schemas import ClassifierDecision, SimpleDecision
from milpo.taxonomy_renderer import (
    render_questions_for_scope,
    render_taxonomy_for_scope,
)


def build_descriptor_messages(
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    scope: str,
) -> list[dict]:
    """Construit les messages ASSIST pour le descripteur multimodal (Alma)."""
    del media_types  # Gemini accepte les vidéos comme image_url aussi.

    rendered_questions = render_questions_for_scope(scope.upper())

    content: list[dict] = [{"type": "text", "text": alma.build_user_intro(rendered_questions)}]
    for url in media_urls:
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
    post_scope: str,
    posted_at: datetime | None = None,
) -> list[dict]:
    """Construit les messages ASSIST pour un classifieur text-only."""
    return [
        {"role": "system", "content": classifier.build_system(axis)},
        {
            "role": "user",
            "content": classifier.build_user(
                axis=axis,
                perceiver_output=perceiver_output,
                caption=caption,
                posted_at=posted_at,
                post_scope=post_scope,
            ),
        },
    ]


def build_simple_messages(
    media_urls: list[str],
    media_types: list[str],
    caption: str | None,
    post_scope: str,
    posted_at: datetime | None = None,
    *,
    no_assist: bool = False,
) -> list[dict]:
    """Construit les messages pour le classifieur simple (1 appel multimodal).

    Si no_assist=True : taxonomies seules, sans questions ASSIST ni procédures.
    """
    del media_types

    scope = post_scope.upper()
    rendered_questions = render_questions_for_scope(scope)
    vf_taxonomy = render_taxonomy_for_scope(scope)
    cat_taxonomy = render_taxonomy_for_scope("CATEGORY")
    strat_taxonomy = render_taxonomy_for_scope("STRATEGY")

    intro = simple.build_user_intro(
        rendered_questions=rendered_questions,
        vf_taxonomy=vf_taxonomy,
        cat_taxonomy=cat_taxonomy,
        strat_taxonomy=strat_taxonomy,
        no_assist=no_assist,
    )
    content: list[dict] = [{"type": "text", "text": intro}]
    for url in media_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append(
        {"type": "text", "text": simple.build_user_caption(caption, posted_at)}
    )

    return [
        {"role": "system", "content": simple.build_system()},
        {"role": "user", "content": content},
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


def _match_label(raw: str, labels: list[str], axis: str) -> str:
    """Valide un label contre un enum avec fallback accent-insensible."""
    if raw in labels:
        return raw
    target = _normalize_label(raw)
    for valid_label in labels:
        if _normalize_label(valid_label) == target:
            return valid_label
    raise RuntimeError(f"Classifier {axis}: label invalide '{raw}' (hors enum)")


def parse_classifier_arguments(arguments: str, axis: str, labels: list[str]) -> tuple[str, str, str]:
    """Parse et valide les arguments d'un tool_call de classifieur.

    Retourne (label, confidence, reasoning). Le reasoning est optionnel
    pour rétrocompatibilité (anciens schemas sans CoT) — défaut "".

    Tolère une petite imprécision du LLM sur les accents via une
    normalisation accent-insensible (ex : "société" → matche "societe").
    """
    parsed = ClassifierDecision.model_validate_json(arguments)
    label = _match_label(parsed.label, labels, axis)
    return label, parsed.confidence, parsed.reasoning


def _extract_label_from_text(text: str, labels: list[str], axis: str) -> str:
    """Tente d'extraire un label depuis du texte libre (reasoning).

    Fallback quand le LLM omet un champ du tool call JSON mais mentionne
    le label correct dans son reasoning. Cherche le label le plus long
    qui apparaît dans le texte (priorité aux labels spécifiques).
    """
    import json as _json
    text_lower = text.lower()
    matches = [l for l in labels if l.lower() in text_lower]
    if not matches:
        kv_pattern = re.compile(rf'"{axis}"\s*:\s*"([^"]+)"')
        m = kv_pattern.search(text)
        if m:
            return _match_label(m.group(1), labels, axis)
        raise RuntimeError(
            f"Simple fallback {axis}: aucun label trouvé dans le reasoning"
        )
    return max(matches, key=len)


def parse_simple_arguments(
    arguments: str,
    vf_labels: list[str],
    cat_labels: list[str],
    strat_labels: list[str],
) -> tuple[str, str, str, str, str]:
    """Parse et valide les arguments d'un tool_call du classifieur simple.

    Retourne (visual_format, category, strategy, confidence, reasoning).
    Si le LLM omet des champs (bug Flash no-assist), tente de les extraire
    du reasoning ou du JSON brut via fallback.
    """
    import json as _json
    try:
        parsed = SimpleDecision.model_validate_json(arguments)
        return (
            _match_label(parsed.visual_format, vf_labels, "visual_format"),
            _match_label(parsed.category, cat_labels, "category"),
            _match_label(parsed.strategy, strat_labels, "strategy"),
            parsed.confidence,
            parsed.reasoning,
        )
    except Exception:
        pass

    raw = _json.loads(arguments)
    reasoning = raw.get("reasoning", "")
    confidence = raw.get("confidence", "high")
    vf = raw.get("visual_format")
    cat = raw.get("category")
    strat = raw.get("strategy")

    search_text = reasoning + " " + arguments
    if not vf:
        vf = _extract_label_from_text(search_text, vf_labels, "visual_format")
    if not cat:
        cat = _extract_label_from_text(search_text, cat_labels, "category")
    if not strat:
        strat = _extract_label_from_text(search_text, strat_labels, "strategy")

    return (
        _match_label(vf, vf_labels, "visual_format"),
        _match_label(cat, cat_labels, "category"),
        _match_label(strat, strat_labels, "strategy"),
        confidence,
        reasoning,
    )
