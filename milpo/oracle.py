"""Oracle cascade — Claude Sonnet 4.6 appelé sur les prédictions classifieur
à confidence synthétique medium/low.

Heuristique : l'oracle (modèle large) est supposé plus rigoureux que le
classifieur primaire (small model) sur l'application stricte de la
taxonomie. Son verdict remplace celui du classifieur quand il est
appelé.

Point de vigilance : l'oracle opère sur les MÊMES features descripteur
que le classifieur (il ne voit pas les pixels). Son amélioration vient
de son capacité d'interprétation supérieure, pas d'une perception
supplémentaire (cf. docs/evaluation.md, section "Limite fondamentale
de la cascade oracle textuelle").
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from anthropic import AsyncAnthropic

from milpo.config import ANTHROPIC_API_KEY, MODEL_ORACLE

log = logging.getLogger("milpo")


_ORACLE_SYSTEM_PROMPT = """\
Tu es un annotateur expert pour une taxonomie de classification de posts Instagram du média Views.

Tu reçois :
- Un post (caption + date + features descripteur visuelles extraites par un modèle multimodal)
- La taxonomie complète des formats visuels pour le scope (FEED ou REELS)
- Une prédiction tentative d'un classifieur primaire plus faible, avec sa confidence synthétique < high — indiquant que ses samples self-consistency ont divergé

Ta mission : décider, en toute indépendance, quel label visual_format est correct pour ce post. Applique rigoureusement la taxonomie fournie (ne jamais inventer de label hors de l'enum). Utilise la prédiction du classifieur comme indice mais sois prêt à la contredire si la règle taxonomique le justifie.

Tu DOIS raisonner STEP BY STEP dans l'ordre suivant, sans sauter d'étape :

1. SIGNAUX OBSERVÉS : cite précisément les signaux structurels présents dans la section "SIGNAUX STRUCTURELS OBSERVÉS" du descripteur (texte overlay slide 1, logo Views, logo propriétaire, flèche de swipe, numérotation, gabarit spécifique, chiffre dominant, photos plein cadre brutes, voix off narrative, interview assise/debout, etc.).

2. TEST DU VIEWER INSTAGRAM : imagine qu'un viewer Instagram scrolle dans son feed, SANS LIRE la caption, et voit uniquement les images. S'arrêterait-il parce que la photo est belle, esthétique, surprenante, iconique ou visuellement frappante ? LA BEAUTÉ PRIME-T-ELLE SUR LE RESTE ? Si oui → signal fort pour post_mood / reel_mood / post_shooting.

3. TEST SHOWING vs TELLING : l'information principale est-elle portée par la PHOTO (SHOWING = post_mood, post_shooting, reel_mood) ou par la CAPTION qui apporte une info non visible (TELLING = post_news, post_anniversaire, reel_news) ? Demande-toi : "en retirant mentalement la caption, la photo reste-t-elle intéressante comme sujet visuel autonome ?"

4. CANDIDATS PLAUSIBLES : liste 2-3 labels de la taxonomie qui matchent le profil de signaux extrait en étape 1.

5. DÉSAMBIGUATION : applique les règles de désambiguation EXPLICITES entre les candidats en citant textuellement les clauses de la taxonomie qui tranchent (ex : "post_news requiert un verbe d'action ou marqueur temporel, or la caption est contemplative → exclus").

6. DÉCISION FINALE : label retenu + justification courte.

Format de réponse JSON strict :
{
  "reasoning": "<raisonnement structuré en 6 étapes numérotées, concis mais explicite>",
  "label": "<nom exact d'une classe de la taxonomie fournie>",
  "confidence": "high" | "medium" | "low"
}
"""


@dataclass
class OracleVerdict:
    """Verdict oracle structuré pour un axe de classification."""

    label: str
    confidence: str
    reasoning: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    error: str | None = None


_client_singleton: AsyncAnthropic | None = None


def get_async_oracle_client() -> AsyncAnthropic | None:
    """Retourne un client Anthropic async (ou None si pas de clé API)."""
    global _client_singleton
    if not ANTHROPIC_API_KEY:
        return None
    if _client_singleton is None:
        _client_singleton = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)
    return _client_singleton


def _build_oracle_user_message(
    *,
    features_json: str,
    caption: str | None,
    descriptions_taxonomiques: str,
    posted_at: datetime | None,
    classifier_prediction: str,
    classifier_confidence: str,
    classifier_samples: list[dict] | None = None,
) -> str:
    date_line = (
        f"**Date de publication** : {posted_at.date().isoformat()}\n"
        if posted_at is not None
        else ""
    )

    samples_block = ""
    if classifier_samples:
        samples_block = "\n**Diversité des samples self-consistency (vote classifieur)** :\n"
        for i, s in enumerate(classifier_samples, 1):
            samples_block += f"- sample {i}: {s.get('label', '?')}\n"

    return f"""\
# Taxonomie visual_format pour le scope courant

{descriptions_taxonomiques}

# Post à classifier

{date_line}
**Caption** :
{caption or '(pas de caption)'}

**Analyse visuelle (features descripteur, texte uniquement — pas d'accès aux pixels)** :
{features_json[:5000]}

# Prédiction tentative du classifieur primaire

- Label : `{classifier_prediction}`
- Confidence synthétique (vote k=3) : `{classifier_confidence}` → samples ont divergé
{samples_block}

Applique strictement la taxonomie ci-dessus et rends ton verdict."""


async def async_call_oracle_visual_format(
    features_json: str,
    caption: str | None,
    descriptions_taxonomiques: str,
    labels: list[str],
    *,
    posted_at: datetime | None = None,
    classifier_prediction: str,
    classifier_confidence: str,
    classifier_samples: list[dict] | None = None,
) -> OracleVerdict:
    """Appelle Claude Sonnet 4.6 comme oracle pour l'axe visual_format.

    Retourne un OracleVerdict structuré. En cas d'échec API ou parsing,
    retourne un verdict avec `error` non-None et `label` = classifier_prediction
    (fallback sûr).
    """
    import time

    client = get_async_oracle_client()
    if client is None:
        return OracleVerdict(
            label=classifier_prediction,
            confidence=classifier_confidence,
            reasoning="[oracle disabled: no ANTHROPIC_API_KEY]",
            model=MODEL_ORACLE,
            latency_ms=0,
            input_tokens=0,
            output_tokens=0,
            error="disabled",
        )

    user_msg = _build_oracle_user_message(
        features_json=features_json,
        caption=caption,
        descriptions_taxonomiques=descriptions_taxonomiques,
        posted_at=posted_at,
        classifier_prediction=classifier_prediction,
        classifier_confidence=classifier_confidence,
        classifier_samples=classifier_samples,
    )

    # Tool schema : force structured output via tool_use (évite les erreurs
    # de parsing JSON qu'on observait quand le LLM produisait du plain text
    # contenant des guillemets non échappés dans reasoning).
    classify_tool = {
        "name": "classify_visual_format",
        "description": "Rend le verdict final après raisonnement en 6 étapes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": (
                        "Raisonnement structuré en 6 étapes numérotées. "
                        "N'inclus PAS de guillemets imbriqués non échappés."
                    ),
                },
                "label": {
                    "type": "string",
                    "enum": labels,
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
            },
            "required": ["reasoning", "label", "confidence"],
        },
    }

    t0 = time.monotonic()
    try:
        response = await client.messages.create(
            model=MODEL_ORACLE,
            max_tokens=12000,
            system=_ORACLE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=[classify_tool],
            tool_choice={"type": "tool", "name": "classify_visual_format"},
        )
    except Exception as exc:
        log.warning("Oracle call failed: %s", exc)
        return OracleVerdict(
            label=classifier_prediction,
            confidence=classifier_confidence,
            reasoning=f"[oracle error: {exc}]",
            model=MODEL_ORACLE,
            latency_ms=int((time.monotonic() - t0) * 1000),
            input_tokens=0,
            output_tokens=0,
            error=str(exc),
        )

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Extraction du tool_use block depuis la réponse Anthropic
    tool_use_block = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_visual_format":
            tool_use_block = block
            break

    if tool_use_block is None:
        log.warning("Oracle ne retourne pas de tool_use block — fallback classifier")
        return OracleVerdict(
            label=classifier_prediction,
            confidence=classifier_confidence,
            reasoning="[oracle no tool_use in response]",
            model=MODEL_ORACLE,
            latency_ms=latency_ms,
            input_tokens=response.usage.input_tokens if response.usage else 0,
            output_tokens=response.usage.output_tokens if response.usage else 0,
            error="no_tool_use",
        )

    parsed = tool_use_block.input

    oracle_label = parsed.get("label")
    if oracle_label not in labels:
        log.warning(
            "Oracle label hors enum: %r — fallback vers prédiction classifieur",
            oracle_label,
        )
        return OracleVerdict(
            label=classifier_prediction,
            confidence=classifier_confidence,
            reasoning=f"[oracle invalid label: {oracle_label!r}] reasoning={parsed.get('reasoning', '')}",
            model=MODEL_ORACLE,
            latency_ms=latency_ms,
            input_tokens=response.usage.input_tokens if response.usage else 0,
            output_tokens=response.usage.output_tokens if response.usage else 0,
            error=f"invalid_label: {oracle_label}",
        )

    return OracleVerdict(
        label=oracle_label,
        confidence=parsed.get("confidence", "medium"),
        reasoning=parsed.get("reasoning", ""),
        model=MODEL_ORACLE,
        latency_ms=latency_ms,
        input_tokens=response.usage.input_tokens if response.usage else 0,
        output_tokens=response.usage.output_tokens if response.usage else 0,
        error=None,
    )
