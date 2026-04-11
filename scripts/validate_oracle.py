"""Validation one-shot : Claude Sonnet 4.6 comme oracle sur les erreurs d'un run.

Note : modèle utilisé = claude-sonnet-4-6 (le plus récent Sonnet au 2026-04-11).

Pour chaque erreur >= 2024 d'un run, appelle Claude avec contexte complet
(caption, date, features descripteur, prédiction actuelle, ground truth annotée,
taxonomie visual_format) et lui demande son avis indépendant.

On compte :
    - combien de fois l'oracle est d'accord avec la vérité annotée (→ cascade aurait corrigé)
    - combien de fois d'accord avec la prédiction (→ cascade inutile)
    - combien de fois il propose autre chose (→ ambiguïté irréductible OU annotation à revoir)

Usage :
    uv run python scripts/validate_oracle.py --run-id 71 --era post2024
    uv run python scripts/validate_oracle.py --run-id 70 --era all --limit 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from milpo.db import get_conn
from milpo.db.taxonomy import load_visual_formats
from milpo.prompting.catalog import format_descriptions

load_dotenv()

ORACLE_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
Tu es un annotateur expert pour une taxonomie de classification de posts Instagram du média Views.
Tu reçois un post (caption + date + features descripteur visuelles) et la taxonomie complète des formats visuels.
Un classifieur automatique a proposé un label et une annotation humaine existe.

Ta mission : décider, en toute indépendance, quel label visual_format est correct pour ce post.
Tu dois prendre en compte :
- Les signaux visuels réels décrits dans les features
- Le contenu et le ton de la caption
- La date du post (certaines classes ont des variantes temporelles)
- La taxonomie exacte fournie (ne jamais inventer de label)

Réponds au format JSON strict :
{
  "predicted_label": "<nom exact d'une classe de la taxonomie>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<2-3 phrases expliquant ton choix>"
}

N'utilise que les noms exacts de classes de la taxonomie fournie.
"""


def build_user_message(
    caption: str | None,
    date_iso: str,
    features: str,
    current_prediction: str,
    human_annotation: str,
    taxonomy_text: str,
) -> str:
    return f"""\
# Taxonomie visual_format complète

{taxonomy_text}

# Post à classifier

**Date de publication** : {date_iso}

**Caption** :
{caption or '(pas de caption)'}

**Analyse visuelle (features descripteur)** :
{features}

# Contexte — prédictions existantes (indicatif seulement, NE PAS biaiser ton jugement)

- Prédiction du classifieur automatique : `{current_prediction}`
- Annotation humaine : `{human_annotation}`

Donne ton verdict indépendant au format JSON."""


def load_errors(conn, run_id: int, era: str, limit: int | None) -> list[dict]:
    """Charge les erreurs de classification pour un run.

    era: 'all' | 'post2024' | 'pre2024'
    """
    era_filter = {
        "all": "",
        "post2024": "AND po.timestamp >= '2024-01-01'",
        "pre2024": "AND po.timestamp < '2024-01-01'",
    }[era]

    limit_clause = f"LIMIT {limit}" if limit else ""

    rows = conn.execute(
        f"""
        WITH errors AS (
            SELECT p.ig_media_id, p.predicted_value,
                   vf_true.name AS truth,
                   po.shortcode, po.caption, po.timestamp,
                   po.media_product_type::text AS scope
            FROM predictions p
            JOIN annotations a ON a.ig_media_id = p.ig_media_id
            JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
            JOIN posts po ON po.ig_media_id = p.ig_media_id
            WHERE p.simulation_run_id = %s
              AND p.agent = 'visual_format'
              AND p.predicted_value <> vf_true.name
              {era_filter}
        ),
        descriptor AS (
            SELECT pd.ig_media_id, pd.raw_response->>'text' AS features
            FROM predictions pd
            WHERE pd.simulation_run_id = %s AND pd.agent = 'descriptor'
        )
        SELECT e.*, COALESCE(d.features, '(features indisponibles)') AS features
        FROM errors e
        LEFT JOIN descriptor d ON d.ig_media_id = e.ig_media_id
        ORDER BY e.timestamp
        {limit_clause}
        """,
        (run_id, run_id),
    ).fetchall()
    return [dict(r) for r in rows]


def build_taxonomy_text(conn, scope: str) -> str:
    """Construit le bloc taxonomique visual_format pour un scope."""
    return format_descriptions(load_visual_formats(conn, scope))


def call_oracle(client: Anthropic, system: str, user: str) -> dict[str, Any]:
    """Appelle Claude Sonnet 4.5 et parse le JSON retourné."""
    response = client.messages.create(
        model=ORACLE_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {
            "predicted_label": None,
            "confidence": "low",
            "reasoning": f"[JSON parse error: {exc}] raw={text[:500]}",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--era", choices=["all", "post2024", "pre2024"], default="post2024")
    parser.add_argument("--limit", type=int, default=None, help="max errors to process")
    parser.add_argument("--output", type=Path, default=Path("data/oracle_validation"))
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY missing in .env")

    client = Anthropic(api_key=api_key)
    conn = get_conn()

    errors = load_errors(conn, args.run_id, args.era, args.limit)
    print(f"Loaded {len(errors)} errors for run {args.run_id} era={args.era}")

    taxo_cache: dict[str, str] = {}

    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / f"oracle_run{args.run_id}_{args.era}.jsonl"
    out_file = out_path.open("w", encoding="utf-8")

    counts = {"agrees_truth": 0, "agrees_prediction": 0, "proposes_other": 0, "parse_error": 0}

    for i, err in enumerate(errors, 1):
        scope = err["scope"]
        if scope not in taxo_cache:
            taxo_cache[scope] = build_taxonomy_text(conn, scope)
        taxonomy_text = taxo_cache[scope]

        user_msg = build_user_message(
            caption=err["caption"],
            date_iso=err["timestamp"].date().isoformat(),
            features=err["features"][:4000],
            current_prediction=err["predicted_value"],
            human_annotation=err["truth"],
            taxonomy_text=taxonomy_text,
        )

        t0 = time.monotonic()
        try:
            verdict = call_oracle(client, SYSTEM_PROMPT, user_msg)
        except Exception as exc:
            print(f"  [{i}/{len(errors)}] ERROR on {err['shortcode']}: {exc}")
            continue

        latency = time.monotonic() - t0

        oracle_label = verdict.get("predicted_label")
        if oracle_label is None:
            bucket = "parse_error"
        elif oracle_label == err["truth"]:
            bucket = "agrees_truth"
        elif oracle_label == err["predicted_value"]:
            bucket = "agrees_prediction"
        else:
            bucket = "proposes_other"

        counts[bucket] += 1

        record = {
            "ig_media_id": err["ig_media_id"],
            "shortcode": err["shortcode"],
            "url": f"https://www.instagram.com/p/{err['shortcode']}/",
            "date": err["timestamp"].date().isoformat(),
            "scope": scope,
            "human_annotation": err["truth"],
            "classifier_prediction": err["predicted_value"],
            "oracle_label": oracle_label,
            "oracle_confidence": verdict.get("confidence"),
            "oracle_reasoning": verdict.get("reasoning"),
            "bucket": bucket,
            "latency_s": round(latency, 2),
        }
        out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_file.flush()

        print(
            f"  [{i}/{len(errors)}] {err['shortcode']} "
            f"truth={err['truth']} pred={err['predicted_value']} "
            f"oracle={oracle_label} → {bucket}"
        )

    out_file.close()

    total = sum(counts.values())
    print("\n" + "=" * 60)
    print(f"RÉSULTATS — run {args.run_id} / era {args.era} / {total} erreurs traitées")
    print("=" * 60)
    for bucket, n in counts.items():
        pct = round(100 * n / total, 1) if total else 0
        print(f"  {bucket:22s} {n:4d}  ({pct}%)")
    print("=" * 60)

    if total > 0:
        oracle_ceiling_pct = 100 * counts["agrees_truth"] / total
        print(
            f"\nPlafond d'accuracy additionnelle avec cascade parfaite : "
            f"+{counts['agrees_truth']} posts corrects → {oracle_ceiling_pct:.1f}% des erreurs corrigées"
        )
        print(f"\nOutput détaillé : {out_path}")


if __name__ == "__main__":
    main()
