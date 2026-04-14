"""Prompts du classifieur text-only (Template B — Prompt Agent Joker).

Aligné sur les 3 templates du vault Obsidian :
- `Joker/Prompt Agent Joker.md` (visual_format)
- `Joker/Prompt Agent Joker — category.md`
- `Joker/Prompt Agent Joker — strategy.md`

Ce qui varie par axe :
- `ROLE_HINT_BY_AXIS` : ligne 3 du ROLE (priorité format / sujet / intention)
- `STEP_1_BY_AXIS`    : type de signaux à identifier (visuels / thématiques / commerciaux)
- `PROCEDURE_BY_AXIS` : étape 2 de la procédure user (règle de décision dominante)

Ce qui est commun aux 3 axes : CONTEXT, OUTPUT_REASONING, GUARDRAIL, headers user,
étapes 3 et 4 de la procédure.

NB étape 4 : le Template Joker prévoit « utilise le joker ». Comme le tool joker
n'est pas encore implémenté (cf. `Joker/Architecture.md`), le code porte un
fallback heuristique (« choisis celle dont le SIGNAL_OBLIGATOIRE matche le mieux »).
Quand le joker sera branché, remplacer `USER_PROCEDURE_STEP_4` par la formulation
du template.

L'assemblage final en list[dict] OpenAI vit dans
`milpo.agent_common.build_classifier_messages`.
"""

from __future__ import annotations

from datetime import datetime

# ─── Bloc 1 — ROLE (system) ─────────────────────────────────────────────────

ROLE_LINE_1 = "Tu es un classificateur {axis} pour le média Views (@viewsfrance)."
ROLE_LINE_2 = "Ta tâche est de classifier un post Instagram en fonction de l'axe {axis}."

ROLE_HINT_BY_AXIS: dict[str, str] = {
    "visual_format": (
        "Tu classes des formats éditoriaux, pas des thèmes. "
        "Privilégie les signaux de forme sur le sujet traité."
    ),
    "category": (
        "Tu classes des catégories éditoriales. "
        "Privilégie le sujet principal du post sur sa mise en forme."
    ),
    "strategy": (
        "Tu classes la stratégie éditoriale ou commerciale du post. "
        "Privilégie les signaux de partenariat et d'intention dominante."
    ),
}

# ─── Bloc 2 — CONTEXT + OUTPUT (system) ─────────────────────────────────────

CONTEXT = (
    "Tu reçois l'analyse textuelle du percepteur, la caption du post,\n"
    "et les descriptions des classes. Ces descriptions sont ta grille\n"
    "de lecture. Tu dois t'y référer et raisonner en fonction d'elles."
)

OUTPUT_REASONING = (
    "Dans reasoning, explicite :\n"
    "1. Les signaux identifiés dans la description du percepteur.\n"
    "2. Les règles SIGNAL_OBLIGATOIRE et EXCLUT appliquées.\n"
    "3. Les hésitations rencontrées.\n"
    "Puis choisis le label."
)

GUARDRAIL = "Le label doit venir de l'enum fournie."

# ─── Bloc 3 — USER MESSAGE (taxonomie + procédure + data) ──────────────────

STEP_1_BY_AXIS: dict[str, str] = {
    "visual_format": "1. Examine la description du percepteur. Identifie les signaux visuels.",
    "category": "1. Examine la description du percepteur. Identifie les signaux thématiques et sémantiques.",
    "strategy": "1. Examine la description du percepteur. Identifie les signaux commerciaux et de partenariat.",
}

PROCEDURE_BY_AXIS: dict[str, str] = {
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

USER_DESCRIPTIONS_HEADER = "Voici les descriptions des classes à appliquer :"
USER_PROCEDURE_HEADER = "NON NÉGOCIABLE - Suis cette procédure :"
USER_PROCEDURE_STEP_3 = "3. Applique les SIGNAL_OBLIGATOIRE et EXCLUT des descriptions ci-dessus."
USER_PROCEDURE_STEP_4 = (
    "4. Si tu hésites entre deux classes, choisis celle dont le SIGNAL_OBLIGATOIRE matche le mieux."
)
USER_PERCEPTEUR_HEADER = "Description du percepteur :"
USER_POSTED_AT_HEADER = "Date de publication :"
USER_CAPTION_HEADER = "Caption du post :"
USER_CAPTION_MISSING = "(pas de caption)"
USER_POSTED_AT_MISSING = "(inconnue)"


def build_system(axis: str) -> str:
    """Assemble le system message du classifieur pour un axe donné."""
    role = (
        f"{ROLE_LINE_1.format(axis=axis)}\n"
        f"{ROLE_LINE_2.format(axis=axis)}\n"
        f"{ROLE_HINT_BY_AXIS[axis]}"
    )
    return f"{role}\n\n{CONTEXT}\n\n{OUTPUT_REASONING}\n\n{GUARDRAIL}"


def _format_posted_at(posted_at: datetime | None) -> str:
    if posted_at is None:
        return USER_POSTED_AT_MISSING
    return posted_at.date().isoformat()


def _axis_scope(axis: str, post_scope: str) -> str:
    """Convertit (axis, post_scope FEED/REELS) en scope YAML taxonomie."""
    if axis == "visual_format":
        return post_scope.upper()
    if axis == "category":
        return "CATEGORY"
    if axis == "strategy":
        return "STRATEGY"
    raise ValueError(f"Axe inconnu : {axis!r}")


def build_user(
    axis: str,
    perceiver_output: str,
    caption: str | None,
    posted_at: datetime | None,
    post_scope: str,
) -> str:
    """Assemble le user message du classifieur.

    La taxonomie canonique est chargée ici depuis les YAML du vault via
    `render_taxonomy_for_scope` — source de vérité unique.
    """
    from milpo.taxonomy_renderer import render_taxonomy_for_scope

    descriptions_taxonomiques = render_taxonomy_for_scope(_axis_scope(axis, post_scope))

    return (
        f"{USER_DESCRIPTIONS_HEADER}\n\n"
        f"{descriptions_taxonomiques}\n\n"
        f"{USER_PROCEDURE_HEADER}\n"
        f"{STEP_1_BY_AXIS[axis]}\n"
        f"2. {PROCEDURE_BY_AXIS[axis]}\n"
        f"{USER_PROCEDURE_STEP_3}\n"
        f"{USER_PROCEDURE_STEP_4}\n\n"
        f"{USER_PERCEPTEUR_HEADER}\n"
        f"{perceiver_output}\n\n"
        f"{USER_POSTED_AT_HEADER}\n"
        f"{_format_posted_at(posted_at)}\n\n"
        f"{USER_CAPTION_HEADER}\n"
        f"{caption or USER_CAPTION_MISSING}"
    )
