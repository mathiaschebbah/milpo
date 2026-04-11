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


_ERA_BLOCK_POST_2024 = """## Cadrage temporel — post PUBLIÉ EN 2024 OU APRÈS

Applique le **test du viewer Instagram** (règle de priorité forte) :

Imagine un utilisateur Instagram qui scrolle dans son feed, SANS LIRE la caption,
et voit uniquement les images du post. S'arrêterait-il parce que la photo est
BELLE, ESTHÉTIQUE, SURPRENANTE ou VISUELLEMENT FRAPPANTE ?

- Si OUI et que la beauté visuelle est la raison principale de l'arrêt → SHOWING,
  probable `post_mood` ou `post_shooting` (même si la caption mentionne un événement).
- Si NON ou si la photo a besoin de la caption pour être comprise → TELLING,
  probable `post_news` / `post_anniversaire` / `post_interview`.

La taxonomie moderne (≥ 2024) reflète des codes éditoriaux où la beauté prime
souvent sur le texte."""

_ERA_BLOCK_PRE_2024 = ""  # Pas d'instructions additionnelles pour les posts legacy.
# Le LLM s'appuie uniquement sur la taxonomie neutre et les exclusions
# déjà présentes dans post_mood/post_news/post_anniversaire. Ajouter des
# instructions ici introduirait du bruit (référence à des concepts que le
# LLM ne verrait pas autrement, comme le "test du viewer Instagram" qui
# est spécifique à l'injection post-2024).


def build_classifier_messages(
    features_json: str,
    caption: str | None,
    instructions: str,
    descriptions_taxonomiques: str,
    posted_at: datetime | None = None,
) -> list[dict]:
    """Construit les messages pour un classifieur text-only.

    Le cadrage temporel (era) est routé dynamiquement :
    - posted_at >= 2024-01-01 : injecte le test du viewer Instagram (beauté prime)
    - posted_at < 2024-01-01 : injecte la règle legacy TELLING-prioritaire
    """
    system = (
        f"{instructions}\n\n"
        f"## Descriptions des labels\n\n"
        f"{descriptions_taxonomiques}"
    )

    date_block = ""
    era_block = ""
    if posted_at is not None:
        date_block = f"## Date de publication\n\n{posted_at.date().isoformat()}\n\n"
        if posted_at.year >= 2024:
            era_block = _ERA_BLOCK_POST_2024 + "\n\n"
        else:
            era_block = _ERA_BLOCK_PRE_2024 + "\n\n"

    user_text = (
        f"{era_block}"
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
