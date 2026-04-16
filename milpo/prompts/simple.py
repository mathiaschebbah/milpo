"""Prompts du classifieur multimodal simple (Template C — 1 appel ASSIST).

Variante ASSIST où le percepteur est fusionné dans le classifieur : le modèle
reçoit les images, la caption, les questions ASSIST (grille d'observation) et
les trois taxonomies avec leurs procédures par axe, puis produit les trois
labels en un seul appel multimodal.

Réutilise volontairement les procédures par axe du classifieur Joker
(`classifier.PROCEDURE_BY_AXIS`) pour rester iso côté décision. Ce qui
change : l'input est multimodal comme Alma au lieu d'une analyse textuelle
préalable.

L'assemblage final en list[dict] OpenAI vit dans
`milpo.agent_common.build_simple_messages`.
"""

from __future__ import annotations

from datetime import datetime

from milpo.prompts import alma
from milpo.prompts.classifier import PROCEDURE_BY_AXIS

# Structure miroir d'Alma : PERSONA + CONTEXT + OUTPUT_RULES.
# - PERSONA : identique à Alma (réutilisé tel quel).
# - CONTEXT : reprend la phrase d'entrée d'Alma mais remplace "tu décris"
#   par la tâche de classification 3-axes.
# - OUTPUT_RULES : format de sortie (reasoning CoT + label par enum).

PERSONA = alma.PERSONA

CONTEXT = (
    "Tu reçois les images ou la vidéo d'un post Instagram de Views, sa caption,\n"
    "et son audio si applicable.\n\n"
    "Tu dois classifier ce post sur trois axes : visual_format, category, strategy.\n"
    "La caption et les images sont à analyser de manière conjointe. Privilégie\n"
    "les signaux de forme sur le sujet traité pour visual_format."
)

OUTPUT_RULES = (
    "Dans reasoning, explicite pour chaque axe :\n"
    "1. Les signaux observés dans les images et la caption.\n"
    "2. Les règles SIGNAL_OBLIGATOIRE et EXCLUT appliquées.\n"
    "3. Les hésitations rencontrées.\n"
    "Puis choisis un label par axe. Chaque label doit venir de l'enum correspondante fournie."
)

# ─── Bloc 3 — USER MESSAGE (headers) ────────────────────────────────────────

USER_QUESTIONS_HEADER = "Grille d'observation :"
USER_VF_HEADER = "Descriptions des classes — axe visual_format :"
USER_CAT_HEADER = "Descriptions des classes — axe category :"
USER_STRAT_HEADER = "Descriptions des classes — axe strategy :"
USER_PROCEDURE_HEADER = "NON NÉGOCIABLE - Suis cette procédure axe par axe :"
USER_MEDIA_LABEL = "Voici le média :"
USER_POSTED_AT_HEADER = "Date de publication :"
USER_POSTED_AT_MISSING = "(inconnue)"
USER_CAPTION_HEADER = "Caption du post :"
USER_CAPTION_MISSING = "(pas de caption)"


def build_system() -> str:
    """Assemble le system message du classifieur simple multimodal."""
    return f"{PERSONA}\n\n{CONTEXT}\n\n{OUTPUT_RULES}"


def build_user_intro(
    rendered_questions: str,
    vf_taxonomy: str,
    cat_taxonomy: str,
    strat_taxonomy: str,
    *,
    no_assist: bool = False,
) -> str:
    """Texte qui ouvre le user message, juste avant les images.

    Si no_assist=True : envoie seulement les taxonomies, sans questions
    ASSIST ni procédures par axe. Point de référence naïf pour l'ablation.
    """
    if no_assist:
        return (
            f"{USER_VF_HEADER}\n\n"
            f"{vf_taxonomy}\n\n"
            f"{USER_CAT_HEADER}\n\n"
            f"{cat_taxonomy}\n\n"
            f"{USER_STRAT_HEADER}\n\n"
            f"{strat_taxonomy}\n\n"
            f"{USER_MEDIA_LABEL}"
        )
    procedure_lines = "\n".join(
        f"{axis} : {PROCEDURE_BY_AXIS[axis]}"
        for axis in ("visual_format", "category", "strategy")
    )
    return (
        f"{USER_QUESTIONS_HEADER}\n\n"
        f"{rendered_questions}\n\n"
        f"{USER_VF_HEADER}\n\n"
        f"{vf_taxonomy}\n\n"
        f"{USER_CAT_HEADER}\n\n"
        f"{cat_taxonomy}\n\n"
        f"{USER_STRAT_HEADER}\n\n"
        f"{strat_taxonomy}\n\n"
        f"{USER_PROCEDURE_HEADER}\n"
        f"{procedure_lines}\n\n"
        f"{USER_MEDIA_LABEL}"
    )


def _format_posted_at(posted_at: datetime | None) -> str:
    if posted_at is None:
        return USER_POSTED_AT_MISSING
    return posted_at.date().isoformat()


def build_user_caption(caption: str | None, posted_at: datetime | None) -> str:
    """Texte de fin du user message, posé après les images."""
    return (
        f"\n{USER_POSTED_AT_HEADER}\n"
        f"{_format_posted_at(posted_at)}\n\n"
        f"{USER_CAPTION_HEADER}\n"
        f"{caption or USER_CAPTION_MISSING}"
    )
