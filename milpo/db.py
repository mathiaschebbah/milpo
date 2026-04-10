"""Accès BDD pour le moteur MILPO (psycopg sync)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from milpo.config import DATABASE_DSN


def get_conn() -> psycopg.Connection:
    return psycopg.connect(DATABASE_DSN, row_factory=dict_row)


# ── Taxonomie ──────────────────────────────────────────────────


def load_visual_formats(conn: psycopg.Connection, scope: str) -> list[dict]:
    """Charge les formats visuels pour un scope (FEED→post_*, REELS→reel_*)."""
    prefix = "post_" if scope == "FEED" else "reel_"
    rows = conn.execute(
        "SELECT name, description FROM visual_formats WHERE name LIKE %s ORDER BY name",
        (f"{prefix}%",),
    ).fetchall()
    return rows


def load_categories(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT name, description FROM categories ORDER BY name"
    ).fetchall()


def load_strategies(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT name, description FROM strategies ORDER BY name"
    ).fetchall()


def format_descriptions(items: list[dict]) -> str:
    """Formate les descriptions taxonomiques pour injection dans le prompt."""
    lines = []
    for item in items:
        desc = item["description"] or "(pas de description)"
        lines.append(f"- **{item['name']}** : {desc}")
    return "\n".join(lines)


# ── Posts à classifier ─────────────────────────────────────────


def load_dev_posts(
    conn: psycopg.Connection,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Charge les posts dev non encore prédits, dans l'ordre de présentation."""
    query = """
        SELECT
            p.ig_media_id,
            p.caption,
            p.media_type::text AS media_type,
            p.media_product_type::text AS media_product_type,
            sp.presentation_order
        FROM sample_posts sp
        JOIN posts p ON p.ig_media_id = sp.ig_media_id
        WHERE sp.split = 'dev'
        ORDER BY sp.presentation_order
    """
    params: list = []
    if limit:
        query += " LIMIT %s OFFSET %s"
        params = [limit, offset]
    return conn.execute(query, params).fetchall()


def load_post_media(conn: psycopg.Connection, ig_media_id: int) -> list[dict]:
    """Charge les médias d'un post (images/vidéos) ordonnés."""
    return conn.execute(
        """
        SELECT
            ig_media_id,
            media_type::text AS media_type,
            media_url,
            thumbnail_url,
            media_order
        FROM post_media
        WHERE parent_ig_media_id = %s
        ORDER BY media_order
        """,
        (ig_media_id,),
    ).fetchall()


def load_posts_media(conn: psycopg.Connection, ig_media_ids: list[int]) -> dict[int, list[dict]]:
    """Charge en une requête les médias de plusieurs posts, ordonnés par post puis média."""
    if not ig_media_ids:
        return {}

    ordered_ids = list(dict.fromkeys(ig_media_ids))
    rows = conn.execute(
        """
        SELECT
            parent_ig_media_id,
            ig_media_id,
            media_type::text AS media_type,
            media_url,
            thumbnail_url,
            media_order
        FROM post_media
        WHERE parent_ig_media_id = ANY(%s)
        ORDER BY parent_ig_media_id, media_order
        """,
        (ordered_ids,),
    ).fetchall()

    by_post: dict[int, list[dict]] = {mid: [] for mid in ordered_ids}
    for row in rows:
        by_post[row["parent_ig_media_id"]].append(row)
    return by_post


# ── Prompt versions ────────────────────────────────────────────


def get_active_prompt(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
    source: str = "human_v0",
) -> dict | None:
    """Retourne le prompt actif pour un agent × scope × source.

    Le default `source='human_v0'` préserve le comportement MILPO existant
    (les prompts seedés par migration 006). Pour récupérer un prompt issu
    de DSPy ou d'une autre méthode, passer source='dspy_constrained' etc.

    NB : nécessite migration 007_prompt_source.sql appliquée.
    """
    if scope is None:
        return conn.execute(
            """
            SELECT id, agent, scope, version, content, source
            FROM prompt_versions
            WHERE agent = %s::agent_type AND scope IS NULL
              AND source = %s AND status = 'active'
            """,
            (agent, source),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, agent, scope, version, content, source
        FROM prompt_versions
        WHERE agent = %s::agent_type AND scope = %s::media_product_type
          AND source = %s AND status = 'active'
        """,
        (agent, scope, source),
    ).fetchone()


def get_prompt_version(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
    version: int,
    source: str = "human_v0",
) -> dict | None:
    """Retourne une version précise de prompt pour un agent × scope × source.

    Le default `source='human_v0'` préserve le comportement MILPO existant.

    NB : nécessite migration 007_prompt_source.sql appliquée.
    """
    if scope is None:
        return conn.execute(
            """
            SELECT id, agent, scope, version, content, status, source
            FROM prompt_versions
            WHERE agent = %s::agent_type AND scope IS NULL
              AND version = %s AND source = %s
            """,
            (agent, version, source),
        ).fetchone()
    return conn.execute(
        """
        SELECT id, agent, scope, version, content, status, source
        FROM prompt_versions
        WHERE agent = %s::agent_type AND scope = %s::media_product_type
          AND version = %s AND source = %s
        """,
        (agent, scope, version, source),
    ).fetchone()


def insert_prompt_version(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
    version: int,
    content: str,
    status: str = "active",
    parent_id: int | None = None,
    simulation_run_id: int | None = None,
    source: str = "human_v0",
) -> int:
    """Insère une nouvelle version de prompt. Retourne l'id.

    Le default `source='human_v0'` préserve le comportement MILPO existant.
    Pour insérer un prompt issu de DSPy, passer source='dspy_constrained' etc.

    NB : nécessite migration 007_prompt_source.sql appliquée.
    """
    row = conn.execute(
        """
        INSERT INTO prompt_versions
            (agent, scope, version, content, status, parent_id, simulation_run_id, source)
        VALUES (%s, %s, %s, %s, %s::prompt_status, %s, %s, %s)
        RETURNING id
        """,
        (agent, scope, version, content, status, parent_id, simulation_run_id, source),
    ).fetchone()
    conn.commit()
    return row["id"]


# ── Prédictions ────────────────────────────────────────────────


def store_prediction(
    conn: psycopg.Connection,
    ig_media_id: int,
    agent: str,
    prompt_version_id: int,
    predicted_value: str | None,
    raw_response: dict | None = None,
    simulation_run_id: int | None = None,
) -> int:
    """Stocke une prédiction. Le trigger calcule match automatiquement."""
    row = conn.execute(
        """
        INSERT INTO predictions
            (ig_media_id, agent, prompt_version_id, predicted_value, raw_response, simulation_run_id)
        VALUES (%s, %s::agent_type, %s, %s, %s::jsonb, %s)
        RETURNING id, match
        """,
        (
            ig_media_id, agent, prompt_version_id,
            predicted_value,
            json.dumps(raw_response) if raw_response else None,
            simulation_run_id,
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


# ── API calls ──────────────────────────────────────────────────


# ── Annotations (ground truth) ────────────────────────────────


def load_dev_annotations(conn: psycopg.Connection) -> dict[int, dict]:
    """Charge les annotations dev. Retourne {ig_media_id: {category, visual_format, strategy}}."""
    rows = conn.execute(
        """
        SELECT a.ig_media_id,
               c.name AS category,
               vf.name AS visual_format,
               a.strategy::text AS strategy
        FROM annotations a
        JOIN categories c ON c.id = a.category_id
        JOIN visual_formats vf ON vf.id = a.visual_format_id
        JOIN sample_posts sp ON sp.ig_media_id = a.ig_media_id
        WHERE sp.split = 'dev'
        ORDER BY sp.presentation_order
        """
    ).fetchall()
    return {
        r["ig_media_id"]: {
            "category": r["category"],
            "visual_format": r["visual_format"],
            "strategy": r["strategy"],
        }
        for r in rows
    }


# ── Prompt lifecycle ──────────────────────────────────────────



def promote_prompt(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
    new_id: int,
    source: str = "human_v0",
) -> None:
    """Retire tout prompt actif du slot (agent, scope, source) et active le nouveau.

    CRITIQUE : le filtrage par `source` est obligatoire après migration 007.
    Sans ça, promouvoir un prompt MILPO retirerait silencieusement les prompts
    DSPy actifs dans le même slot (agent, scope) — ce qui casserait le tagging
    multi-source mis en place pour les comparaisons baseline.

    Le default `source='human_v0'` préserve le comportement MILPO existant.

    NB : nécessite migration 007_prompt_source.sql appliquée.
    """
    with conn.transaction():
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
        conn.execute(
            "UPDATE prompt_versions SET status = 'active'::prompt_status WHERE id = %s",
            (new_id,),
        )


# ── Rewrite logs ──────────────────────────────────────────────


def store_rewrite_log(
    conn: psycopg.Connection,
    prompt_before_id: int,
    prompt_after_id: int,
    error_batch: list[dict],
    rewriter_reasoning: str,
    accepted: bool,
    simulation_run_id: int,
    target_agent: str,
    target_scope: str | None,
    incumbent_accuracy: float,
    candidate_accuracy: float,
    eval_sample_size: int,
    iteration: int,
) -> int:
    """Insère un log de rewrite. Retourne l'id."""
    row = conn.execute(
        """
        INSERT INTO rewrite_logs
            (prompt_before_id, prompt_after_id, error_batch, rewriter_reasoning,
             accepted, simulation_run_id, target_agent, target_scope,
             incumbent_accuracy, candidate_accuracy, eval_sample_size, iteration)
        VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s::agent_type, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            prompt_before_id, prompt_after_id,
            json.dumps(error_batch), rewriter_reasoning,
            accepted, simulation_run_id,
            target_agent, target_scope,
            incumbent_accuracy, candidate_accuracy, eval_sample_size, iteration,
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


# ── API calls ──────────────────────────────────────────────────


def store_api_call(
    conn: psycopg.Connection,
    call_type: str,
    agent: str,
    model_name: str,
    prompt_version_id: int | None,
    ig_media_id: int | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    latency_ms: int,
    simulation_run_id: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO api_calls
            (call_type, agent, model_name, prompt_version_id, ig_media_id,
             input_tokens, output_tokens, cost_usd, latency_ms, simulation_run_id)
        VALUES (%s::api_call_type, %s::agent_type, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            call_type, agent, model_name, prompt_version_id, ig_media_id,
            input_tokens, output_tokens, cost_usd, latency_ms, simulation_run_id,
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


# ── ProTeGi loop : gradients et beam candidates (migration 008) ───────────────


def store_gradient(
    conn: psycopg.Connection,
    *,
    simulation_run_id: int,
    iteration: int,
    target_agent: str,
    target_scope: str | None,
    prompt_id: int,
    gradient_text: str,
    n_critiques: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> int:
    """Insère un row dans rewrite_gradients (1 row par appel critic LLM_∇).

    Référence : Pryzant et al. 2023, EMNLP, ProTeGi.
    Migration : 008_protegi_loop.sql.
    """
    row = conn.execute(
        """
        INSERT INTO rewrite_gradients
            (simulation_run_id, iteration, target_agent, target_scope, prompt_id,
             gradient_text, n_critiques, model,
             input_tokens, output_tokens, latency_ms)
        VALUES (%s, %s, %s::agent_type, %s::media_product_type, %s,
                %s, %s, %s,
                %s, %s, %s)
        RETURNING id
        """,
        (
            simulation_run_id, iteration, target_agent, target_scope, prompt_id,
            gradient_text, n_critiques, model,
            input_tokens, output_tokens, latency_ms,
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


def store_beam_candidate(
    conn: psycopg.Connection,
    *,
    simulation_run_id: int,
    iteration: int,
    target_agent: str,
    target_scope: str | None,
    parent_prompt_id: int,
    candidate_prompt_id: int,
    gradient_id: int,
    generation_kind: str,           # 'edit' | 'paraphrase'
    eval_accuracy: float | None = None,
    eval_sample_size: int | None = None,
    sr_phase: int | None = None,
    sr_eliminated: bool = False,
    is_winner: bool = False,
) -> int:
    """Insère un candidat du beam ProTeGi dans rewrite_beam_candidates.

    L'évaluation et le bandit Successive Rejects sont remplis dans un second
    temps via update_beam_candidate_eval et update_beam_candidate_sr.

    Migration : 008_protegi_loop.sql.
    """
    if generation_kind not in ("edit", "paraphrase"):
        raise ValueError(
            f"store_beam_candidate: generation_kind invalide '{generation_kind}'"
        )
    row = conn.execute(
        """
        INSERT INTO rewrite_beam_candidates
            (simulation_run_id, iteration, target_agent, target_scope,
             parent_prompt_id, candidate_prompt_id, gradient_id, generation_kind,
             eval_accuracy, eval_sample_size, sr_phase, sr_eliminated, is_winner)
        VALUES (%s, %s, %s::agent_type, %s::media_product_type,
                %s, %s, %s, %s::generation_kind,
                %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            simulation_run_id, iteration, target_agent, target_scope,
            parent_prompt_id, candidate_prompt_id, gradient_id, generation_kind,
            eval_accuracy, eval_sample_size, sr_phase, sr_eliminated, is_winner,
        ),
    ).fetchone()
    conn.commit()
    return row["id"]


def update_beam_candidate_eval(
    conn: psycopg.Connection,
    *,
    candidate_row_id: int,
    eval_accuracy: float,
    eval_sample_size: int,
) -> None:
    """Renseigne l'accuracy d'un candidat après multi_evaluate."""
    conn.execute(
        """
        UPDATE rewrite_beam_candidates
        SET eval_accuracy = %s, eval_sample_size = %s
        WHERE id = %s
        """,
        (eval_accuracy, eval_sample_size, candidate_row_id),
    )
    conn.commit()


def update_beam_candidate_sr(
    conn: psycopg.Connection,
    *,
    candidate_row_id: int,
    sr_phase: int | None,
    sr_eliminated: bool,
    is_winner: bool = False,
) -> None:
    """Renseigne le résultat de Successive Rejects pour un candidat.

    sr_phase : numéro de phase d'élimination (1..K-1) ou None pour le winner.
    sr_eliminated : True si éliminé par SR.
    is_winner : True pour le top-1 retenu (sr_phase IS NULL et sr_eliminated=False).
    """
    conn.execute(
        """
        UPDATE rewrite_beam_candidates
        SET sr_phase = %s, sr_eliminated = %s, is_winner = %s
        WHERE id = %s
        """,
        (sr_phase, sr_eliminated, is_winner, candidate_row_id),
    )
    conn.commit()
