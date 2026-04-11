"""Accès aux posts, médias et annotations."""

from __future__ import annotations

import psycopg


def load_dev_posts(
    conn: psycopg.Connection,
    limit: int | None = None,
    offset: int = 0,
    split: str = "dev",
) -> list[dict]:
    """Charge les posts d'un split dans l'ordre de présentation."""
    query = """
        SELECT
            p.ig_media_id,
            p.caption,
            p.media_type::text AS media_type,
            p.media_product_type::text AS media_product_type,
            p.timestamp AS posted_at,
            sp.presentation_order
        FROM sample_posts sp
        JOIN posts p ON p.ig_media_id = sp.ig_media_id
        WHERE sp.split = %s
        ORDER BY sp.presentation_order
    """
    params: list = [split]
    if limit:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
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


def load_dev_annotations(conn: psycopg.Connection, split: str = "dev") -> dict[int, dict]:
    """Charge les annotations d'un split. Retourne {ig_media_id: {category, visual_format, strategy}}."""
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
        WHERE sp.split = %s
        ORDER BY sp.presentation_order
        """,
        (split,),
    ).fetchall()
    return {
        row["ig_media_id"]: {
            "category": row["category"],
            "visual_format": row["visual_format"],
            "strategy": row["strategy"],
        }
        for row in rows
    }
