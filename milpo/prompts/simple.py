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

from milpo.prompts.classifier import PROCEDURE_BY_AXIS

# ─── Bloc 1 — ROLE (system) ─────────────────────────────────────────────────

ROLE = (
    "Tu es un classificateur multimodal de posts Instagram pour le média Views (@viewsfrance).\n"
    "Ta tâche est de classifier un post sur trois axes en un seul appel : "
    "visual_format, category, strategy.\n"
    "Tu classes des formats éditoriaux, des sujets et des intentions. "
    "Privilégie les signaux de forme sur le sujet traité pour visual_format."
)

# ─── Bloc 2 — CONTEXT + OUTPUT (system) ─────────────────────────────────────

CONTEXT = (
    "Tu reçois les images ou la vidéo du post, sa caption, une grille\n"
    "d'observation et les descriptions des classes pour chaque axe. Ces\n"
    "descriptions sont ta grille de lecture : tu dois t'y référer et\n"
    "raisonner en fonction d'elles."
)

OUTPUT_REASONING = (
    "Dans reasoning, explicite pour chaque axe :\n"
    "1. Les signaux observés dans les images, la caption et la grille d'observation.\n"
    "2. Les règles SIGNAL_OBLIGATOIRE et EXCLUT appliquées.\n"
    "3. Les hésitations rencontrées.\n"
    "Puis choisis un label par axe."
)

GUARDRAIL = "Chaque label doit venir de l'enum correspondante fournie."

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
    return f"{ROLE}\n\n{CONTEXT}\n\n{OUTPUT_REASONING}\n\n{GUARDRAIL}"


def build_user_intro(
    rendered_questions: str,
    vf_taxonomy: str,
    cat_taxonomy: str,
    strat_taxonomy: str,
) -> str:
    """Texte qui ouvre le user message, juste avant les images."""
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
