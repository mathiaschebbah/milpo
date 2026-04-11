"""Simule une cascade confidence-routed sur les prédictions d'un run.

Pour chaque prédiction visual_format avec confidence synthétique
in {'medium', 'low'}, route vers Claude Sonnet 4.6 comme oracle.
Compare ensuite : prédiction originale vs oracle verdict vs annotation
humaine, et calcule l'accuracy simulée après cascade.

Usage :
    uv run python scripts/simulate_cascade.py --run-id 74
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from milpo.db import get_conn
from milpo.db.taxonomy import load_visual_formats
from milpo.prompting.catalog import format_descriptions

load_dotenv()
sys.stdout.reconfigure(line_buffering=True)

ORACLE_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
Tu es un annotateur expert pour une taxonomie de classification de posts Instagram du média Views.
Tu reçois un post (caption + date + features descripteur visuelles) et la taxonomie complète des formats visuels.
Un classifieur automatique a proposé un label avec une confidence synthétique basse (< high) — indiquant que le
classifieur n'est pas sûr de son verdict. Ta mission : décider, en toute indépendance, quel label visual_format est
correct pour ce post.

Prends en compte :
- Les signaux visuels réels décrits dans les features
- Le contenu et le ton de la caption
- La date du post
- La taxonomie exacte fournie (ne jamais inventer de label)

Format de réponse JSON strict :
{
  "predicted_label": "<nom exact d'une classe de la taxonomie>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<2-3 phrases expliquant ton choix>"
}
"""


def build_user_message(
    caption: str | None,
    date_iso: str,
    features: str,
    classifier_prediction: str,
    classifier_confidence: str,
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
{features[:4000]}

# Contexte — prédiction classifieur Flash Lite (sujette à erreur)

- Prédiction : `{classifier_prediction}`
- Confidence synthétique (vote k=3) : `{classifier_confidence}` → le classifieur est incertain

Donne ton verdict indépendant au format JSON."""


def load_routed_cases(conn, run_id: int) -> list[dict]:
    """Charge toutes les prédictions medium/low avec annotation humaine."""
    rows = conn.execute(
        """
        SELECT p.ig_media_id, p.predicted_value,
               p.raw_response->>'confidence' AS confidence,
               p.raw_response->>'text' AS features,
               vf_true.name AS truth,
               po.shortcode, po.caption, po.timestamp,
               po.media_product_type::text AS scope
        FROM predictions p
        JOIN annotations a ON a.ig_media_id = p.ig_media_id
        JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
        JOIN posts po ON po.ig_media_id = p.ig_media_id
        WHERE p.simulation_run_id = %s
          AND p.agent = 'visual_format'
          AND p.raw_response->>'confidence' IN ('medium', 'low')
        ORDER BY po.timestamp
        """,
        (run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def call_oracle(client: Anthropic, system: str, user: str) -> dict:
    resp = client.messages.create(
        model=ORACLE_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {"predicted_label": None, "confidence": "low", "reasoning": f"[parse error: {exc}]"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/cascade_simulation"))
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY missing")

    client = Anthropic(api_key=api_key)
    conn = get_conn()

    cases = load_routed_cases(conn, args.run_id)
    print(f"Loaded {len(cases)} medium/low confidence cases from run {args.run_id}\n")

    taxo_cache: dict[str, str] = {}
    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / f"cascade_run{args.run_id}.jsonl"
    out_file = out_path.open("w", encoding="utf-8")

    # Metrics
    n_classifier_correct = 0   # cas où le classifieur avait raison au départ
    n_classifier_wrong = 0     # cas où le classifieur se trompait
    n_oracle_agrees_truth = 0  # oracle aligné avec la vérité
    n_oracle_agrees_classifier = 0  # oracle valide la prédiction (qui peut être juste ou fausse)
    n_oracle_proposes_other = 0

    cascade_corrected = 0   # cas où cascade transforme une erreur en correct
    cascade_broke = 0       # cas où cascade transforme un correct en erreur
    cascade_kept_right = 0  # cas où cascade préserve un correct
    cascade_kept_wrong = 0  # cas où cascade préserve une erreur

    for i, c in enumerate(cases, 1):
        scope = c["scope"]
        if scope not in taxo_cache:
            taxo_cache[scope] = format_descriptions(load_visual_formats(conn, scope))

        classifier_was_correct = c["predicted_value"] == c["truth"]
        if classifier_was_correct:
            n_classifier_correct += 1
        else:
            n_classifier_wrong += 1

        user_msg = build_user_message(
            caption=c["caption"],
            date_iso=c["timestamp"].date().isoformat(),
            features=c.get("features") or "(features indisponibles)",
            classifier_prediction=c["predicted_value"],
            classifier_confidence=c["confidence"],
            taxonomy_text=taxo_cache[scope],
        )

        t0 = time.monotonic()
        verdict = call_oracle(client, SYSTEM_PROMPT, user_msg)
        latency = time.monotonic() - t0

        oracle_label = verdict.get("predicted_label")
        oracle_correct = oracle_label == c["truth"]

        if oracle_label == c["truth"]:
            n_oracle_agrees_truth += 1
        if oracle_label == c["predicted_value"]:
            n_oracle_agrees_classifier += 1
        if oracle_label is not None and oracle_label != c["truth"] and oracle_label != c["predicted_value"]:
            n_oracle_proposes_other += 1

        # Cascade effect : oracle verdict replaces classifier
        if classifier_was_correct and oracle_correct:
            cascade_kept_right += 1
            effect = "kept_right"
        elif classifier_was_correct and not oracle_correct:
            cascade_broke += 1
            effect = "broke"
        elif not classifier_was_correct and oracle_correct:
            cascade_corrected += 1
            effect = "corrected"
        else:
            cascade_kept_wrong += 1
            effect = "kept_wrong"

        record = {
            "ig_media_id": c["ig_media_id"],
            "shortcode": c["shortcode"],
            "url": f"https://www.instagram.com/p/{c['shortcode']}/",
            "date": c["timestamp"].date().isoformat(),
            "scope": scope,
            "truth": c["truth"],
            "classifier_prediction": c["predicted_value"],
            "classifier_confidence": c["confidence"],
            "classifier_correct": classifier_was_correct,
            "oracle_label": oracle_label,
            "oracle_confidence": verdict.get("confidence"),
            "oracle_reasoning": verdict.get("reasoning"),
            "oracle_correct": oracle_correct,
            "cascade_effect": effect,
            "latency_s": round(latency, 2),
        }
        out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_file.flush()

        print(
            f"  [{i}/{len(cases)}] {c['shortcode']:14s} "
            f"truth={c['truth']} pred={c['predicted_value']} oracle={oracle_label} → {effect}"
        )

    out_file.close()

    total = len(cases)
    print("\n" + "=" * 68)
    print(f"CASCADE SIMULATION — run {args.run_id} / {total} medium+low cases routés")
    print("=" * 68)
    print(f"\n-- État initial avant cascade --")
    print(f"  Classifier correct        : {n_classifier_correct:3d}  ({100*n_classifier_correct/total:.1f}%)")
    print(f"  Classifier wrong          : {n_classifier_wrong:3d}  ({100*n_classifier_wrong/total:.1f}%)")
    print(f"\n-- Oracle verdicts --")
    print(f"  agrees_truth              : {n_oracle_agrees_truth:3d}  ({100*n_oracle_agrees_truth/total:.1f}%)")
    print(f"  agrees_classifier         : {n_oracle_agrees_classifier:3d}  ({100*n_oracle_agrees_classifier/total:.1f}%)")
    print(f"  proposes_other            : {n_oracle_proposes_other:3d}  ({100*n_oracle_proposes_other/total:.1f}%)")
    print(f"\n-- Effet de la cascade sur les cas routés --")
    print(f"  corrected (wrong → right) : {cascade_corrected:3d}  <- GAIN")
    print(f"  kept_right (right → right): {cascade_kept_right:3d}")
    print(f"  kept_wrong (wrong → wrong): {cascade_kept_wrong:3d}")
    print(f"  broke (right → wrong)     : {cascade_broke:3d}  <- LOSS")
    print(f"  NET gain                  : {cascade_corrected - cascade_broke:+d} prédictions")
    print("=" * 68)

    # Compute new accuracy on the full vf axis
    total_run = conn.execute(
        "SELECT COUNT(*) AS n FROM predictions WHERE simulation_run_id = %s AND agent = 'visual_format'",
        (args.run_id,),
    ).fetchone()["n"]
    original_correct = conn.execute(
        """
        SELECT COUNT(*) AS n FROM predictions p
        JOIN annotations a ON a.ig_media_id = p.ig_media_id
        JOIN visual_formats vf ON vf.id = a.visual_format_id
        WHERE p.simulation_run_id = %s AND p.agent = 'visual_format'
          AND p.predicted_value = vf.name
        """,
        (args.run_id,),
    ).fetchone()["n"]

    new_correct = original_correct + (cascade_corrected - cascade_broke)
    print(f"\n-- Accuracy simulée après cascade --")
    print(f"  Run {args.run_id} sans cascade : {original_correct}/{total_run} = {100*original_correct/total_run:.1f}%")
    print(f"  Run {args.run_id} avec cascade : {new_correct}/{total_run} = {100*new_correct/total_run:.1f}%")
    print(f"  Δ                             : {100*(new_correct-original_correct)/total_run:+.1f}pp")
    print("\nOutput : " + str(out_path))


if __name__ == "__main__":
    main()
