"""Agent rewriter HILPO — analyse les erreurs et propose un nouveau prompt."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from openai import OpenAI

from hilpo.client import get_client
from hilpo.config import MODEL_REWRITER

REWRITER_SYSTEM = """\
Tu es un ingénieur prompt expert en classification de contenus Instagram.

Tu reçois :
1. Les **instructions actuelles** d'un agent de classification (la partie optimisable du prompt)
2. Un **batch d'erreurs** : pour chaque erreur, le label prédit, le label attendu (annotation humaine), les features visuelles extraites, la caption, et les descriptions taxonomiques des deux labels
3. Les **descriptions taxonomiques complètes** de tous les labels du scope

## Ta mission

Analyse les patterns d'erreur dans le batch et réécris les instructions pour corriger ces erreurs. Tu dois :

1. **Diagnostiquer** : quelles règles ou heuristiques dans les instructions actuelles causent les erreurs ? Quels patterns visuels/textuels sont mal interprétés ?
2. **Corriger** : modifier les règles de décision, ajouter des cas spécifiques, clarifier les frontières entre labels confondus
3. **Préserver** : ne pas casser ce qui fonctionne. Les instructions doivent rester cohérentes et complètes.

## Contraintes

- Retourne un JSON avec deux champs : `reasoning` (ton analyse) et `new_instructions` (les instructions complètes réécrites)
- Les nouvelles instructions remplacent entièrement les anciennes (pas un diff)
- Garde le même format et style que les instructions originales
- Ne modifie PAS les descriptions taxonomiques (elles sont fixes)
- Sois concis dans les instructions — le prompt sera envoyé à chaque classification
"""


@dataclass
class ErrorCase:
    """Une erreur de classification à analyser."""

    ig_media_id: int
    axis: str
    scope: str | None
    predicted: str
    expected: str
    features_json: str
    caption: str | None
    desc_predicted: str
    desc_expected: str


@dataclass
class RewriteResult:
    """Résultat d'un appel au rewriter."""

    new_instructions: str
    reasoning: str
    target_agent: str
    target_scope: str | None
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def _format_error_batch(errors: list[ErrorCase]) -> str:
    """Formate le batch d'erreurs pour le prompt du rewriter."""
    lines = []
    for i, e in enumerate(errors, 1):
        lines.append(f"### Erreur {i}")
        lines.append(f"- **Prédit** : `{e.predicted}`")
        lines.append(f"- **Attendu** : `{e.expected}`")
        lines.append(f"- **Caption** : {(e.caption or '(vide)')[:300]}")
        lines.append(f"- **Description label prédit** : {e.desc_predicted}")
        lines.append(f"- **Description label attendu** : {e.desc_expected}")
        lines.append(f"- **Features extraites** :\n```json\n{e.features_json[:1500]}\n```")
        lines.append("")
    return "\n".join(lines)


def rewrite_prompt(
    current_instructions: str,
    errors: list[ErrorCase],
    all_descriptions: str,
    model: str = MODEL_REWRITER,
    client: OpenAI | None = None,
) -> RewriteResult:
    """Appelle le rewriter pour proposer un nouveau prompt.

    Args:
        current_instructions: Instructions I_t actuelles du prompt ciblé.
        errors: Batch d'erreurs filtrées pour la cible.
        all_descriptions: Descriptions taxonomiques complètes du scope.
        model: Modèle LLM à utiliser.
        client: Client OpenAI (créé si None).

    Returns:
        RewriteResult avec les nouvelles instructions et le raisonnement.
    """
    if client is None:
        client = get_client()

    user_content = f"""## Instructions actuelles

```
{current_instructions}
```

## Batch d'erreurs ({len(errors)} erreurs)

{_format_error_batch(errors)}

## Descriptions taxonomiques (référence)

{all_descriptions}

---

Analyse les erreurs et propose des instructions améliorées. Retourne un JSON avec `reasoning` et `new_instructions`."""

    t0 = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REWRITER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)

    return RewriteResult(
        new_instructions=parsed.get("new_instructions", current_instructions),
        reasoning=parsed.get("reasoning", ""),
        target_agent=errors[0].axis if errors else "unknown",
        target_scope=errors[0].scope if errors else None,
        model=model,
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        latency_ms=latency_ms,
    )
