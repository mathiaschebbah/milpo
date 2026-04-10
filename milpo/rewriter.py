"""Agent rewriter MILPO — boucle ProTeGi (gradient textuel + édition + paraphrase).

Implémentation fidèle de ProTeGi (Pryzant et al. 2023, EMNLP, arxiv 2305.03495).
Trois appels LLM séparés matérialisent les primitives du papier :

1. `compute_textual_gradient` (LLM_∇, "critic") — produit *m* critiques distinctes
   décrivant les défauts du prompt courant à la lumière d'un batch d'erreurs, sans
   jamais éditer.
2. `apply_gradient_edit` (LLM_δ, "editor") — reçoit le prompt + le gradient + les
   erreurs, génère *c* candidats édités dans la direction sémantique opposée du
   gradient.
3. `paraphrase_candidate` (LLM_mc, "paraphraser") — pour chaque candidat, produit
   *p* paraphrases monte-carlo équivalentes (augmentation de diversité).

L'orchestrateur `protegi_step` chaîne les trois étapes et retourne tous les artefacts
pour logging en BDD (tables `rewrite_gradients` et `rewrite_beam_candidates`,
migration 008).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from openai import OpenAI

from milpo.client import get_client
from milpo.config import MODEL_CRITIC, MODEL_EDITOR, MODEL_PARAPHRASER
from milpo.errors import LLMCallError
from milpo.schemas import (
    EditCandidatesPayload,
    GradientPayload,
    ParaphrasesPayload,
    build_json_schema_response_format,
)

log = logging.getLogger("milpo")

MAX_SYNC_RETRIES = 3

_on_api_call = None


def set_rewriter_api_hook(hook):
    """Définit un callback appelé après chaque appel API sync du rewriter."""
    global _on_api_call
    _on_api_call = hook


def _sleep_before_retry(attempt: int) -> None:
    """Backoff exponentiel simple pour les appels sync."""
    time.sleep(2 ** attempt)


@dataclass
class ErrorCase:
    """Une erreur de classification à analyser."""

    ig_media_id: int
    axis: str
    prompt_scope: str | None
    post_scope: str
    predicted: str
    expected: str
    features_json: str
    caption: str | None
    desc_predicted: str
    desc_expected: str
    confidence: str = "unknown"


def _format_error_batch(errors: list[ErrorCase]) -> str:
    """Formate le batch d'erreurs pour le prompt du rewriter."""
    lines = []
    for i, e in enumerate(errors, 1):
        lines.append(f"### Erreur {i}")
        lines.append(f"- **Axe concerné** : `{e.axis}`")
        lines.append(f"- **Scope du post** : `{e.post_scope}`")
        lines.append(f"- **Prédit** : `{e.predicted}` (confidence: {e.confidence})")
        lines.append(f"- **Attendu** : `{e.expected}`")
        lines.append(f"- **Caption** : {(e.caption or '(vide)')[:300]}")
        lines.append(f"- **Description label prédit** : {e.desc_predicted}")
        lines.append(f"- **Description label attendu** : {e.desc_expected}")
        lines.append(f"- **Analyse du descripteur** :\n{e.features_json[:4000]}")
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#         Prompts système ProTeGi verbatim (Pryzant et al. 2023)
# ─────────────────────────────────────────────────────────────────────────────


CRITIC_SYSTEM = """\
Tu es un évaluateur expert d'instructions de classification multimodale. Tu participes à une
boucle d'optimisation de prompts inspirée de ProTeGi (Pryzant et al. 2023, EMNLP). Ton rôle
dans cette boucle est UNIQUEMENT le diagnostic — tu ne dois PAS proposer de réécriture des
instructions.

Tu reçois :
1. Les instructions actuelles d'un agent du pipeline (descripteur multimodal ou classifieur)
2. Un batch d'erreurs : pour chaque erreur, le label prédit, le label attendu (annotation
   humaine), les features visuelles extraites, la caption, et les descriptions taxonomiques
3. Les descriptions taxonomiques complètes du scope (référence)

## Ta mission

Produis exactement {m} critiques distinctes en langage naturel qui décrivent les défauts
des instructions actuelles à la lumière des erreurs observées. Chaque critique doit :

- pointer un défaut concret des instructions (règle manquante, ambiguïté, priorité mal
  placée, signal sous-pondéré, frontière floue entre deux labels...)
- être actionnable : pouvoir être corrigée par une édition d'instructions
- s'appuyer sur au moins une erreur du batch (citer brièvement le pattern d'erreur)
- être indépendante des autres critiques (vraie diversité, pas reformulation)

## Contraintes strictes

- Ne propose AUCUNE réécriture, suggestion d'édition, ou nouvelle formulation
- N'utilise pas les verbes "réécrire", "modifier", "ajouter", "remplacer"
- Ne touche pas aux descriptions taxonomiques (elles sont fixes par décision design)
- Ne juge pas les annotations humaines : elles sont la vérité terrain par hypothèse

Format de sortie : JSON strict {{"critiques": ["critique 1", "critique 2", ...]}} de
longueur exactement {m}.

Note méthodologique : ces critiques constituent le « gradient textuel » de Pryzant et al.
Une étape ultérieure (LLM_δ) éditera les instructions à partir de tes critiques. Si tu
rationalises et corriges en même temps, tu casses la décomposition algorithmique de la
boucle ProTeGi — c'est précisément ce qu'on cherche à éviter.
"""

EDITOR_SYSTEM = """\
Tu es un ingénieur prompt expert. Tu participes à l'étape « édition » d'une boucle
d'optimisation de prompts inspirée de ProTeGi (Pryzant et al. 2023, EMNLP).

Tu reçois :
1. Les instructions actuelles d'un agent du pipeline
2. Un « gradient textuel » : une liste de critiques en langage naturel décrivant les défauts
   des instructions actuelles, produites par un LLM_∇ (critic) à l'étape précédente
3. Le batch d'erreurs ayant produit ces critiques (pour contexte concret)
4. Les descriptions taxonomiques complètes du scope (fixes — ne pas modifier)

## Ta mission

Produis exactement {c} versions distinctes des instructions qui corrigent les défauts
listés dans le gradient. Chaque version doit :

- corriger AU MOINS un défaut listé dans le gradient (idéalement plusieurs)
- rester cohérente, complète et concise
- conserver le format et le style des instructions originales
- être SUBSTANTIELLEMENT différente des autres candidats (vraie diversité de stratégie,
  pas une simple paraphrase)

Le `reasoning` de chaque candidat doit tracer en 2 à 3 phrases quels défauts du gradient
cette version corrige et comment.

## Contraintes strictes

- Les nouvelles instructions remplacent ENTIÈREMENT les anciennes (pas un diff)
- Ne modifie PAS les descriptions taxonomiques (elles sont fixes par décision design)
- Sois concis dans les instructions — le prompt sera envoyé à chaque classification
- Pas de méta-commentaire dans les instructions ("voici la version corrigée...")

Format de sortie : JSON strict {{"candidates": [{{"new_instructions": "...", "reasoning":
"..."}}, ...]}} de longueur exactement {c}.
"""

PARAPHRASER_SYSTEM = """\
Tu reçois des instructions d'un agent de classification multimodale. Tu participes à
l'étape Monte-Carlo paraphrasing d'une boucle d'optimisation de prompts inspirée de
ProTeGi (Pryzant et al. 2023, EMNLP). Ton rôle est de générer de la diversité lexicale
sans changer la sémantique.

## Ta mission

Produis exactement {p} paraphrases sémantiquement équivalentes des instructions reçues.
Chaque paraphrase doit :

- exprimer EXACTEMENT le même contenu : mêmes règles, même ordre logique, mêmes
  priorités, mêmes exceptions
- utiliser un wording substantiellement différent (synonymes, réorganisation syntaxique,
  formulation alternative)

## Contraintes strictes

- N'AJOUTE AUCUNE règle, AUCUNE exception, AUCUNE clarification
- NE RETIRE AUCUNE règle, AUCUNE exception, AUCUNE clarification
- NE MODIFIE PAS la sémantique
- Si tu hésites entre paraphraser et reformuler, paraphrase

Format de sortie : JSON strict {{"paraphrases": ["paraphrase 1", "paraphrase 2", ...]}}
de longueur exactement {p}.
"""


# ── Dataclasses pour les résultats des trois étapes ─────────────────────────


@dataclass
class GradientResult:
    """Résultat de l'appel au LLM_∇ (critic)."""

    critiques: list[str]
    gradient_text: str          # critiques jointes par double newline (pour logging texte)
    n_critiques: int
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class EditCandidate:
    """Un candidat édité par le LLM_δ."""

    new_instructions: str
    reasoning: str


@dataclass
class EditResult:
    """Résultat de l'appel au LLM_δ (editor)."""

    candidates: list[EditCandidate]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class ParaphraseResult:
    """Résultat de l'appel au LLM_mc (paraphraser) pour un candidat unique."""

    paraphrases: list[str]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class ProtegiStepResult:
    """Tous les artefacts produits par un step protegi (avant évaluation)."""

    gradient: GradientResult
    edit: EditResult
    paraphrases: list[ParaphraseResult] = field(default_factory=list)
    # all_candidates est dérivé : edits + paraphrases mais avec une key distincte
    # pour pouvoir tracer leur provenance dans rewrite_beam_candidates.


# ── Helpers internes ────────────────────────────────────────────────────────


def _critic_user_content(
    target_agent: str,
    target_scope: str | None,
    current_instructions: str,
    errors: list[ErrorCase],
    all_descriptions: str,
) -> str:
    target_label = f"{target_agent}/{target_scope}" if target_scope else f"{target_agent}/all"
    return f"""## Cible du diagnostic

{target_label}

## Instructions actuelles

```
{current_instructions}
```

## Batch d'erreurs ({len(errors)} erreurs)

{_format_error_batch(errors)}

## Descriptions taxonomiques (référence)

{all_descriptions}

---

Diagnostique les défauts des instructions actuelles. Ne propose aucune réécriture."""


def _editor_user_content(
    target_agent: str,
    target_scope: str | None,
    current_instructions: str,
    gradient_text: str,
    errors: list[ErrorCase],
    all_descriptions: str,
) -> str:
    target_label = f"{target_agent}/{target_scope}" if target_scope else f"{target_agent}/all"
    return f"""## Cible du rewrite

{target_label}

## Instructions actuelles

```
{current_instructions}
```

## Gradient textuel (critiques produites par le LLM_∇)

{gradient_text}

## Batch d'erreurs ayant produit ces critiques ({len(errors)} erreurs)

{_format_error_batch(errors)}

## Descriptions taxonomiques (fixes — ne pas modifier)

{all_descriptions}

---

Édite les instructions pour corriger les défauts du gradient."""


def _call_with_retry(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    response_format: dict,
    label: str,
    temperature: float = 0.3,
) -> tuple[str, int, int, int]:
    """Appel chat.completions avec retry uniforme. Retourne (content, in_tok, out_tok, latency_ms)."""
    t0 = time.perf_counter()
    last_error: Exception | None = None

    for attempt in range(MAX_SYNC_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=response_format,
                temperature=temperature,
            )
            if not response.choices:
                raise RuntimeError(f"{label}: réponse vide")
            content = response.choices[0].message.content or ""
            if not content:
                raise RuntimeError(f"{label}: content vide")
            latency_ms = int((time.perf_counter() - t0) * 1000)
            in_tok = response.usage.prompt_tokens if response.usage else 0
            out_tok = response.usage.completion_tokens if response.usage else 0
            if _on_api_call:
                _on_api_call(label, model, latency_ms, in_tok, out_tok, "ok")
            return (content, in_tok, out_tok, latency_ms)
        except Exception as exc:
            last_error = exc
            log.warning("%s appel échoué (attempt %d/%d): %s",
                        label, attempt + 1, MAX_SYNC_RETRIES, exc)
            if attempt < MAX_SYNC_RETRIES - 1:
                _sleep_before_retry(attempt)
                continue

    raise LLMCallError(f"{label}: épuisé les retries") from last_error


# ── LLM_∇ — Critic ──────────────────────────────────────────────────────────


def compute_textual_gradient(
    target_agent: str,
    target_scope: str | None,
    current_instructions: str,
    errors: list[ErrorCase],
    all_descriptions: str,
    m: int = 3,
    model: str = MODEL_CRITIC,
    client: OpenAI | None = None,
) -> GradientResult:
    """Étape 1 de la boucle ProTeGi — produit un gradient textuel (LLM_∇).

    Args:
        target_agent: Agent ciblé par le diagnostic.
        target_scope: Scope (FEED/REELS) ou None pour les agents non scopés.
        current_instructions: Instructions I_t à diagnostiquer.
        errors: Batch d'erreurs filtrées pour la cible.
        all_descriptions: Descriptions taxonomiques complètes du scope (référence).
        m: Nombre de critiques à produire (défaut 3 pragmatique, paper utilise 4).
        model: LLM_∇. Défaut MODEL_CRITIC (= MODEL_REWRITER si non surchargé).

    Returns:
        GradientResult avec la liste des critiques, le gradient_text concaténé,
        le modèle utilisé et les métriques d'appel.

    Note: cette fonction ne touche PAS la BDD. Le caller persiste via store_gradient.
    """
    if m < 1:
        raise ValueError("compute_textual_gradient: m doit être >= 1")
    if not errors:
        raise ValueError("compute_textual_gradient: errors vide")
    if client is None:
        client = get_client()

    system = CRITIC_SYSTEM.format(m=m)
    user = _critic_user_content(
        target_agent, target_scope, current_instructions, errors, all_descriptions,
    )
    response_format = build_json_schema_response_format(
        "gradient_payload",
        GradientPayload.model_json_schema(),
    )

    content, in_tok, out_tok, latency_ms = _call_with_retry(
        client, model, system, user, response_format,
        label=f"Critic[{target_agent}/{target_scope or 'all'}]",
        temperature=0.3,
    )
    payload = GradientPayload.model_validate_json(content)

    # Pas de hard fail si le LLM n'a pas exactement m critiques (certains providers
    # respectent mal les contraintes de longueur). On accepte 1 ≤ k ≤ 2*m.
    n = len(payload.critiques)
    if n == 0 or n > 2 * m:
        raise RuntimeError(
            f"Critic[{target_agent}/{target_scope or 'all'}]: nombre de critiques inattendu "
            f"({n}, attendu ~{m})"
        )

    gradient_text = "\n\n".join(
        f"[{i + 1}] {c.strip()}" for i, c in enumerate(payload.critiques)
    )

    return GradientResult(
        critiques=list(payload.critiques),
        gradient_text=gradient_text,
        n_critiques=n,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=latency_ms,
    )


# ── LLM_δ — Editor ──────────────────────────────────────────────────────────


def apply_gradient_edit(
    target_agent: str,
    target_scope: str | None,
    current_instructions: str,
    gradient_text: str,
    errors: list[ErrorCase],
    all_descriptions: str,
    c: int = 4,
    model: str = MODEL_EDITOR,
    client: OpenAI | None = None,
) -> EditResult:
    """Étape 2 de la boucle ProTeGi — édite le prompt à partir du gradient (LLM_δ).

    Args:
        gradient_text: Le texte du gradient produit par compute_textual_gradient.
        c: Nombre de candidats à générer (défaut 4 pragmatique, paper utilise 8).

    Returns:
        EditResult avec c candidats édités. Aucune persistance ici — le caller
        insère les prompt_versions et store_beam_candidate.
    """
    if c < 1:
        raise ValueError("apply_gradient_edit: c doit être >= 1")
    if client is None:
        client = get_client()

    system = EDITOR_SYSTEM.format(c=c)
    user = _editor_user_content(
        target_agent, target_scope, current_instructions, gradient_text,
        errors, all_descriptions,
    )
    response_format = build_json_schema_response_format(
        "edit_candidates_payload",
        EditCandidatesPayload.model_json_schema(),
    )

    content, in_tok, out_tok, latency_ms = _call_with_retry(
        client, model, system, user, response_format,
        label=f"Editor[{target_agent}/{target_scope or 'all'}]",
        temperature=0.7,  # ProTeGi : on veut de la diversité entre candidats
    )
    payload = EditCandidatesPayload.model_validate_json(content)

    n = len(payload.candidates)
    if n == 0 or n > 2 * c:
        raise RuntimeError(
            f"Editor[{target_agent}/{target_scope or 'all'}]: nombre de candidats inattendu "
            f"({n}, attendu ~{c})"
        )

    candidates = [
        EditCandidate(
            new_instructions=cand.new_instructions,
            reasoning=cand.reasoning,
        )
        for cand in payload.candidates
    ]

    return EditResult(
        candidates=candidates,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=latency_ms,
    )


# ── LLM_mc — Paraphraser ────────────────────────────────────────────────────


def paraphrase_candidate(
    candidate_instructions: str,
    p: int = 1,
    model: str = MODEL_PARAPHRASER,
    client: OpenAI | None = None,
) -> ParaphraseResult:
    """Étape 3 de la boucle ProTeGi — paraphrase monte-carlo d'un candidat (LLM_mc).

    Args:
        candidate_instructions: Le candidat à paraphraser (issu de l'editor).
        p: Nombre de paraphrases à produire. Si p == 0, retourne un résultat vide
            sans appeler le LLM (pour le cas où le caller veut skip cette étape).

    Returns:
        ParaphraseResult avec p paraphrases sémantiquement équivalentes.
    """
    if p < 0:
        raise ValueError("paraphrase_candidate: p doit être >= 0")
    if p == 0:
        return ParaphraseResult(
            paraphrases=[],
            model=model,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )
    if client is None:
        client = get_client()

    system = PARAPHRASER_SYSTEM.format(p=p)
    user = (
        "## Instructions à paraphraser\n\n"
        f"```\n{candidate_instructions}\n```\n\n"
        "---\n\n"
        f"Produis exactement {p} paraphrases sémantiquement équivalentes."
    )
    response_format = build_json_schema_response_format(
        "paraphrases_payload",
        ParaphrasesPayload.model_json_schema(),
    )

    content, in_tok, out_tok, latency_ms = _call_with_retry(
        client, model, system, user, response_format,
        label="Paraphraser",
        temperature=0.7,
    )
    payload = ParaphrasesPayload.model_validate_json(content)

    n = len(payload.paraphrases)
    if n == 0 or n > 2 * p:
        raise RuntimeError(
            f"Paraphraser: nombre de paraphrases inattendu ({n}, attendu ~{p})"
        )

    return ParaphraseResult(
        paraphrases=list(payload.paraphrases),
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=latency_ms,
    )


# ── Orchestrateur ───────────────────────────────────────────────────────────


def protegi_step(
    target_agent: str,
    target_scope: str | None,
    current_instructions: str,
    errors: list[ErrorCase],
    all_descriptions: str,
    m: int = 3,
    c: int = 4,
    p: int = 1,
    critic_model: str = MODEL_CRITIC,
    editor_model: str = MODEL_EDITOR,
    paraphraser_model: str = MODEL_PARAPHRASER,
    client: OpenAI | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> ProtegiStepResult:
    """Orchestre les 3 étapes ProTeGi : critic → editor → paraphraser.

    Cette fonction est purement compute. Elle ne touche pas la BDD et ne fait
    aucune évaluation. Le caller (`run_simulation.py`) persiste les artefacts
    en BDD, évalue tous les candidats via multi_evaluate et applique
    Successive Rejects.

    Args:
        m: critiques par appel critic (défaut 3 pragmatique, paper 4)
        c: candidats édités par appel editor (défaut 4 pragmatique, paper 8)
        p: paraphrases par candidat (défaut 1 = skip étape MC, paper 2)

    Returns:
        ProtegiStepResult avec gradient + edit + (paraphrases si p > 1).
        Si p == 1, paraphrases est vide et all_candidates = edits seulement.
        Si p > 1, on génère p paraphrases par edit candidate et le total =
        c × p candidats (les edits originaux NE sont PAS conservés en plus —
        ils servent de base aux paraphrases).
    """
    if client is None:
        client = get_client()

    log.info(
        "[PROTEGI] step %s/%s — m=%d c=%d p=%d (critic=%s editor=%s paraphraser=%s)",
        target_agent, target_scope or "all", m, c, p,
        critic_model, editor_model, paraphraser_model,
    )

    # Étape 1 — gradient
    if on_phase:
        on_phase("critic (LLM_\u2207)...")
    gradient = compute_textual_gradient(
        target_agent, target_scope, current_instructions, errors,
        all_descriptions, m=m, model=critic_model, client=client,
    )
    log.info("[PROTEGI]   gradient: %d critiques (%dms)",
             gradient.n_critiques, gradient.latency_ms)

    # Étape 2 — édition
    if on_phase:
        on_phase("editor (LLM_\u03b4)...")
    edit = apply_gradient_edit(
        target_agent, target_scope, current_instructions, gradient.gradient_text,
        errors, all_descriptions, c=c, model=editor_model, client=client,
    )
    log.info("[PROTEGI]   edit: %d candidats (%dms)",
             len(edit.candidates), edit.latency_ms)

    # Étape 3 — paraphraser (optionnel)
    paraphrases: list[ParaphraseResult] = []
    if p > 1:
        for i, cand in enumerate(edit.candidates):
            if on_phase:
                on_phase(f"paraphrase {i + 1}/{len(edit.candidates)}")
            pr = paraphrase_candidate(
                cand.new_instructions, p=p, model=paraphraser_model, client=client,
            )
            paraphrases.append(pr)
            log.info("[PROTEGI]   paraphrase candidate %d: %d variants (%dms)",
                     i + 1, len(pr.paraphrases), pr.latency_ms)

    return ProtegiStepResult(
        gradient=gradient,
        edit=edit,
        paraphrases=paraphrases,
    )
