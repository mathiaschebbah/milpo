"""Évaluation native DSPy des programmes compilés sur le test split.

Ce script charge les 4 programmes compilés (category, visual_format FEED,
visual_format REELS, strategy) pour un mode donné, les exécute sur les 437
posts du test split via le runtime DSPy natif, et stocke les chiffres dans
`simulation_runs` sous le nom `B_dspy_native_{mode}`.

C'est le **bonus gratuit** discuté dans le plan : les chiffres « DSPy
end-to-end avec son propre runtime », qui répondent à la question « que
ferait DSPy si on l'utilisait comme un utilisateur lambda l'utiliserait ? ».
La différence avec B_dspy_in_milpo_{mode} (mêmes prompts, runtime MILPO)
mesure empiriquement la contribution du runtime à la performance.

ATTENTION : ce script LANCE des appels au LLM (Qwen via OpenRouter) pour
les 437 posts × 3 axes ≈ 1300 appels. Coût attendu : ~$1. Durée : ~5 min.
Ne pas exécuter sans validation.

Usage :
    .venv/bin/python -m related_work.dspy_baseline.evaluate_native --mode constrained
    .venv/bin/python -m related_work.dspy_baseline.evaluate_native --mode free
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import dspy

from milpo.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_CLASSIFIER
from milpo.db import get_conn

from related_work.dspy_baseline.data import (
    load_descriptions,
    load_examples,
    load_label_lists,
)
from related_work.dspy_baseline.metrics import accuracy_per_axis
from related_work.dspy_baseline.pipeline import build_program

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dspy_evaluate_native")


TASK_MODEL = f"openrouter/{MODEL_CLASSIFIER}"


# ── Chargement des programmes compilés ──────────────────────────


def _compiled_path(mode: str, axis: str, scope: str | None) -> Path:
    base = Path(__file__).resolve().parent / "compiled"
    scope_label = scope or "all"
    return base / f"{mode}_{axis}_{scope_label}.json"


def load_compiled_programs(
    conn,
    mode: str,
) -> dict[tuple[str, str | None], dspy.Module]:
    """Charge les 4 programmes compilés pour un mode donné.

    Returns:
        dict avec clés :
        - ("category", None)
        - ("visual_format", "FEED")
        - ("visual_format", "REELS")
        - ("strategy", None)
    """
    descriptions = load_descriptions(conn)
    labels = load_label_lists(conn)

    targets = [
        ("category", None, "category"),
        ("visual_format", "FEED", "visual_format_FEED"),
        ("visual_format", "REELS", "visual_format_REELS"),
        ("strategy", None, "strategy"),
    ]

    programs: dict[tuple[str, str | None], dspy.Module] = {}
    for axis, scope, key in targets:
        path = _compiled_path(mode, axis, scope)
        if not path.exists():
            raise FileNotFoundError(
                f"Programme compilé manquant : {path}\n"
                f"  → lancer d'abord : python -m related_work.dspy_baseline.optimize "
                f"--mode {mode} --axis {axis}"
                + (f" --scope {scope}" if scope else "")
            )

        program = build_program(
            mode=mode,
            axis=axis,
            scope=scope,
            descriptions=descriptions[key],
            valid_labels=labels[key],
        )
        program.load(str(path))
        programs[(axis, scope)] = program
        log.info("  Programme chargé : %s/%s ← %s", axis, scope or "all", path.name)

    return programs


# ── Boucle d'évaluation ─────────────────────────────────────────


def run_eval(
    test_examples: list[dspy.Example],
    test_sources,
    programs: dict[tuple[str, str | None], dspy.Module],
) -> tuple[dict[str, float], int, int]:
    """Évalue les 3 axes sur le test split via le runtime DSPy natif.

    Pour chaque example :
    - category   : appelle programs[("category", None)]
    - strategy   : appelle programs[("strategy", None)]
    - visual_format : appelle programs[("visual_format", scope)] selon scope du post

    Returns:
        Tuple (accuracies, n_total, n_failed). accuracies = dict {axis: acc}.
    """
    if len(test_examples) != len(test_sources):
        raise ValueError("examples et sources doivent avoir la même longueur")

    matches = {"category": 0, "visual_format": 0, "strategy": 0}
    n_total_per_axis = {"category": 0, "visual_format": 0, "strategy": 0}
    n_failed = 0

    for i, (ex, src) in enumerate(zip(test_examples, test_sources)):
        scope = src.scope
        try:
            cat_pred = programs[("category", None)](
                features=ex.features, caption=ex.caption, scope=scope,
            )
            strat_pred = programs[("strategy", None)](
                features=ex.features, caption=ex.caption, scope=scope,
            )
            vf_pred = programs[("visual_format", scope)](
                features=ex.features, caption=ex.caption, scope=scope,
            )
        except Exception as exc:
            log.warning("Post %s : échec d'inférence (%s)", src.ig_media_id, exc)
            n_failed += 1
            continue

        n_total_per_axis["category"] += 1
        if str(getattr(cat_pred, "category", "")).strip() == ex.category:
            matches["category"] += 1

        n_total_per_axis["strategy"] += 1
        if str(getattr(strat_pred, "strategy", "")).strip() == ex.strategy:
            matches["strategy"] += 1

        n_total_per_axis["visual_format"] += 1
        if str(getattr(vf_pred, "visual_format", "")).strip() == ex.visual_format:
            matches["visual_format"] += 1

        if (i + 1) % 50 == 0:
            log.info("  ... %d / %d", i + 1, len(test_examples))

    accuracies = {
        axis: matches[axis] / n_total_per_axis[axis] if n_total_per_axis[axis] > 0 else 0.0
        for axis in matches
    }
    n_total = max(n_total_per_axis.values())
    return accuracies, n_total, n_failed


# ── Persistance dans simulation_runs ────────────────────────────


def create_run(conn, mode: str) -> int:
    row = conn.execute(
        """
        INSERT INTO simulation_runs (seed, batch_size, config, status, started_at)
        VALUES (42, 0, %s::jsonb, 'running', NOW())
        RETURNING id
        """,
        (
            json.dumps({
                "name": f"B_dspy_native_{mode}",
                "kind": "dspy_native_eval",
                "split": "test",
                "mode": mode,
                "task_model": TASK_MODEL,
                "description": (
                    f"Évaluation native DSPy des programmes compilés "
                    f"({mode}) sur le test split. Runtime DSPy "
                    f"(JSONAdapter), pas tool calling Qwen. À comparer "
                    f"avec B_dspy_in_milpo_{mode} pour mesurer la "
                    f"contribution du runtime."
                ),
            }),
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


def finish_run(
    conn,
    run_id: int,
    accuracies: dict[str, float],
    n_total: int,
    n_failed: int,
) -> None:
    conn.execute(
        """
        UPDATE simulation_runs
        SET status = 'completed', finished_at = NOW(),
            final_accuracy_category = %s,
            final_accuracy_visual_format = %s,
            final_accuracy_strategy = %s,
            config = config || %s::jsonb
        WHERE id = %s
        """,
        (
            accuracies["category"],
            accuracies["visual_format"],
            accuracies["strategy"],
            json.dumps({
                "n_total": n_total,
                "n_failed": n_failed,
            }),
            run_id,
        ),
    )
    conn.commit()


# ── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Évalue les programmes DSPy compilés en runtime natif sur le test split."
    )
    parser.add_argument(
        "--mode",
        choices=("constrained", "free"),
        required=True,
    )
    args = parser.parse_args()

    log.info("=" * 55)
    log.info("DSPy native eval — mode=%s", args.mode)
    log.info("=" * 55)

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY non définie")

    # Configuration du LM DSPy
    task_lm = dspy.LM(
        TASK_MODEL,
        api_key=OPENROUTER_API_KEY,
        api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        max_tokens=1024,
    )
    dspy.configure(lm=task_lm)
    log.info("Task LM configuré : %s", TASK_MODEL)

    conn = get_conn()
    t0 = time.monotonic()

    # 1. Charger les 4 programmes compilés
    log.info("Chargement des programmes compilés...")
    programs = load_compiled_programs(conn, args.mode)

    # 2. Charger les examples test (437 posts avec features cachées)
    log.info("Chargement du test split...")
    test_examples, test_sources = load_examples(conn, split="test")
    log.info("Examples test : %d", len(test_examples))

    # 3. Créer le run dans simulation_runs
    run_id = create_run(conn, args.mode)
    log.info("simulation_run id=%d", run_id)

    # 4. Évaluation
    log.info("Évaluation en cours...")
    accuracies, n_total, n_failed = run_eval(test_examples, test_sources, programs)

    # 5. Persistance
    finish_run(conn, run_id, accuracies, n_total, n_failed)

    elapsed = time.monotonic() - t0
    log.info("")
    log.info("=" * 55)
    log.info("RÉSULTATS B_dspy_native_%s", args.mode)
    log.info("=" * 55)
    log.info("  Posts évalués     : %d (%d en échec)", n_total, n_failed)
    log.info("  Durée             : %.0fs (%.1f min)", elapsed, elapsed / 60)
    log.info("")
    log.info("  Accuracy catégorie     : %.1f%%", accuracies["category"] * 100)
    log.info("  Accuracy visual_format : %.1f%%", accuracies["visual_format"] * 100)
    log.info("  Accuracy stratégie     : %.1f%%", accuracies["strategy"] * 100)
    log.info("")
    log.info("  simulation_run_id = %d", run_id)
    log.info("✓ B_dspy_native_%s terminé", args.mode)

    conn.close()


if __name__ == "__main__":
    main()
