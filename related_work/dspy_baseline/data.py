"""Couche données DSPy : load examples + descriptions taxonomiques + split.

Conventions :
- Les `dspy.Example` ont 3 input fields : `features` (str JSON), `caption` (str),
  `scope` (str FEED/REELS — utile pour le routage côté pipeline mais pas
  nécessairement consommé par toutes les signatures).
- Les 3 output fields gold sont `category`, `visual_format`, `strategy`.
- Le split train/val pour MIPROv2 est déterministe (seed=42).
- Le test split est utilisé tel quel pour l'évaluation finale (jamais touché
  pendant l'optimisation).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass

import dspy

from milpo.db import (
    format_descriptions,
    load_categories,
    load_strategies,
    load_visual_formats,
)


# ── Identifiant du run de feature cache (côté dev) ─────────────


FEATURE_EXTRACTION_RUN_NAME = "feature_cache_dev"
B0_RUN_ID = 7  # Run B0 stable qui contient les features test (cf. CLAUDE.md v2.28)


# ── Chargement des examples ─────────────────────────────────────


@dataclass
class ExampleSource:
    """Métadonnées d'un example pour debug et tracking."""

    ig_media_id: int
    scope: str  # FEED ou REELS
    feature_run_id: int  # run d'où viennent les features


def _resolve_feature_run_id(conn, split: str) -> int:
    """Retourne le run_id qui contient les features cachées pour ce split.

    Convention :
    - dev  → run dont config.name = 'feature_cache_dev' (généré par extract_features_dev.py)
    - test → run B0 stable (id=7, généré par run_baseline.py --prompts v0)
    """
    if split == "test":
        return B0_RUN_ID

    if split != "dev":
        raise ValueError(f"split inconnu : {split!r}")

    row = conn.execute(
        """
        SELECT id FROM simulation_runs
        WHERE config->>'name' = %s
        ORDER BY id DESC LIMIT 1
        """,
        (FEATURE_EXTRACTION_RUN_NAME,),
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"Aucun run de feature extraction trouvé pour le split dev "
            f"(config.name = '{FEATURE_EXTRACTION_RUN_NAME}'). "
            f"Lancer d'abord scripts/extract_features_dev.py."
        )
    return row["id"]


def load_examples(
    conn,
    split: str,
    scope_filter: str | None = None,
) -> tuple[list[dspy.Example], list[ExampleSource]]:
    """Charge les examples DSPy pour un split donné.

    Args:
        conn: connexion psycopg
        split: 'dev' ou 'test'
        scope_filter: None (tous), 'FEED', ou 'REELS'

    Returns:
        Tuple (examples, sources). examples = list[dspy.Example] avec input fields
        marqués via .with_inputs(). sources = métadonnées en parallèle pour debug.
    """
    feature_run_id = _resolve_feature_run_id(conn, split)

    scope_clause = ""
    params: list = [feature_run_id]
    if scope_filter is not None:
        if scope_filter not in ("FEED", "REELS"):
            raise ValueError(f"scope_filter invalide : {scope_filter!r}")
        scope_clause = "AND p.media_product_type = %s::media_product_type"
        params.append(scope_filter)

    rows = conn.execute(
        f"""
        SELECT
            p.ig_media_id,
            p.caption,
            p.media_product_type::text AS scope,
            c.name AS category_gold,
            vf.name AS visual_format_gold,
            a.strategy::text AS strategy_gold,
            pred.raw_response AS features_json
        FROM annotations a
        JOIN sample_posts sp ON sp.ig_media_id = a.ig_media_id
        JOIN posts p ON p.ig_media_id = a.ig_media_id
        JOIN categories c ON c.id = a.category_id
        JOIN visual_formats vf ON vf.id = a.visual_format_id
        JOIN predictions pred
            ON pred.ig_media_id = p.ig_media_id
            AND pred.agent = 'descriptor'
            AND pred.simulation_run_id = %s
        WHERE sp.split = %s
        {scope_clause}
        ORDER BY sp.presentation_order
        """,
        (feature_run_id, split, *params[1:]),
    ).fetchall()

    examples: list[dspy.Example] = []
    sources: list[ExampleSource] = []

    for row in rows:
        # Le raw_response est déjà du JSON natif côté psycopg (jsonb → dict).
        # On le re-sérialise en string parce que les InputField DSPy attendent
        # un type primitif simple (str), et ça permet aux signatures d'inclure
        # ce JSON tel quel dans le prompt envoyé au LM.
        features_json_str = json.dumps(row["features_json"], ensure_ascii=False, indent=2)

        ex = dspy.Example(
            features=features_json_str,
            caption=row["caption"] or "(pas de caption)",
            scope=row["scope"],
            category=row["category_gold"],
            visual_format=row["visual_format_gold"],
            strategy=row["strategy_gold"],
        ).with_inputs("features", "caption", "scope")

        examples.append(ex)
        sources.append(ExampleSource(
            ig_media_id=row["ig_media_id"],
            scope=row["scope"],
            feature_run_id=feature_run_id,
        ))

    return examples, sources


# ── Chargement des descriptions taxonomiques (mode constrained) ──


def load_descriptions(conn) -> dict[str, str]:
    """Charge les descriptions taxonomiques formatées pour chaque axe / scope.

    Returns:
        dict avec les clés :
        - 'category'             : descriptions des 15 catégories (sans scope)
        - 'visual_format_FEED'   : descriptions des 44 formats post_*
        - 'visual_format_REELS'  : descriptions des 16 formats reel_*
        - 'strategy'             : descriptions des 2 stratégies
    """
    return {
        "category": format_descriptions(load_categories(conn)),
        "visual_format_FEED": format_descriptions(load_visual_formats(conn, "FEED")),
        "visual_format_REELS": format_descriptions(load_visual_formats(conn, "REELS")),
        "strategy": format_descriptions(load_strategies(conn)),
    }


def load_label_lists(conn) -> dict[str, list[str]]:
    """Charge la liste plate des labels valides par axe / scope.

    Utilisé pour la validation post-prédiction (DSPy ne contraint pas l'output
    à un enum fermé comme le tool calling MILPO).
    """
    return {
        "category": [c["name"] for c in load_categories(conn)],
        "visual_format_FEED": [v["name"] for v in load_visual_formats(conn, "FEED")],
        "visual_format_REELS": [v["name"] for v in load_visual_formats(conn, "REELS")],
        "strategy": [s["name"] for s in load_strategies(conn)],
    }


# ── Split train/val déterministe ────────────────────────────────


def split_train_val(
    examples: list[dspy.Example],
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dspy.Example], list[dspy.Example]]:
    """Split déterministe train/val pour MIPROv2.

    Le seed est fixé pour la reproductibilité. Le shuffle est fait sur une
    copie pour ne pas altérer la liste passée en argument.
    """
    if not examples:
        return [], []
    if not 0.0 < val_ratio < 1.0:
        raise ValueError(f"val_ratio doit être dans (0, 1), reçu : {val_ratio}")

    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_val = max(1, int(len(shuffled) * val_ratio))
    val = shuffled[:n_val]
    train = shuffled[n_val:]
    return train, val
