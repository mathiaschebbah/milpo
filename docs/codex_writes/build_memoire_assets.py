#!/usr/bin/env python3
"""Génère les assets du mémoire Codex à partir de la BDD MILPO.

Sorties :
- figures `.png/.pdf` dans `docs/codex_writes/assets/`
- tableaux `.tex` dans `docs/codex_writes/generated/`
- annexes de traces `.tex`
- résumé JSON pour vérification rapide
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from textwrap import fill

import matplotlib.pyplot as plt
from matplotlib import patches
from matplotlib.lines import Line2D
from psycopg import connect
from psycopg.rows import dict_row
from scipy.stats import binomtest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "docs" / "codex_writes"
ASSETS_DIR = OUT_DIR / "assets"
GENERATED_DIR = OUT_DIR / "generated"
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)

ASSETS_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


plt.rcParams.update(
    {
        "font.family": "DejaVu Serif",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "#FCFCFD",
        "savefig.dpi": 300,
        "axes.linewidth": 0.8,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
    }
)


BLUE = "#2563EB"
BLUE_DARK = "#1D4ED8"
GREEN = "#059669"
GREEN_DARK = "#047857"
AMBER = "#D97706"
RED = "#DC2626"
RED_DARK = "#991B1B"
SLATE = "#475569"
SLATE_LIGHT = "#CBD5E1"
INK = "#0F172A"
PURPLE = "#7C3AED"
TEAL = "#0F766E"


FINAL_RUN_LABELS = {
    158: "Alma Flash Lite",
    159: "Alma Flash",
    160: "Alma Full Flash",
    161: "Alma Qwen",
    164: "Simple Flash Lite + ASSIST",
    165: "Simple Flash Lite sans ASSIST",
    167: "Simple Flash sans ASSIST",
    171: "Simple Flash + ASSIST",
    172: "Alma Flash Lite",
    176: "Simple Flash Lite + ASSIST",
    177: "Simple Flash Lite sans ASSIST",
    178: "Alma Qwen",
    181: "Simple Flash + ASSIST",
    182: "Alma Flash",
    183: "Alma Full Flash",
    185: "Simple Flash sans ASSIST",
    187: "Simple Flash grille seule",
    188: "Simple Flash procédure seule",
}


AUDIT_COUNTS = {
    "alpha": {"A": 1, "B": 12, "C": 6, "D": 4, "n": 23},
    "test": {"A": 3, "B": 12, "C": 6, "D": 3, "n": 24},
}

PURE_C4_SYNERGY = {"Synergie forte": 4, "Synergie moyenne": 2, "Synergie faible": 2}


TRACE_CASES = [
    {
        "kind": "A",
        "title": "Catégorie A — trigger caption explicite mobilisé par ASSIST",
        "post_id": 18009582545163555,
        "dataset": "test",
        "gt_label": "post_news",
        "left_label": "no-ASSIST (run 185)",
        "right_label": "ASSIST (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "La slide 1 présente un overlay textuel blanc",
        "right_focus": "est élu",
        "left_highlights": [
            "Cette structure asymétrique (Slide 1 avec titre + Slides 2+ plein cadre) correspond parfaitement au format post_serie_mood_texte",
        ],
        "right_highlights": [
            "« est élu », « a battu », « remportait »",
            "OVERLAY_SLIDE_1 = texte actualité",
            "post_news",
        ],
        "quant_note": "1 des 3 cas A du test (12,5%). Ici ASSIST explicite des verbes d’officialisation absents du raisonnement no-ASSIST.",
    },
    {
        "kind": "B",
        "title": "Catégorie B — mêmes signaux, arbitrage différent",
        "post_id": 17947266366106809,
        "dataset": "test",
        "gt_label": "reel_interview",
        "left_label": "no-ASSIST (run 185)",
        "right_label": "ASSIST (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "La vidéo montre Just Riadh sur un tapis rouge",
        "right_focus": "On observe une interview de Just Riadh",
        "left_highlights": [
            "Hésitation entre `reel_interview` et `reel_wrap_up`",
            "`reel_wrap_up` est privilégié",
        ],
        "right_highlights": [
            "le contenu est centré sur la parole de l'invité",
            "`reel_interview`",
        ],
        "quant_note": "Les cas B sont majoritaires sur alpha comme sur test. La différence vient d’un tie-break sur le format dominant, pas d’un signal nouveau.",
    },
    {
        "kind": "C",
        "title": "Catégorie C — contradiction raisonnement / label stocké",
        "post_id": 17950101776682281,
        "dataset": "test",
        "gt_label": "post_news",
        "left_label": "no-ASSIST (run 185)",
        "right_label": "ASSIST (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "ce qui exclut `post_quote`",
        "right_focus": "C'est la signature typique du format `post_news`",
        "left_highlights": [
            "ce qui exclut `post_quote`",
            "confirme `post_news`",
        ],
        "right_highlights": [
            "format `post_news`",
        ],
        "quant_note": "6 cas sur 24 au test. Le raisonnement no-ASSIST est correct, mais `predicted_value` diverge du diagnostic verbal.",
    },
    {
        "kind": "D",
        "title": "Catégorie D — bruit perceptuel sur le rôle de l’audio",
        "post_id": 18019535522485240,
        "dataset": "test",
        "gt_label": "reel_news",
        "left_label": "no-ASSIST (run 185)",
        "right_label": "ASSIST (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "voix off narrative continue",
        "right_focus": "Il n'y a pas de voix off narrative continue",
        "left_highlights": [
            "voix off narrative continue",
            "`reel_voix_off`",
        ],
        "right_highlights": [
            "Il n'y a pas de voix off narrative continue",
            "texte overlay descriptif constant",
            "`reel_news`",
        ],
        "quant_note": "3 cas sur 24 au test. Le différentiel porte sur ce que le modèle croit entendre/voir, pas sur la grille elle-même.",
    },
    {
        "kind": "C4",
        "title": "Synergie C4 — gate OVERLAY_SLIDE_1 correctement appliqué",
        "post_id": 17902122857362843,
        "dataset": "test",
        "gt_label": "post_news_legacy",
        "left_label": "C1 taxonomies seules (run 185)",
        "right_label": "C4 grille + procédure (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "La slide 1 présente un titre en overlay blanc",
        "right_focus": "la slide 1 n'a AUCUN overlay",
        "left_highlights": [
            "`post_serie_mood_texte`",
        ],
        "right_highlights": [
            "la slide 1 n'a AUCUN overlay",
            "Famille B et C",
            "`post_news_legacy`",
        ],
        "quant_note": "1 des 8 victoires pures de C4, codée “synergie forte”. C’est le cas le plus propre de gate éliminatoire observé dans le 2x2.",
        "extra_predictions": {
            "C1": "post_serie_mood_texte",
            "C2": "post_serie_mood_texte",
            "C3": "post_news",
            "C4": "post_news_legacy",
        },
    },
    {
        "kind": "C4",
        "title": "Synergie C4 — flèche swipe repérée puis priorisée",
        "post_id": 17959463933531143,
        "dataset": "test",
        "gt_label": "post_en_savoir_plus",
        "left_label": "C1 taxonomies seules (run 185)",
        "right_label": "C4 grille + procédure (run 181)",
        "left_run": 185,
        "right_run": 181,
        "left_focus": "Le visuel montre un processus de fabrication",
        "right_focus": "La slide 1 présente un texte descriptif annonçant un workshop",
        "left_highlights": [
            "`post_serie_mood_texte`",
        ],
        "right_highlights": [
            "une flèche d'incitation au swipe vers la droite",
            "SIGNAL_OBLIGATOIRE pour la classe 'post_en_savoir_plus'",
        ],
        "quant_note": "1 des 8 victoires pures de C4, également codée “synergie forte”. Sans la grille, le cue décisif n’est pas stabilisé.",
        "extra_predictions": {
            "C1": "post_serie_mood_texte",
            "C2": "post_serie_mood_texte",
            "C3": "post_serie_mood_texte",
            "C4": "post_en_savoir_plus",
        },
    },
]


def query_all(sql: str, params: tuple | None = None) -> list[dict]:
    with connect(DATABASE_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def query_one(sql: str, params: tuple | None = None) -> dict:
    rows = query_all(sql, params)
    if len(rows) != 1:
        raise RuntimeError(f"Requête attendue 1 ligne, obtenu {len(rows)}")
    return rows[0]


def latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def tex_pct(value: float) -> str:
    return f"{value:.2f}\\%"


def tex_pp(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f} pp"


def exact_mcnemar_p(gains: int, losses: int) -> float:
    if gains + losses == 0:
        return 1.0
    return float(binomtest(gains, n=gains + losses, p=0.5).pvalue)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def fetch_dataset_stats() -> dict:
    scalar_rows = query_all(
        """
        WITH alpha AS (
          SELECT ig_media_id FROM eval_sets WHERE set_name='alpha'
        ),
        test AS (
          SELECT sp.ig_media_id
          FROM sample_posts sp
          JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        ),
        overlap AS (
          SELECT ig_media_id FROM alpha
          INTERSECT
          SELECT ig_media_id FROM test
        )
        SELECT 'posts_total' AS metric, count(*)::int AS value FROM posts
        UNION ALL SELECT 'annotations_total', count(*)::int FROM annotations
        UNION ALL SELECT 'sample_total', count(*)::int FROM sample_posts
        UNION ALL SELECT 'sample_dev', count(*)::int FROM sample_posts WHERE split='dev'
        UNION ALL SELECT 'sample_test_raw', count(*)::int FROM sample_posts WHERE split='test'
        UNION ALL SELECT 'dev_annotated', count(*)::int
            FROM sample_posts sp JOIN annotations a USING (ig_media_id) WHERE sp.split='dev'
        UNION ALL SELECT 'test_annotated_raw', count(*)::int
            FROM sample_posts sp JOIN annotations a USING (ig_media_id) WHERE sp.split='test'
        UNION ALL SELECT 'test_doubtful', count(*)::int FROM annotations a
            JOIN sample_posts sp USING (ig_media_id) WHERE sp.split='test' AND a.doubtful
        UNION ALL SELECT 'alpha_posts', count(*)::int FROM alpha
        UNION ALL SELECT 'test_posts', count(*)::int FROM test
        UNION ALL SELECT 'overlap', count(*)::int FROM overlap
        UNION ALL SELECT 'alpha_only', count(*)::int FROM alpha EXCEPT SELECT 'alpha_only', count(*)::int FROM overlap
        """
    )
    values = {row["metric"]: row["value"] for row in scalar_rows}
    # alpha_only query above was malformed by UNION logic; recompute explicitly.
    values["alpha_only"] = query_one(
        """
        WITH alpha AS (SELECT ig_media_id FROM eval_sets WHERE set_name='alpha'),
        test AS (
          SELECT sp.ig_media_id
          FROM sample_posts sp JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        )
        SELECT count(*)::int AS value
        FROM (
          SELECT ig_media_id FROM alpha
          EXCEPT
          SELECT ig_media_id FROM test
        ) q
        """
    )["value"]
    values["test_only"] = query_one(
        """
        WITH alpha AS (SELECT ig_media_id FROM eval_sets WHERE set_name='alpha'),
        test AS (
          SELECT sp.ig_media_id
          FROM sample_posts sp JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        )
        SELECT count(*)::int AS value
        FROM (
          SELECT ig_media_id FROM test
          EXCEPT
          SELECT ig_media_id FROM alpha
        ) q
        """
    )["value"]
    distincts = query_all(
        """
        WITH alpha AS (SELECT ig_media_id FROM eval_sets WHERE set_name='alpha'),
        test AS (
          SELECT sp.ig_media_id
          FROM sample_posts sp
          JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        )
        SELECT 'alpha_vf_classes' AS metric, count(DISTINCT vf.name)::int AS value
        FROM alpha a JOIN annotations ann USING (ig_media_id) JOIN visual_formats vf ON vf.id=ann.visual_format_id
        UNION ALL
        SELECT 'test_vf_classes', count(DISTINCT vf.name)::int
        FROM test t JOIN annotations ann USING (ig_media_id) JOIN visual_formats vf ON vf.id=ann.visual_format_id
        UNION ALL
        SELECT 'alpha_categories', count(DISTINCT c.name)::int
        FROM alpha a JOIN annotations ann USING (ig_media_id) JOIN categories c ON c.id=ann.category_id
        UNION ALL
        SELECT 'test_categories', count(DISTINCT c.name)::int
        FROM test t JOIN annotations ann USING (ig_media_id) JOIN categories c ON c.id=ann.category_id
        """
    )
    values.update({row["metric"]: row["value"] for row in distincts})
    return values


def fetch_class_distribution() -> dict[str, list[dict]]:
    rows = query_all(
        """
        WITH alpha AS (
          SELECT 'alpha'::text AS dataset, ig_media_id
          FROM eval_sets WHERE set_name='alpha'
        ),
        test AS (
          SELECT 'test'::text AS dataset, sp.ig_media_id
          FROM sample_posts sp
          JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        ),
        sets AS (
          SELECT * FROM alpha
          UNION ALL
          SELECT * FROM test
        )
        SELECT s.dataset, vf.name AS label, count(*)::int AS n
        FROM sets s
        JOIN annotations ann USING (ig_media_id)
        JOIN visual_formats vf ON vf.id=ann.visual_format_id
        GROUP BY s.dataset, vf.name
        ORDER BY s.dataset, n DESC, label
        """
    )
    grouped: dict[str, list[dict]] = {"alpha": [], "test": []}
    for row in rows:
        grouped[row["dataset"]].append(row)
    return grouped


def fetch_final_runs() -> list[dict]:
    run_ids = sorted(FINAL_RUN_LABELS)
    rows = query_all(
        """
        WITH target_runs AS (
          SELECT unnest(%s::int[]) AS run_id
        )
        SELECT
          r.id,
          r.config->>'dataset' AS dataset,
          r.config->>'pipeline_mode' AS mode,
          r.config->>'model_tier' AS tier,
          COALESCE(r.config->>'include_grille', 'default') AS include_grille,
          COALESCE(r.config->>'include_procedure', 'default') AS include_procedure,
          r.final_accuracy_visual_format * 100.0 AS vf,
          r.final_accuracy_category * 100.0 AS cat,
          r.final_accuracy_strategy * 100.0 AS strat,
          r.total_cost_usd,
          (
            SELECT count(*) FROM predictions p
            WHERE p.simulation_run_id = r.id AND p.agent='visual_format'
          )::int AS n_vf,
          (
            SELECT avg(latency_ms) FROM api_calls c
            WHERE c.simulation_run_id = r.id
          ) AS avg_latency_ms,
          (
            SELECT avg(input_tokens) FROM api_calls c
            WHERE c.simulation_run_id = r.id
          ) AS avg_input_tokens,
          (
            SELECT avg(output_tokens) FROM api_calls c
            WHERE c.simulation_run_id = r.id
          ) AS avg_output_tokens,
          (
            SELECT avg(reasoning_tokens) FROM api_calls c
            WHERE c.simulation_run_id = r.id
          ) AS avg_reasoning_tokens,
          r.total_api_calls
        FROM simulation_runs r
        JOIN target_runs t ON t.run_id = r.id
        ORDER BY r.id
        """,
        (run_ids,),
    )
    for row in rows:
        row["label"] = FINAL_RUN_LABELS[row["id"]]
        row["cost_per_post"] = float(row["total_cost_usd"]) / int(row["n_vf"])
        row["avg_latency_s"] = (float(row["avg_latency_ms"]) or 0.0) / 1000.0
    return rows


def fetch_disjoint_assist_results() -> list[dict]:
    rows = query_all(
        """
        WITH alpha AS (
          SELECT ig_media_id FROM eval_sets WHERE set_name='alpha'
        ),
        test AS (
          SELECT sp.ig_media_id
          FROM sample_posts sp
          JOIN annotations a USING (ig_media_id)
          WHERE sp.split='test' AND NOT a.doubtful
        ),
        overlap AS (
          SELECT ig_media_id FROM alpha
          INTERSECT
          SELECT ig_media_id FROM test
        ),
        alpha_only AS (
          SELECT ig_media_id FROM alpha
          EXCEPT
          SELECT ig_media_id FROM test
        ),
        test_only AS (
          SELECT ig_media_id FROM test
          EXCEPT
          SELECT ig_media_id FROM alpha
        ),
        pools AS (
          SELECT 'flash_alpha_only' AS subset, 171 AS assist_run, 167 AS noassist_run, ARRAY(SELECT ig_media_id FROM alpha_only) AS ids
          UNION ALL SELECT 'flash_test_only', 181, 185, ARRAY(SELECT ig_media_id FROM test_only)
          UNION ALL SELECT 'flashlite_alpha_only', 164, 165, ARRAY(SELECT ig_media_id FROM alpha_only)
          UNION ALL SELECT 'flashlite_test_only', 176, 177, ARRAY(SELECT ig_media_id FROM test_only)
          UNION ALL SELECT 'flash_overlap', 171, 167, ARRAY(SELECT ig_media_id FROM overlap)
          UNION ALL SELECT 'flashlite_overlap', 164, 165, ARRAY(SELECT ig_media_id FROM overlap)
        ),
        preds AS (
          SELECT
            p.subset,
            a.agent,
            a.ig_media_id,
            a.match AS assist_match,
            n.match AS noassist_match
          FROM pools p
          JOIN predictions a
            ON a.simulation_run_id = p.assist_run
           AND a.ig_media_id = ANY(p.ids)
          JOIN predictions n
            ON n.simulation_run_id = p.noassist_run
           AND n.ig_media_id = a.ig_media_id
           AND n.agent = a.agent
          WHERE a.agent IN ('visual_format', 'category', 'strategy')
        )
        SELECT
          subset,
          agent,
          count(*)::int AS n,
          100.0 * avg(assist_match::int) AS assist_pct,
          100.0 * avg(noassist_match::int) AS noassist_pct,
          sum((assist_match AND NOT noassist_match)::int)::int AS gains,
          sum((noassist_match AND NOT assist_match)::int)::int AS losses
        FROM preds
        GROUP BY subset, agent
        ORDER BY subset, agent
        """
    )
    for row in rows:
        row["delta_pp"] = float(row["assist_pct"]) - float(row["noassist_pct"])
        row["p_exact"] = exact_mcnemar_p(int(row["gains"]), int(row["losses"]))
    return rows


def fetch_factorial_2x2() -> dict:
    score_rows = query_all(
        """
        WITH common_posts AS (
          SELECT ig_media_id
          FROM predictions
          WHERE simulation_run_id IN (181,185,187,188) AND agent='visual_format'
          GROUP BY ig_media_id
          HAVING count(*) = 4
        )
        SELECT
          p.simulation_run_id AS run_id,
          count(*)::int AS n,
          sum(p.match::int)::int AS correct,
          100.0 * avg(p.match::int) AS pct
        FROM predictions p
        JOIN common_posts cp USING (ig_media_id)
        WHERE p.agent='visual_format' AND p.simulation_run_id IN (181,185,187,188)
        GROUP BY p.simulation_run_id
        ORDER BY p.simulation_run_id
        """
    )
    pair_rows = query_all(
        """
        WITH common_posts AS (
          SELECT ig_media_id
          FROM predictions
          WHERE simulation_run_id IN (181,185,187,188) AND agent='visual_format'
          GROUP BY ig_media_id
          HAVING count(*) = 4
        )
        SELECT
          a.simulation_run_id AS run_a,
          b.simulation_run_id AS run_b,
          sum((a.match AND NOT b.match)::int)::int AS a_only,
          sum((b.match AND NOT a.match)::int)::int AS b_only,
          count(*)::int AS n
        FROM predictions a
        JOIN predictions b USING (ig_media_id, agent)
        JOIN common_posts cp USING (ig_media_id)
        WHERE a.agent='visual_format'
          AND a.simulation_run_id IN (181,185,187,188)
          AND b.simulation_run_id IN (181,185,187,188)
          AND a.simulation_run_id < b.simulation_run_id
        GROUP BY a.simulation_run_id, b.simulation_run_id
        ORDER BY a.simulation_run_id, b.simulation_run_id
        """
    )
    only_rows = query_one(
        """
        WITH common_posts AS (
          SELECT ig_media_id
          FROM predictions
          WHERE simulation_run_id IN (181,185,187,188) AND agent='visual_format'
          GROUP BY ig_media_id
          HAVING count(*) = 4
        ),
        pt AS (
          SELECT
            ig_media_id,
            max((simulation_run_id=181 AND match)::int) AS c4,
            max((simulation_run_id=185 AND match)::int) AS c1,
            max((simulation_run_id=187 AND match)::int) AS c3,
            max((simulation_run_id=188 AND match)::int) AS c2
          FROM predictions
          JOIN common_posts USING (ig_media_id)
          WHERE agent='visual_format' AND simulation_run_id IN (181,185,187,188)
          GROUP BY ig_media_id
        )
        SELECT
          sum((c4=1 AND c1=0 AND c2=0 AND c3=0)::int)::int AS only_c4,
          sum((c2=1 AND c1=0 AND c3=0 AND c4=0)::int)::int AS only_c2,
          sum((c3=1 AND c1=0 AND c2=0 AND c4=0)::int)::int AS only_c3,
          sum((c1=1 AND c2=0 AND c3=0 AND c4=0)::int)::int AS only_c1
        FROM pt
        """
    )
    score_map = {row["run_id"]: row for row in score_rows}
    c1 = float(score_map[185]["pct"])
    c2 = float(score_map[188]["pct"])
    c3 = float(score_map[187]["pct"])
    c4 = float(score_map[181]["pct"])
    return {
        "scores": score_rows,
        "pairs": [
            {
                **row,
                "p_exact": exact_mcnemar_p(int(row["a_only"]), int(row["b_only"])),
            }
            for row in pair_rows
        ],
        "only": only_rows,
        "effects": {
            "procedure_main": ((c2 - c1) + (c4 - c3)) / 2.0,
            "grille_main": ((c3 - c1) + (c4 - c2)) / 2.0,
            "interaction": (c4 - c3) - (c2 - c1),
        },
    }


def fetch_trace_payload() -> list[dict]:
    payload: list[dict] = []
    for case in TRACE_CASES:
        if case["kind"] == "C4":
            row = query_one(
                """
                WITH c4 AS (
                  SELECT ig_media_id, predicted_value, raw_response->>'reasoning' AS reasoning
                  FROM predictions WHERE simulation_run_id=%s AND agent='visual_format'
                ),
                c1 AS (
                  SELECT ig_media_id, predicted_value, raw_response->>'reasoning' AS reasoning
                  FROM predictions WHERE simulation_run_id=185 AND agent='visual_format'
                ),
                c2 AS (
                  SELECT ig_media_id, predicted_value
                  FROM predictions WHERE simulation_run_id=188 AND agent='visual_format'
                ),
                c3 AS (
                  SELECT ig_media_id, predicted_value
                  FROM predictions WHERE simulation_run_id=187 AND agent='visual_format'
                )
                SELECT
                  c1.predicted_value AS left_pred,
                  c4.predicted_value AS right_pred,
                  c1.reasoning AS left_reasoning,
                  c4.reasoning AS right_reasoning,
                  c2.predicted_value AS c2_pred,
                  c3.predicted_value AS c3_pred
                FROM c4
                JOIN c1 USING (ig_media_id)
                JOIN c2 USING (ig_media_id)
                JOIN c3 USING (ig_media_id)
                WHERE c4.ig_media_id=%s
                """,
                (case["right_run"], case["post_id"]),
            )
        else:
            row = query_one(
                """
                WITH left_pred AS (
                  SELECT ig_media_id, predicted_value, raw_response->>'reasoning' AS reasoning
                  FROM predictions WHERE simulation_run_id=%s AND agent='visual_format'
                ),
                right_pred AS (
                  SELECT ig_media_id, predicted_value, raw_response->>'reasoning' AS reasoning
                  FROM predictions WHERE simulation_run_id=%s AND agent='visual_format'
                )
                SELECT
                  left_pred.predicted_value AS left_pred,
                  right_pred.predicted_value AS right_pred,
                  left_pred.reasoning AS left_reasoning,
                  right_pred.reasoning AS right_reasoning
                FROM left_pred
                JOIN right_pred USING (ig_media_id)
                WHERE left_pred.ig_media_id=%s
                """,
                (case["left_run"], case["right_run"], case["post_id"]),
            )
        payload.append({**case, **row})
    return payload


def summarize_disjoint(results: list[dict]) -> dict:
    pooled = {}
    for tier, subsets in (
        ("flash", ["flash_alpha_only", "flash_test_only"]),
        ("flashlite", ["flashlite_alpha_only", "flashlite_test_only"]),
    ):
        vf_rows = [row for row in results if row["subset"] in subsets and row["agent"] == "visual_format"]
        pooled[tier] = {
            "n": sum(int(r["n"]) for r in vf_rows),
            "gains": sum(int(r["gains"]) for r in vf_rows),
            "losses": sum(int(r["losses"]) for r in vf_rows),
            "assist_correct": sum(round(float(r["assist_pct"]) * int(r["n"]) / 100.0) for r in vf_rows),
            "noassist_correct": sum(round(float(r["noassist_pct"]) * int(r["n"]) / 100.0) for r in vf_rows),
        }
        pooled[tier]["assist_pct"] = 100.0 * pooled[tier]["assist_correct"] / pooled[tier]["n"]
        pooled[tier]["noassist_pct"] = 100.0 * pooled[tier]["noassist_correct"] / pooled[tier]["n"]
        pooled[tier]["delta_pp"] = pooled[tier]["assist_pct"] - pooled[tier]["noassist_pct"]
        pooled[tier]["p_exact"] = exact_mcnemar_p(pooled[tier]["gains"], pooled[tier]["losses"])
    return pooled


def pooled_axis_summary(results: list[dict]) -> list[dict]:
    summary = []
    for tier, subsets in (
        ("Flash", ["flash_alpha_only", "flash_test_only"]),
        ("Flash Lite", ["flashlite_alpha_only", "flashlite_test_only"]),
    ):
        for agent in ("visual_format", "category", "strategy"):
            rows = [row for row in results if row["subset"] in subsets and row["agent"] == agent]
            n = sum(int(r["n"]) for r in rows)
            assist_correct = sum(round(float(r["assist_pct"]) * int(r["n"]) / 100.0) for r in rows)
            noassist_correct = sum(round(float(r["noassist_pct"]) * int(r["n"]) / 100.0) for r in rows)
            gains = sum(int(r["gains"]) for r in rows)
            losses = sum(int(r["losses"]) for r in rows)
            assist_pct = 100.0 * assist_correct / n
            noassist_pct = 100.0 * noassist_correct / n
            summary.append(
                {
                    "tier": tier,
                    "agent": agent,
                    "n": n,
                    "assist_pct": assist_pct,
                    "noassist_pct": noassist_pct,
                    "delta_pp": assist_pct - noassist_pct,
                    "gains": gains,
                    "losses": losses,
                    "p_exact": exact_mcnemar_p(gains, losses),
                }
            )
    return summary


def make_system_overview() -> None:
    fig, ax = plt.subplots(figsize=(12.6, 4.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4)
    ax.axis("off")

    def box(x: float, y: float, w: float, h: float, text: str, fc: str, ec: str = SLATE) -> None:
        rect = patches.FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=1.2,
            edgecolor=ec,
            facecolor=fc,
        )
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=10, color=INK)

    def arrow(x0: float, y0: float, x1: float, y1: float, color: str = SLATE) -> None:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", lw=1.4, color=color),
        )

    box(0.3, 2.65, 2.3, 0.8, "posts / post_media\ncaption + médias", "#E0F2FE", BLUE_DARK)
    box(0.3, 0.55, 2.3, 0.8, "annotations humaines\nsample_posts / eval_sets", "#ECFCCB", GREEN_DARK)
    box(3.1, 1.6, 2.3, 1.0, "CLI `classification`\nchargement + URLs signées", "#F8FAFC")
    box(6.0, 2.45, 2.4, 0.9, "Mode Alma\n1 descripteur multimodal\n+ 3 classifieurs text-only", "#DBEAFE", BLUE_DARK)
    box(6.0, 0.75, 2.4, 0.9, "Mode Simple\n1 appel multimodal\n3 axes en un coup", "#DCFCE7", GREEN_DARK)
    box(9.2, 1.6, 2.2, 1.0, "simulation_runs\npredictions\napi_calls", "#FEF3C7", AMBER)

    arrow(2.65, 3.05, 3.05, 2.15)
    arrow(2.65, 0.95, 3.05, 2.0)
    arrow(5.45, 2.1, 5.95, 2.9, BLUE_DARK)
    arrow(5.45, 2.1, 5.95, 1.2, GREEN_DARK)
    arrow(8.45, 2.9, 9.15, 2.1, BLUE_DARK)
    arrow(8.45, 1.2, 9.15, 2.0, GREEN_DARK)

    ax.text(
        6.0,
        3.55,
        "Deux pipelines évalués sur les mêmes annotations et persistés au même format",
        fontsize=10.2,
        color=SLATE,
        ha="left",
    )
    ax.text(
        9.2,
        0.45,
        "La base conserve les labels, les reasonings, les coûts,\nles latences et les tokens par appel.",
        fontsize=9.2,
        color=SLATE,
        ha="left",
    )
    fig.tight_layout()
    fig.savefig(ASSETS_DIR / "system_overview.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "system_overview.pdf", bbox_inches="tight")
    plt.close(fig)


def make_dataset_overlap(stats: dict) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 3.8))
    ax.set_xlim(0, max(stats["alpha_posts"], stats["test_posts"]) + 40)
    ax.set_ylim(-0.6, 1.6)
    ax.set_yticks([1, 0])
    ax.set_yticklabels(["Alpha", "Test"])
    ax.set_xlabel("Nombre de posts")
    ax.grid(axis="x", color="#E5E7EB", linewidth=0.7)
    ax.set_axisbelow(True)

    ax.barh(1, stats["alpha_only"], color=BLUE, height=0.42, label="alpha uniquement")
    ax.barh(1, stats["overlap"], left=stats["alpha_only"], color=PURPLE, height=0.42, label="recouvrement")
    ax.barh(0, stats["overlap"], color=PURPLE, height=0.42)
    ax.barh(0, stats["test_only"], left=stats["overlap"], color=GREEN, height=0.42, label="test uniquement")

    ax.text(stats["alpha_only"] / 2, 1, str(stats["alpha_only"]), ha="center", va="center", color="white", fontweight="bold")
    ax.text(stats["alpha_only"] + stats["overlap"] / 2, 1, str(stats["overlap"]), ha="center", va="center", color="white", fontweight="bold")
    ax.text(stats["overlap"] / 2, 0, str(stats["overlap"]), ha="center", va="center", color="white", fontweight="bold")
    ax.text(stats["overlap"] + stats["test_only"] / 2, 0, str(stats["test_only"]), ha="center", va="center", color="white", fontweight="bold")

    ax.text(stats["alpha_posts"] + 8, 1, f"total alpha = {stats['alpha_posts']}", va="center", color=SLATE)
    ax.text(stats["test_posts"] + 8, 0, f"total test = {stats['test_posts']}", va="center", color=SLATE)
    ax.legend(loc="upper right", ncol=3, fontsize=9, frameon=True)
    ax.set_title("Recouvrement partiel entre les deux jeux d’évaluation", fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(ASSETS_DIR / "dataset_overlap.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "dataset_overlap.pdf", bbox_inches="tight")
    plt.close(fig)


def make_vf_distribution(distribution: dict[str, list[dict]]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 6.2), sharex=False)
    for ax, dataset, color in zip(axes, ("alpha", "test"), (BLUE, GREEN)):
        rows = distribution[dataset]
        top = rows[:10]
        other = sum(row["n"] for row in rows[10:])
        labels = [row["label"] for row in top] + ["autres"]
        values = [row["n"] for row in top] + [other]
        labels = [fill(label.replace("_", " "), width=18) for label in labels]
        ax.barh(range(len(labels)), values, color=color, alpha=0.9)
        ax.invert_yaxis()
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels)
        ax.set_title(
            f"{dataset.capitalize()} — top 10 formats + queue\n({len(rows)} classes observées)",
            fontsize=11.5,
            fontweight="bold",
        )
        ax.grid(axis="x", color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        for i, value in enumerate(values):
            ax.text(value + 0.5, i, str(value), va="center", fontsize=9, color=SLATE)
    axes[0].set_xlabel("Nombre de posts annotés")
    axes[1].set_xlabel("Nombre de posts annotés")
    fig.suptitle("Longue traîne des classes `visual_format`", fontsize=13.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(ASSETS_DIR / "vf_distribution.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "vf_distribution.pdf", bbox_inches="tight")
    plt.close(fig)


def make_final_runs_cost_perf(runs: list[dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 5.8), sharey=True)
    tier_colors = {
        "flash-lite": BLUE,
        "flash": GREEN,
        "full-flash": RED,
        "qwen": PURPLE,
    }
    mode_markers = {"alma": "o", "simple": "s"}

    for ax, dataset in zip(axes, ("alpha", "test")):
        subset = [row for row in runs if row["dataset"] == dataset and row["id"] in {158,159,160,161,164,165,167,171,172,176,177,178,181,182,183,185}]
        subset = sorted(subset, key=lambda row: row["total_cost_usd"])
        frontier = []
        for candidate in subset:
            dominated = False
            for other in subset:
                if other["id"] == candidate["id"]:
                    continue
                if (
                    other["total_cost_usd"] <= candidate["total_cost_usd"]
                    and other["vf"] >= candidate["vf"]
                    and (
                        other["total_cost_usd"] < candidate["total_cost_usd"]
                        or other["vf"] > candidate["vf"]
                    )
                ):
                    dominated = True
                    break
            if not dominated:
                frontier.append(candidate)
        frontier = sorted(frontier, key=lambda row: row["total_cost_usd"])

        for row in subset:
            color = tier_colors.get(row["tier"], SLATE)
            marker = mode_markers.get(row["mode"], "o")
            ax.scatter(
                row["total_cost_usd"],
                row["vf"],
                s=80,
                color=color,
                marker=marker,
                edgecolor="white",
                linewidth=0.9,
                zorder=3,
            )
            label = row["label"].replace("Simple ", "").replace("Alma ", "")
            ax.text(
                row["total_cost_usd"] + 0.05,
                row["vf"] + 0.08,
                f"{row['id']} — {fill(label, 15)}",
                fontsize=8.4,
                color=SLATE,
            )

        ax.plot(
            [row["total_cost_usd"] for row in frontier],
            [row["vf"] for row in frontier],
            linestyle="--",
            color=RED_DARK,
            linewidth=1.8,
        )
        ax.set_title(dataset.capitalize(), fontsize=12, fontweight="bold")
        ax.grid(color="#E5E7EB", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.set_xlabel("Coût total du run (USD)")
    axes[0].set_ylabel("Accuracy Visual Format (%)")
    legend_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=SLATE, label="Alma", markersize=8),
        Line2D([0], [0], marker="s", color="w", markerfacecolor=SLATE, label="Simple", markersize=8),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BLUE, label="Flash Lite", markersize=8),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GREEN, label="Flash", markersize=8),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=RED, label="Full Flash", markersize=8),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=PURPLE, label="Qwen", markersize=8),
    ]
    fig.legend(handles=legend_handles, loc="upper center", ncol=6, fontsize=9, frameon=True)
    fig.suptitle("Ablation finale : coût vs accuracy VF", fontsize=13.5, fontweight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(ASSETS_DIR / "final_runs_cost_perf.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "final_runs_cost_perf.pdf", bbox_inches="tight")
    plt.close(fig)


def make_assist_disjoint_figure(results: list[dict], pooled: dict, axis_summary: list[dict]) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.8, 5.6))

    subset_order = [
        ("flash_alpha_only", "Flash\nalpha only"),
        ("flash_test_only", "Flash\ntest only"),
        ("flashlite_alpha_only", "Flash Lite\nalpha only"),
        ("flashlite_test_only", "Flash Lite\ntest only"),
    ]
    values = [next(row for row in results if row["subset"] == key and row["agent"] == "visual_format") for key, _ in subset_order]
    x = range(len(values))
    colors = [GREEN, GREEN, BLUE, BLUE]
    ax1.axhline(0, color=SLATE, linewidth=0.8)
    ax1.bar(x, [row["delta_pp"] for row in values], color=colors, width=0.58)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([label for _, label in subset_order])
    ax1.set_ylabel("Delta VF (ASSIST - no-ASSIST, pp)")
    ax1.set_title("Effet ASSIST sur les ensembles disjoints", fontsize=12, fontweight="bold")
    ax1.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    ax1.set_axisbelow(True)
    for i, row in enumerate(values):
        ax1.text(
            i,
            row["delta_pp"] + (0.08 if row["delta_pp"] >= 0 else -0.12),
            f"{row['delta_pp']:+.2f}",
            ha="center",
            va="bottom" if row["delta_pp"] >= 0 else "top",
            fontsize=9,
            color=INK,
            fontweight="bold",
        )
        ax1.text(i, -0.9, f"g/l={row['gains']}/{row['losses']}", ha="center", fontsize=8.3, color=SLATE)
    ax1.text(
        1.5,
        max(row["delta_pp"] for row in values) + 0.65,
        f"Pooled disjoint Flash: {pooled['flash']['delta_pp']:+.2f} pp (p={pooled['flash']['p_exact']:.3f})\n"
        f"Pooled disjoint Flash Lite: {pooled['flashlite']['delta_pp']:+.2f} pp (p={pooled['flashlite']['p_exact']:.3f})",
        ha="center",
        fontsize=8.6,
        color=SLATE,
    )

    axis_order = ["visual_format", "category", "strategy"]
    tiers = ["Flash", "Flash Lite"]
    xpos = [0, 1, 2]
    width = 0.32
    for j, tier in enumerate(tiers):
        rows = [next(row for row in axis_summary if row["tier"] == tier and row["agent"] == agent) for agent in axis_order]
        ax2.bar(
            [x + (j - 0.5) * width for x in xpos],
            [row["delta_pp"] for row in rows],
            width=width,
            label=tier,
            color=GREEN if tier == "Flash" else BLUE,
        )
        for x_val, row in zip([x + (j - 0.5) * width for x in xpos], rows):
            ax2.text(
                x_val,
                row["delta_pp"] + (0.06 if row["delta_pp"] >= 0 else -0.1),
                f"{row['delta_pp']:+.2f}",
                ha="center",
                va="bottom" if row["delta_pp"] >= 0 else "top",
                fontsize=8.5,
            )
    ax2.axhline(0, color=SLATE, linewidth=0.8)
    ax2.set_xticks(xpos)
    ax2.set_xticklabels(["visual_format", "category", "strategy"])
    ax2.set_ylabel("Delta apparié (pp)")
    ax2.set_title("Effet par axe sur le pooled disjoint", fontsize=12, fontweight="bold")
    ax2.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    ax2.set_axisbelow(True)
    ax2.legend(fontsize=9)

    fig.suptitle("Flash garde un bénéfice VF stable ; Flash Lite reste faible et instable", fontsize=13.3, fontweight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(ASSETS_DIR / "assist_disjoint.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "assist_disjoint.pdf", bbox_inches="tight")
    plt.close(fig)


def make_factorial_figure(factorial: dict) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.3))
    score_map = {row["run_id"]: row["pct"] for row in factorial["scores"]}
    x = [0, 1]
    no_grid = [float(score_map[185]), float(score_map[188])]
    yes_grid = [float(score_map[187]), float(score_map[181])]

    ax1.plot(x, no_grid, marker="o", color=AMBER, linewidth=2.2, label="Sans grille")
    ax1.plot(x, yes_grid, marker="o", color=BLUE, linewidth=2.2, label="Avec grille")
    ax1.set_xticks(x)
    ax1.set_xticklabels(["Sans procédure", "Avec procédure"])
    ax1.set_ylabel("Accuracy VF (%) sur 400 posts communs")
    ax1.set_title("Interaction positive grille × procédure", fontsize=12, fontweight="bold")
    ax1.grid(color="#E5E7EB", linewidth=0.7)
    ax1.set_axisbelow(True)
    ax1.legend(fontsize=9)
    for xi, yi in zip(x, no_grid):
        ax1.text(xi, yi + 0.12, f"{yi:.2f}", ha="center", fontsize=9)
    for xi, yi in zip(x, yes_grid):
        ax1.text(xi, yi + 0.12, f"{yi:.2f}", ha="center", fontsize=9)

    effects = factorial["effects"]
    ax1.text(
        0.5,
        min(no_grid + yes_grid) - 1.1,
        f"Effet grille = {effects['grille_main']:+.2f} pp\n"
        f"Effet procédure = {effects['procedure_main']:+.2f} pp\n"
        f"Interaction = {effects['interaction']:+.2f} pp",
        ha="center",
        fontsize=9,
        color=SLATE,
    )

    only = factorial["only"]
    labels = ["C1\nTaxonomies", "C2\nProcédure", "C3\nGrille", "C4\nLes deux"]
    values = [only["only_c1"], only["only_c2"], only["only_c3"], only["only_c4"]]
    colors = [SLATE_LIGHT, AMBER, BLUE, RED]
    ax2.bar(range(4), values, color=colors, width=0.58)
    ax2.set_xticks(range(4))
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Posts correctement classés par une seule cellule")
    ax2.set_title("Victoire propre de C4", fontsize=12, fontweight="bold")
    ax2.grid(axis="y", color="#E5E7EB", linewidth=0.7)
    ax2.set_axisbelow(True)
    for i, value in enumerate(values):
        ax2.text(i, value + 0.15, str(value), ha="center", fontsize=9, fontweight="bold")

    fig.suptitle("Test 2x2 : le gain ne se réduit ni à la grille seule ni à la procédure seule", fontsize=13.2, fontweight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(ASSETS_DIR / "factorial_test_2x2.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "factorial_test_2x2.pdf", bbox_inches="tight")
    plt.close(fig)


def make_audit_figure() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.3, 5.2))
    cats = ["A", "B", "C", "D"]
    colors = [GREEN, BLUE, AMBER, RED]
    datasets = ["alpha", "test"]
    bottoms = [0, 0]
    for cat, color in zip(cats, colors):
        values = [AUDIT_COUNTS[dataset][cat] for dataset in datasets]
        ax1.bar(datasets, values, bottom=bottoms, color=color, width=0.55, label=cat)
        for i, value in enumerate(values):
            if value:
                ax1.text(i, bottoms[i] + value / 2, f"{cat}\n{value}", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        bottoms = [bottoms[i] + values[i] for i in range(2)]
    ax1.set_title("Composition des gains ASSIST codés a posteriori", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Nombre de gains ASSIST audités")
    ax1.legend(title="Catégorie", fontsize=9)

    labels = list(PURE_C4_SYNERGY)
    values = list(PURE_C4_SYNERGY.values())
    ax2.bar(labels, values, color=[RED, AMBER, SLATE], width=0.56)
    ax2.set_title("Lecture des 8 victoires pures de C4", fontsize=12, fontweight="bold")
    ax2.set_ylabel("Nombre de posts")
    for i, value in enumerate(values):
        ax2.text(i, value + 0.1, str(value), ha="center", fontsize=9, fontweight="bold")
    ax2.text(
        1,
        max(values) + 0.7,
        "6/8 cas relèvent d’une synergie forte ou moyenne,\nsoit 75% du noyau dur C4.",
        ha="center",
        fontsize=8.8,
        color=SLATE,
    )
    fig.suptitle("Audit qualitatif : procédure majoritaire, mais un noyau dur de synergie existe", fontsize=13.1, fontweight="bold", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(ASSETS_DIR / "audit_summary.png", bbox_inches="tight")
    fig.savefig(ASSETS_DIR / "audit_summary.pdf", bbox_inches="tight")
    plt.close(fig)


def make_tables(stats: dict, runs: list[dict], disjoint: list[dict], pooled: dict, axis_summary: list[dict], factorial: dict) -> None:
    write_text(
        GENERATED_DIR / "table_dataset_stats.tex",
        "\n".join(
            [
                r"\begin{tabular}{lrr}",
                r"\toprule",
                r"Indicateur & Valeur \\",
                r"\midrule",
                f"Posts bruts en base & {stats['posts_total']} \\\\",
                f"Posts échantillonnés (\\texttt{{sample\\_posts}}) & {stats['sample_total']} \\\\",
                f"Annotations humaines uniques & {stats['annotations_total']} \\\\",
                f"Dev annoté & {stats['dev_annotated']} / {stats['sample_dev']} \\\\",
                f"Test brut annoté & {stats['test_annotated_raw']} / {stats['sample_test_raw']} \\\\",
                f"Test exclus pour \\texttt{{doubtful=true}} & {stats['test_doubtful']} \\\\",
                f"Alpha utilisé & {stats['alpha_posts']} \\\\",
                f"Test utilisé & {stats['test_posts']} \\\\",
                f"Recouvrement alpha $\\cap$ test & {stats['overlap']} \\\\",
                f"Alpha uniquement & {stats['alpha_only']} \\\\",
                f"Test uniquement & {stats['test_only']} \\\\",
                f"Classes VF observées dans alpha & {stats['alpha_vf_classes']} \\\\",
                f"Classes VF observées dans test & {stats['test_vf_classes']} \\\\",
                r"\bottomrule",
                r"\end{tabular}",
            ]
        ),
    )

    final_rows = [row for row in runs if row["id"] in {158,159,160,161,164,165,167,171,172,176,177,178,181,182,183,185}]
    final_rows = sorted(final_rows, key=lambda row: (row["dataset"], row["mode"], row["id"]))
    table_lines = [
        r"\begin{longtable}{llrrrrrr}",
        r"\toprule",
        r"Run & Configuration & VF & Cat. & Strat. & Coût & Posts & Latence moy. \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Run & Configuration & VF & Cat. & Strat. & Coût & Posts & Latence moy. \\",
        r"\midrule",
        r"\endhead",
    ]
    for row in final_rows:
        table_lines.append(
            f"{row['id']} & {latex_escape(row['dataset'])} -- {latex_escape(row['label'])} "
            f"& {tex_pct(row['vf'])} & {tex_pct(row['cat'])} & {tex_pct(row['strat'])} "
            f"& \\${row['total_cost_usd']:.2f} & {row['n_vf']} & {row['avg_latency_s']:.1f}s \\\\"
        )
    table_lines.extend([r"\bottomrule", r"\end{longtable}"])
    write_text(GENERATED_DIR / "table_final_runs.tex", "\n".join(table_lines))

    flash_rows = [row for row in disjoint if row["agent"] == "visual_format" and row["subset"] in {"flash_alpha_only", "flash_test_only", "flashlite_alpha_only", "flashlite_test_only"}]
    disjoint_lines = [
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Tier & Sous-ensemble & ASSIST & no-ASSIST & $\Delta$ & Gains & Pertes & $p_{\mathrm{exact}}$ \\",
        r"\midrule",
    ]
    label_map = {
        "flash_alpha_only": ("Flash", "alpha only"),
        "flash_test_only": ("Flash", "test only"),
        "flashlite_alpha_only": ("Flash Lite", "alpha only"),
        "flashlite_test_only": ("Flash Lite", "test only"),
    }
    for row in flash_rows:
        tier, subset = label_map[row["subset"]]
        disjoint_lines.append(
            f"{tier} & {subset} & {tex_pct(row['assist_pct'])} & {tex_pct(row['noassist_pct'])} & "
            f"{tex_pp(row['delta_pp'])} & {row['gains']} & {row['losses']} & {row['p_exact']:.3f} \\\\"
        )
    disjoint_lines.extend(
        [
            r"\midrule",
            f"Flash & pooled disjoint & {tex_pct(pooled['flash']['assist_pct'])} & {tex_pct(pooled['flash']['noassist_pct'])} & {tex_pp(pooled['flash']['delta_pp'])} & {pooled['flash']['gains']} & {pooled['flash']['losses']} & {pooled['flash']['p_exact']:.3f} \\\\",
            f"Flash Lite & pooled disjoint & {tex_pct(pooled['flashlite']['assist_pct'])} & {tex_pct(pooled['flashlite']['noassist_pct'])} & {tex_pp(pooled['flashlite']['delta_pp'])} & {pooled['flashlite']['gains']} & {pooled['flashlite']['losses']} & {pooled['flashlite']['p_exact']:.3f} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
        ]
    )
    write_text(GENERATED_DIR / "table_assist_disjoint.tex", "\n".join(disjoint_lines))

    axis_lines = [
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Tier & Axe & ASSIST & no-ASSIST & $\Delta$ & Gains & Pertes & $p_{\mathrm{exact}}$ \\",
        r"\midrule",
    ]
    axis_name_map = {"visual_format": "visual\\_format", "category": "category", "strategy": "strategy"}
    for row in axis_summary:
        axis_lines.append(
            f"{row['tier']} & {axis_name_map[row['agent']]} & {tex_pct(row['assist_pct'])} & {tex_pct(row['noassist_pct'])} & {tex_pp(row['delta_pp'])} & {row['gains']} & {row['losses']} & {row['p_exact']:.3f} \\\\"
        )
    axis_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write_text(GENERATED_DIR / "table_axis_pooled.tex", "\n".join(axis_lines))

    score_map = {row["run_id"]: row for row in factorial["scores"]}
    pair_map = {(row["run_a"], row["run_b"]): row for row in factorial["pairs"]}
    factorial_lines = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Cellule & Configuration & Accuracy VF & Posts & Coût run & Only correct \\",
        r"\midrule",
        f"C1 & taxonomies seules (run 185) & {tex_pct(score_map[185]['pct'])} & {score_map[185]['n']} & \\$1.64 & {factorial['only']['only_c1']} \\\\",
        f"C2 & taxonomies + procédure (run 188) & {tex_pct(score_map[188]['pct'])} & {score_map[188]['n']} & \\$2.50 & {factorial['only']['only_c2']} \\\\",
        f"C3 & taxonomies + grille (run 187) & {tex_pct(score_map[187]['pct'])} & {score_map[187]['n']} & \\$2.54 & {factorial['only']['only_c3']} \\\\",
        f"C4 & taxonomies + procédure + grille (run 181) & {tex_pct(score_map[181]['pct'])} & {score_map[181]['n']} & \\$5.49 & {factorial['only']['only_c4']} \\\\",
        r"\midrule",
        f"Effet grille & moyenne de (C3-C1) et (C4-C2) & \\multicolumn{{4}}{{r}}{{{tex_pp(factorial['effects']['grille_main'])}}} \\\\",
        f"Effet procédure & moyenne de (C2-C1) et (C4-C3) & \\multicolumn{{4}}{{r}}{{{tex_pp(factorial['effects']['procedure_main'])}}} \\\\",
        f"Interaction & (C4-C3) - (C2-C1) & \\multicolumn{{4}}{{r}}{{{tex_pp(factorial['effects']['interaction'])}}} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    write_text(GENERATED_DIR / "table_factorial_2x2.tex", "\n".join(factorial_lines))

    pair_lines = [
        r"\begin{tabular}{llrrr}",
        r"\toprule",
        r"Comparaison & Lecture & Gains A & Gains B & $p_{\mathrm{exact}}$ \\",
        r"\midrule",
    ]
    pair_labels = {
        (181, 185): "C4 vs C1",
        (181, 187): "C4 vs C3",
        (181, 188): "C4 vs C2",
        (185, 187): "C1 vs C3",
        (185, 188): "C1 vs C2",
        (187, 188): "C3 vs C2",
    }
    for key in ((181, 185), (181, 187), (181, 188), (185, 187), (185, 188), (187, 188)):
        row = pair_map[key]
        pair_lines.append(
            f"{pair_labels[key]} & run {row['run_a']} vs run {row['run_b']} & {row['a_only']} & {row['b_only']} & {row['p_exact']:.3f} \\\\"
        )
    pair_lines.extend([r"\bottomrule", r"\end{tabular}"])
    write_text(GENERATED_DIR / "table_factorial_pairs.tex", "\n".join(pair_lines))
    write_text(
        GENERATED_DIR / "table_audit_counts.tex",
        "\n".join(
            [
                r"\begin{tabular}{lrrrrr}",
                r"\toprule",
                r"Dataset & A & B & C & D & Total \\",
                r"\midrule",
                f"Alpha & {AUDIT_COUNTS['alpha']['A']} & {AUDIT_COUNTS['alpha']['B']} & {AUDIT_COUNTS['alpha']['C']} & {AUDIT_COUNTS['alpha']['D']} & {AUDIT_COUNTS['alpha']['n']} \\\\",
                f"Test & {AUDIT_COUNTS['test']['A']} & {AUDIT_COUNTS['test']['B']} & {AUDIT_COUNTS['test']['C']} & {AUDIT_COUNTS['test']['D']} & {AUDIT_COUNTS['test']['n']} \\\\",
                r"\bottomrule",
                r"\end{tabular}",
            ]
        ),
    )


def excerpt_around(text: str, focus: str, span: int = 250) -> str:
    idx = text.lower().find(focus.lower())
    if idx == -1:
        return text[: min(len(text), 520)]
    start = max(0, idx - span)
    end = min(len(text), idx + len(focus) + span)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    return excerpt


def apply_highlights(text: str, phrases: list[str], macro: str) -> str:
    intervals: list[tuple[int, int]] = []
    lower = text.lower()
    for phrase in phrases:
        idx = lower.find(phrase.lower())
        if idx == -1:
            continue
        interval = (idx, idx + len(phrase))
        if any(not (interval[1] <= other[0] or interval[0] >= other[1]) for other in intervals):
            continue
        intervals.append(interval)
    intervals.sort()
    if not intervals:
        return latex_escape(text)
    out = []
    pos = 0
    for start, end in intervals:
        out.append(latex_escape(text[pos:start]))
        out.append(f"{macro}{{{latex_escape(text[start:end])}}}")
        pos = end
    out.append(latex_escape(text[pos:]))
    return "".join(out)


def make_trace_appendix(trace_payload: list[dict]) -> None:
    lines = []
    for case in trace_payload:
        left_excerpt = excerpt_around(case["left_reasoning"], case["left_focus"])
        right_excerpt = excerpt_around(case["right_reasoning"], case["right_focus"])
        left_tex = apply_highlights(left_excerpt, case["left_highlights"], r"\tracehlleft")
        right_tex = apply_highlights(right_excerpt, case["right_highlights"], r"\tracehlright")
        subtitle = (
            f"Post {case['post_id']} — GT: \\texttt{{{latex_escape(case['gt_label'])}}}; "
            f"transition \\texttt{{{latex_escape(case['left_pred'])}}} $\\rightarrow$ \\texttt{{{latex_escape(case['right_pred'])}}}."
        )
        lines.extend(
            [
                rf"\subsection*{{{latex_escape(case['title'])}}}",
                rf"\textbf{{Lecture quantitative.}} {latex_escape(case['quant_note'])}",
                rf"\par\smallskip\textbf{{Métadonnées.}} {subtitle}",
            ]
        )
        if "extra_predictions" in case:
            pred = case["extra_predictions"]
            lines.append(
                rf"\par\smallskip\textbf{{2x2 complet.}} C1=\texttt{{{latex_escape(pred['C1'])}}}, "
                rf"C2=\texttt{{{latex_escape(pred['C2'])}}}, C3=\texttt{{{latex_escape(pred['C3'])}}}, "
                rf"C4=\texttt{{{latex_escape(pred['C4'])}}}."
            )
        lines.extend(
            [
                rf"\TraceBox{{{latex_escape(case['left_label'])}}}{{{left_tex}}}",
                rf"\TraceBox{{{latex_escape(case['right_label'])}}}{{{right_tex}}}",
                "",
            ]
        )
    write_text(GENERATED_DIR / "appendix_traces.tex", "\n".join(lines))


def write_summary_json(stats: dict, runs: list[dict], disjoint: list[dict], pooled: dict, axis_summary: list[dict], factorial: dict) -> None:
    payload = {
        "dataset_stats": stats,
        "final_runs": runs,
        "assist_disjoint": disjoint,
        "assist_pooled_disjoint": pooled,
        "assist_axis_pooled": axis_summary,
        "factorial_2x2": factorial,
        "audit_counts": AUDIT_COUNTS,
        "pure_c4_synergy": PURE_C4_SYNERGY,
    }
    write_text(
        GENERATED_DIR / "summary.json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=float),
    )


def main() -> None:
    stats = fetch_dataset_stats()
    distribution = fetch_class_distribution()
    runs = fetch_final_runs()
    disjoint = fetch_disjoint_assist_results()
    pooled = summarize_disjoint(disjoint)
    axis_summary = pooled_axis_summary(disjoint)
    factorial = fetch_factorial_2x2()
    traces = fetch_trace_payload()

    make_system_overview()
    make_dataset_overlap(stats)
    make_vf_distribution(distribution)
    make_final_runs_cost_perf(runs)
    make_assist_disjoint_figure(disjoint, pooled, axis_summary)
    make_factorial_figure(factorial)
    make_audit_figure()

    make_tables(stats, runs, disjoint, pooled, axis_summary, factorial)
    make_trace_appendix(traces)
    write_summary_json(stats, runs, disjoint, pooled, axis_summary, factorial)

    print("Assets générés dans:")
    print(f"  - {ASSETS_DIR}")
    print(f"  - {GENERATED_DIR}")


if __name__ == "__main__":
    main()
