"""Import des instructions DSPy optimisées dans prompt_versions.

Pour chaque programme compilé `{mode}_{axis}_{scope}.json` produit par
optimize.py, ce script :
1. Recharge le programme via DSPy
2. Extrait la string `instructions` finale (post-MIPROv2) de la signature
3. Insère cette instruction dans la table `prompt_versions` avec
   `source='dspy_{mode}'`, `status='active'`, et un numéro de version
   incrémental dans le slot (agent, scope, source)

Une fois ce script exécuté, les prompts DSPy sont disponibles dans la BDD
exactement comme les prompts v0 ou MILPO. Pour les utiliser dans le
runtime MILPO existant :

    uv run python scripts/run_baseline.py --prompts dspy_constrained
    uv run python scripts/run_baseline.py --prompts dspy_free

Le slot `descriptor` n'est jamais touché — DSPy ne l'optimise pas dans ce
protocole expérimental (gelé par design). Le runtime MILPO chargera
automatiquement le descripteur v0 humain en fallback.

ATTENTION : ce script écrit en BDD (INSERT dans prompt_versions). Il ne
lance AUCUN appel LLM, mais il modifie l'état de la BDD. Reversible via :
    DELETE FROM prompt_versions WHERE source IN ('dspy_constrained', 'dspy_free');

Usage :
    .venv/bin/python -m related_work.dspy_baseline.import_to_db --mode constrained
    .venv/bin/python -m related_work.dspy_baseline.import_to_db --mode free
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import dspy

from milpo.db import (
    get_active_prompt,
    get_conn,
    insert_prompt_version,
)

from related_work.dspy_baseline.data import (
    load_descriptions,
    load_label_lists,
)
from related_work.dspy_baseline.pipeline import build_program

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dspy_import_to_db")


# Mapping (axis, scope) → (agent_type, scope) tels qu'utilisés dans prompt_versions
PROMPT_TARGETS: list[tuple[str, str | None]] = [
    ("category", None),
    ("visual_format", "FEED"),
    ("visual_format", "REELS"),
    ("strategy", None),
]


def _compiled_path(mode: str, axis: str, scope: str | None) -> Path:
    base = Path(__file__).resolve().parent / "compiled"
    scope_label = scope or "all"
    return base / f"{mode}_{axis}_{scope_label}.json"


def _resolve_descriptions_key(axis: str, scope: str | None) -> str:
    if axis == "visual_format":
        return f"visual_format_{scope}"
    return axis


def _next_version(conn, agent: str, scope: str | None, source: str) -> int:
    """Retourne le prochain numéro de version disponible pour ce slot."""
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version), -1) + 1 AS next_version
        FROM prompt_versions
        WHERE agent = %s::agent_type
          AND scope IS NOT DISTINCT FROM %s::media_product_type
          AND source = %s
        """,
        (agent, scope, source),
    ).fetchone()
    return row["next_version"]


def _retire_existing_active(conn, agent: str, scope: str | None, source: str) -> None:
    """Retire l'éventuel prompt actif courant dans le slot (agent, scope, source).

    Nécessaire pour respecter la contrainte UNIQUE (agent, scope, source)
    WHERE status = 'active'. Si on ré-importe les prompts DSPy après une
    nouvelle optim, l'ancien doit être retiré avant d'insérer le nouveau.
    """
    conn.execute(
        """
        UPDATE prompt_versions
        SET status = 'retired'::prompt_status
        WHERE agent = %s::agent_type
          AND scope IS NOT DISTINCT FROM %s::media_product_type
          AND source = %s
          AND status = 'active'::prompt_status
        """,
        (agent, scope, source),
    )
    conn.commit()


def extract_instructions(program: dspy.Module) -> str:
    """Extrait la string d'instructions optimisées du programme DSPy.

    DSPy stocke l'instruction finale dans `program.predict.signature.instructions`
    après optimisation par MIPROv2. C'est la string qui sera collée comme
    system prompt par le runtime DSPy au moment de l'inférence.

    Pour notre cas (mode constrained), cette instruction NE contient PAS les
    descriptions taxonomiques (qui sont passées séparément en InputField).
    Pour le mode free, l'instruction inclut tout le docstring optimisé qui
    contient (potentiellement) une version retravaillée des descriptions.
    """
    if not hasattr(program, "predict"):
        raise RuntimeError(
            f"Programme {type(program).__name__} n'a pas d'attribut .predict"
        )
    sig = program.predict.signature
    instructions = sig.instructions
    if not instructions or not instructions.strip():
        raise RuntimeError(
            "Instructions vides dans le programme compilé — l'optim a probablement échoué"
        )
    return instructions


def main():
    parser = argparse.ArgumentParser(
        description="Importe les instructions DSPy optimisées dans prompt_versions."
    )
    parser.add_argument(
        "--mode",
        choices=("constrained", "free"),
        required=True,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Imprime les instructions extraites sans les insérer en BDD.",
    )
    args = parser.parse_args()

    source_label = f"dspy_{args.mode}"
    log.info("=" * 55)
    log.info("DSPy import to DB — mode=%s (source=%s)", args.mode, source_label)
    log.info("=" * 55)

    conn = get_conn()
    descriptions_dict = load_descriptions(conn)
    labels_dict = load_label_lists(conn)

    n_inserted = 0

    for axis, scope in PROMPT_TARGETS:
        path = _compiled_path(args.mode, axis, scope)
        if not path.exists():
            log.error(
                "Programme compilé manquant : %s\n"
                "  → lancer d'abord : python -m related_work.dspy_baseline.optimize "
                "--mode %s --axis %s%s",
                path,
                args.mode,
                axis,
                f" --scope {scope}" if scope else "",
            )
            continue

        # Recharger le programme pour extraire les instructions
        descriptions_key = _resolve_descriptions_key(axis, scope)
        program = build_program(
            mode=args.mode,
            axis=axis,
            scope=scope,
            descriptions=descriptions_dict[descriptions_key],
            valid_labels=labels_dict[descriptions_key],
        )
        program.load(str(path))

        instructions = extract_instructions(program)
        log.info(
            "Instruction extraite pour %s/%s (source=%s) : %d caractères",
            axis, scope or "all", source_label, len(instructions),
        )

        if args.dry_run:
            log.info("---")
            log.info("%s", instructions[:500])
            log.info("...(tronqué)" if len(instructions) > 500 else "")
            log.info("---")
            continue

        # Retirer l'ancien actif s'il existe (pour respecter UNIQUE constraint)
        existing = get_active_prompt(conn, axis, scope, source=source_label)
        if existing is not None:
            log.info(
                "  Retire l'ancien prompt actif (id=%d, version=%d)",
                existing["id"], existing["version"],
            )
            _retire_existing_active(conn, axis, scope, source_label)

        # Insérer le nouveau
        new_version = _next_version(conn, axis, scope, source_label)
        new_id = insert_prompt_version(
            conn,
            agent=axis,
            scope=scope,
            version=new_version,
            content=instructions,
            status="active",
            source=source_label,
        )
        log.info(
            "  → INSERT prompt_versions (id=%d, agent=%s, scope=%s, version=%d, source=%s)",
            new_id, axis, scope or "NULL", new_version, source_label,
        )
        n_inserted += 1

    log.info("")
    log.info("=" * 55)
    log.info("✓ Import terminé : %d prompts insérés (source=%s)", n_inserted, source_label)
    log.info("=" * 55)
    log.info("")
    log.info("Pour évaluer apples-to-apples via le runtime MILPO :")
    log.info("  uv run python scripts/run_baseline.py --prompts %s", source_label)

    conn.close()


if __name__ == "__main__":
    main()
