"""Builders et validateurs partagés par les adaptateurs sync/async."""

from __future__ import annotations

from datetime import datetime

from milpo.schemas import ClassifierDecision
from milpo.taxonomy_renderer import render_questions_for_scope

# Prompts ASSIST hardcodés depuis le vault Obsidian. Les anciens prompts BDD
# restent chargés plus haut pour compatibilité, mais ils ne pilotent plus
# l'inférence de production.

ALMA_SYSTEM = """Tu es Alma, analyste visuelle pour Views (@viewsfrance).

Formée en communication mode et luxe, tu as travaillé dans le stylisme photo et la production média (presse, webmagazines, shootings). Tu as une culture profonde de la mode, de l'art et de la musique, et tu es toujours en quête d'actualité. Chaque détail visuel compte pour toi. Composition, logos, typographie, hiérarchie de l'image, tu es méticuleuse sur tous ces points, tant ils te passionnent, et tu t'entraînes à les reconnaître depuis longtemps.

Tu es d'une nature très curieuse, appliquée. Tu sais questionner ton travail et raisonner concrètement sur des problèmes culturels.

Tu reçois les images ou la vidéo d'un post Instagram de Views, sa caption, et son audio si applicable.

Tu dois produire une analyse visuelle détaillée de ce post. Tu ne classes pas, tu décris. La caption et les images sont à analyser de manière conjointe. Un autre agent classifiera à partir de ta description.

Pour chaque question, réponds factuellement et en détail. Décris ce que tu vois, pas ce que tu devines. Ne mentionne aucun nom de format, catégorie ou stratégie. Ne fais pas de résumé éditorial. Réponds uniquement aux clés demandées."""

CLASSIFIER_AXIS_HINTS = {
    "visual_format": "Tu classes des formats éditoriaux, pas des thèmes. Privilégie les signaux de forme sur le sujet traité.",
    "category": "Tu classes des catégories éditoriales. Privilégie le sujet principal du post sur sa mise en forme.",
    "strategy": "Tu classes la stratégie éditoriale ou commerciale du post. Privilégie les signaux de partenariat et d'intention dominante.",
}

CLASSIFIER_STEP_2 = {
    "visual_format": (
        "Décide la classe à partir du format dominant. Priorise les indices de structure, "
        "de composition, d'audio, de montage, de logo et de dispositif éditorial. Le "
        "sujet traité n'emporte la décision que s'il correspond aussi au format dominant "
        "ou à un signal obligatoire explicite de la classe."
    ),
    "category": (
        "Décide la classe à partir du sujet principal. Priorise le domaine, les personnes, "
        "les œuvres, les objets, les événements ou les pratiques décrits. La forme "
        "éditoriale n'emporte la décision que si elle éclaire explicitement ce sujet "
        "principal ou un signal obligatoire de la classe."
    ),
    "strategy": (
        "Décide la classe à partir de l'intention éditoriale ou commerciale dominante. "
        "Priorise les mentions de partenariat, les logos de marque partenaire, les relais "
        "vers un site commercial et les signaux de sponsorisation. Le sujet traité "
        "n'emporte la décision que s'il confirme aussi un signal obligatoire explicite "
        "de la classe."
    ),
}


def _build_classifier_system(axis: str) -> str:
    return f"""Tu es un classificateur {axis} pour le média Views (@viewsfrance).
Ta tâche est de classifier un post Instagram en fonction de l'axe {axis}.
{CLASSIFIER_AXIS_HINTS[axis]}

Tu reçois l'analyse textuelle du percepteur, la caption du post,
et les descriptions des classes. Ces descriptions sont ta grille
de lecture. Tu dois t'y référer et raisonner en fonction d'elles.

Dans reasoning, explicite :
1. Les signaux identifiés dans la description du percepteur.
2. Les règles SIGNAL_OBLIGATOIRE et EXCLUT appliquées.
3. Les hésitations rencontrées.
Puis choisis le label.

Le label doit venir de l'enum fournie."""


def _build_classifier_user_message(
    axis: str,
    features_json: str,
    caption: str | None,
    descriptions_taxonomiques: str,
    posted_at: datetime | None,
) -> str:
    return f"""Voici les descriptions des classes à appliquer :

{descriptions_taxonomiques}

NON NÉGOCIABLE - Suis cette procédure :
1. Examine la description du percepteur. Identifie les signaux saillants.
2. {CLASSIFIER_STEP_2[axis]}
3. Applique les SIGNAL_OBLIGATOIRE et EXCLUT des descriptions ci-dessus.
4. Si tu hésites entre deux classes, choisis celle dont le SIGNAL_OBLIGATOIRE matche le mieux.

Description du percepteur :
{features_json}

Date de publication :
{_format_posted_at(posted_at)}

Caption du post :
{caption or '(pas de caption)'}"""


def _format_posted_at(posted_at: datetime | None) -> str:
    if posted_at is None:
        return "(inconnue)"
    return posted_at.date().isoformat()


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

    content: list[dict] = []
    content.append({
        "type": "text",
        "text": (
            "Analyse ce post en répondant aux questions suivantes :\n\n"
            f"{rendered_questions}\n\n"
            "Voici le média :"
        ),
    })
    for url in media_urls:
        # Gemini via l'endpoint OpenAI-compatible accepte les vidéos comme image_url
        content.append({"type": "image_url", "image_url": {"url": url}})

    content.append({
        "type": "text",
        "text": f"\nCaption du post :\n{caption or '(pas de caption)'}",
    })

    return [
        {"role": "system", "content": ALMA_SYSTEM},
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


def build_classifier_messages(
    axis: str,
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    posted_at: datetime | None = None,
) -> list[dict]:
    """Construit les messages ASSIST pour un classifieur text-only."""
    del instructions

    system = _build_classifier_system(axis)
    user_text = _build_classifier_user_message(
        axis=axis,
        features_json=features_json,
        caption=caption,
        descriptions_taxonomiques=descriptions_taxonomiques,
        posted_at=posted_at,
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
