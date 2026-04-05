"""Accès BDD pour le moteur HILPO (psycopg sync)."""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from hilpo.config import DATABASE_DSN


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


# ── Prompt versions ────────────────────────────────────────────


def get_active_prompt(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
) -> dict | None:
    """Retourne le prompt actif pour un agent × scope."""
    return conn.execute(
        """
        SELECT id, agent, scope, version, content
        FROM prompt_versions
        WHERE agent = %s
          AND (scope = %s OR (scope IS NULL AND %s IS NULL))
          AND status = 'active'
        """,
        (agent, scope, scope),
    ).fetchone()


def insert_prompt_version(
    conn: psycopg.Connection,
    agent: str,
    scope: str | None,
    version: int,
    content: str,
    status: str = "active",
    parent_id: int | None = None,
) -> int:
    """Insère une nouvelle version de prompt. Retourne l'id."""
    row = conn.execute(
        """
        INSERT INTO prompt_versions (agent, scope, version, content, status, parent_id)
        VALUES (%s, %s, %s, %s, %s::prompt_status, %s)
        RETURNING id
        """,
        (agent, scope, version, content, status, parent_id),
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
