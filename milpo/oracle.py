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

Format de réponse JSON strict :
{
  "reasoning": "<3-5 phrases : cite les signaux observés dans les features descripteur et applique la règle taxonomique qui tranche>",
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

    t0 = time.monotonic()
    try:
        response = await client.messages.create(
            model=MODEL_ORACLE,
            max_tokens=1024,
            system=_ORACLE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
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
    text = response.content[0].text.strip() if response.content else ""
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("Oracle JSON parse failed: %s — raw=%r", exc, text[:300])
        return OracleVerdict(
            label=classifier_prediction,
            confidence=classifier_confidence,
            reasoning=f"[oracle parse error: {exc}] raw={text[:200]}",
            model=MODEL_ORACLE,
            latency_ms=latency_ms,
            input_tokens=response.usage.input_tokens if response.usage else 0,
            output_tokens=response.usage.output_tokens if response.usage else 0,
            error=f"parse: {exc}",
        )

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
