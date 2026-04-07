"""Optimisation MIPROv2 sur les classifieurs DSPy.

Lance MIPROv2 (zero-shot, instructions seulement) sur un (axe × scope × mode)
et sauvegarde le programme compilé sur disque pour réutilisation par
evaluate_native.py et import_to_db.py.

Choix méthodologiques :
- **Zero-shot only** (`max_bootstrapped_demos=0`, `max_labeled_demos=0`) :
  on optimise les instructions seules, pas les few-shot examples. Raisons :
  (a) la cardinalité élevée du visual_format (44/16 classes) rend le bootstrap
  de demos peu fiable, (b) on compare à MILPO qui n'utilise pas non plus de
  demos, (c) c'est plus rapide et moins cher.
- **Task LM = Qwen 3.5 Flash** : strictement le même modèle que MILPO, pour
  que la comparaison apples-to-apples ait un sens.
- **Proposer LM = Claude Opus 4.6** : modèle puissant pour générer les
  candidates d'instructions. Consomme un peu plus de budget mais améliore
  significativement la qualité des propositions.
- **Train/val split 80/20 déterministe** sur le dev split annoté. Le test
  split (437 posts) est gardé entièrement pour l'évaluation finale, jamais
  touché pendant l'optim.

ATTENTION : ce script LANCE des appels au LLM (Qwen via OpenRouter pour la
tâche, Claude via OpenRouter pour la proposition d'instructions). Ne pas
exécuter sans avoir validé que les annotations dev sont suffisantes et que
le budget OpenRouter est OK.

Usage :
    # Run pilote (validation du pipeline avant les 8 runs réels) :
    .venv/bin/python -m related_work.dspy_baseline.optimize \\
        --mode constrained --axis category --auto light

    # Runs complets pour le mode constrained :
    .venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis category --auto medium
    .venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis visual_format --scope FEED --auto medium
    .venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis visual_format --scope REELS --auto medium
    .venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis strategy --auto medium

    # Idem pour --mode free
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import dspy
from dspy.teleprompt import MIPROv2

from milpo.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_CLASSIFIER
from milpo.db import get_conn

from related_work.dspy_baseline.data import (
    load_descriptions,
    load_examples,
    load_label_lists,
    split_train_val,
)
from related_work.dspy_baseline.metrics import accuracy_metric
from related_work.dspy_baseline.pipeline import build_program

# ── Modèles ─────────────────────────────────────────────────────


# Task LM : strictement le même que MILPO (cf. milpo/config.py:MODEL_CLASSIFIER)
TASK_MODEL = f"openrouter/{MODEL_CLASSIFIER}"

# Proposer LM : Claude Opus 4.6 (haute capacité de raisonnement, 1M context)
PROPOSER_MODEL = "openrouter/anthropic/claude-opus-4-6"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dspy_optimize")


# ── Helpers de scope ────────────────────────────────────────────


def _resolve_descriptions_key(axis: str, scope: str | None) -> str:
    if axis == "visual_format":
        if scope is None:
            raise ValueError("visual_format nécessite un scope (FEED ou REELS)")
        return f"visual_format_{scope}"
    return axis


def _resolve_scope_filter(axis: str, scope: str | None) -> str | None:
    """Détermine si on doit filtrer le dev split par scope.

    Pour visual_format : on filtre (FEED ou REELS), parce que les labels
    sont scopés et les modèles différents.
    Pour category et strategy : on prend tous les posts du dev split.
    """
    if axis == "visual_format":
        return scope
    return None


def _compiled_path(mode: str, axis: str, scope: str | None) -> Path:
    """Chemin du fichier compilé pour un (mode, axis, scope) donné."""
    base = Path(__file__).resolve().parent / "compiled"
    base.mkdir(parents=True, exist_ok=True)
    scope_label = scope or "all"
    return base / f"{mode}_{axis}_{scope_label}.json"


# ── Configuration DSPy LMs ──────────────────────────────────────


def configure_dspy_lms(task_lm_kwargs: dict | None = None) -> tuple[dspy.LM, dspy.LM]:
    """Configure les deux LMs DSPy : task et proposer.

    Returns:
        Tuple (task_lm, proposer_lm).
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY non définie dans .env")

    task_kwargs = {
        "api_key": OPENROUTER_API_KEY,
        "api_base": OPENROUTER_BASE_URL,
        "temperature": 0.1,  # = MILPO
        "max_tokens": 1024,
    }
    if task_lm_kwargs:
        task_kwargs.update(task_lm_kwargs)

    task_lm = dspy.LM(TASK_MODEL, **task_kwargs)
    proposer_lm = dspy.LM(
        PROPOSER_MODEL,
        api_key=OPENROUTER_API_KEY,
        api_base=OPENROUTER_BASE_URL,
        temperature=1.0,  # explorer pour la génération de candidats
        max_tokens=8192,
    )

    dspy.configure(lm=task_lm)
    return task_lm, proposer_lm


# ── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Optimise un classifieur DSPy via MIPROv2 (zero-shot, instructions only)."
    )
    parser.add_argument(
        "--mode",
        choices=("constrained", "free"),
        required=True,
        help=(
            "constrained = descriptions taxonomiques fixes (apples-to-apples MILPO). "
            "free = MIPROv2 peut tout réécrire."
        ),
    )
    parser.add_argument(
        "--axis",
        choices=("category", "visual_format", "strategy"),
        required=True,
    )
    parser.add_argument(
        "--scope",
        choices=("FEED", "REELS"),
        default=None,
        help="Obligatoire pour --axis visual_format. Ignoré pour les autres.",
    )
    parser.add_argument(
        "--auto",
        choices=("light", "medium", "heavy"),
        default="medium",
        help="Niveau d'automatisation MIPROv2 (light = rapide, heavy = exhaustif).",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.2,
        help="Ratio train/val pour le split du dev split (default: 0.2).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed pour le shuffle train/val (default: 42).",
    )
    parser.add_argument(
        "--num-threads",
        type=int,
        default=8,
        help="Nombre de threads pour les évaluations parallèles MIPROv2.",
    )
    args = parser.parse_args()

    # Validation des combinaisons
    if args.axis == "visual_format" and args.scope is None:
        log.error("--scope est obligatoire pour --axis visual_format")
        sys.exit(2)
    if args.axis != "visual_format" and args.scope is not None:
        log.warning("--scope ignoré pour --axis %s", args.axis)
        args.scope = None

    log.info("=" * 55)
    log.info("DSPy MIPROv2 — mode=%s axis=%s scope=%s auto=%s",
             args.mode, args.axis, args.scope, args.auto)
    log.info("=" * 55)

    conn = get_conn()

    # 1. Charger les descriptions et labels valides
    descriptions_dict = load_descriptions(conn)
    labels_dict = load_label_lists(conn)
    descriptions_key = _resolve_descriptions_key(args.axis, args.scope)
    descriptions = descriptions_dict[descriptions_key]
    valid_labels = labels_dict[descriptions_key]
    log.info("Labels valides pour %s : %d", descriptions_key, len(valid_labels))

    # 2. Charger les examples dev (filtrés par scope si visual_format)
    scope_filter = _resolve_scope_filter(args.axis, args.scope)
    examples, _sources = load_examples(conn, split="dev", scope_filter=scope_filter)
    log.info("Examples dev (scope=%s) : %d", scope_filter or "tous", len(examples))

    if len(examples) < 20:
        log.error(
            "Trop peu d'examples (%d) pour optimiser sérieusement. "
            "Annoter davantage le dev split avant de relancer.",
            len(examples),
        )
        sys.exit(1)

    trainset, valset = split_train_val(examples, val_ratio=args.val_ratio, seed=args.seed)
    log.info("Split train/val : %d train / %d val", len(trainset), len(valset))

    # 3. Configurer les LMs DSPy
    task_lm, proposer_lm = configure_dspy_lms()
    log.info("Task LM     : %s", TASK_MODEL)
    log.info("Proposer LM : %s", PROPOSER_MODEL)

    # 4. Construire le programme à optimiser
    program = build_program(
        mode=args.mode,
        axis=args.axis,
        scope=args.scope,
        descriptions=descriptions,
        valid_labels=valid_labels,
    )
    log.info("Programme construit : %s", type(program).__name__)

    # 5. Configurer MIPROv2
    metric = accuracy_metric(args.axis)
    teleprompter = MIPROv2(
        metric=metric,
        prompt_model=proposer_lm,
        task_model=task_lm,
        auto=args.auto,
        num_threads=args.num_threads,
        verbose=True,
    )

    # 6. Compiler (= lancer l'optim)
    log.info("Lancement de MIPROv2.compile() ...")
    optimized = teleprompter.compile(
        program,
        trainset=trainset,
        valset=valset,
        max_bootstrapped_demos=0,  # zero-shot only — pas de few-shot demos
        max_labeled_demos=0,
        requires_permission_to_run=False,
    )

    # 7. Sauvegarder
    out_path = _compiled_path(args.mode, args.axis, args.scope)
    optimized.save(str(out_path))
    log.info("Programme sauvegardé : %s", out_path)

    log.info("")
    log.info("=" * 55)
    log.info("✓ Optimisation %s/%s/%s terminée", args.mode, args.axis, args.scope or "all")
    log.info("=" * 55)
    log.info("Pour évaluer en runtime DSPy natif :")
    log.info("  python -m related_work.dspy_baseline.evaluate_native --mode %s", args.mode)
    log.info("Pour évaluer apples-to-apples via MILPO runtime :")
    log.info("  python -m related_work.dspy_baseline.import_to_db --mode %s", args.mode)
    log.info("  uv run python scripts/run_baseline.py --prompts dspy_%s", args.mode)

    conn.close()


if __name__ == "__main__":
    main()
