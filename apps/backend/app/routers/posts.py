from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("/next")
async def get_next_post(
    annotator: str = "mathias",
    db: AsyncSession = Depends(get_db),
):
    """Retourne le prochain post à annoter (non encore annoté par cet annotateur)."""
    result = await db.execute(
        text("""
            SELECT
                p.ig_media_id,
                p.shortcode,
                p.caption,
                p.timestamp,
                p.media_type,
                p.media_product_type,
                h.category_id,
                c.name AS heuristic_category,
                h.visual_format_id,
                vf.name AS heuristic_visual_format,
                h.strategy AS heuristic_strategy,
                h.subcategory AS heuristic_subcategory
            FROM sample_posts sp
            JOIN posts p ON p.ig_media_id = sp.ig_media_id
            LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
            LEFT JOIN categories c ON c.id = h.category_id
            LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
            LEFT JOIN annotations a ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
            WHERE a.id IS NULL
            ORDER BY RANDOM()
            LIMIT 1
        """),
        {"annotator": annotator},
    )
    row = result.mappings().first()
    if not row:
        return {"done": True, "message": "Tous les posts sont annotés"}

    # Récupérer les médias du post
    media_result = await db.execute(
        text("""
            SELECT media_url, thumbnail_url, media_type, media_order, width, height
            FROM post_media
            WHERE parent_ig_media_id = :post_id
            ORDER BY media_order
        """),
        {"post_id": row["ig_media_id"]},
    )
    media = [dict(m) for m in media_result.mappings().all()]

    return {"post": dict(row), "media": media}


@router.get("/progress")
async def get_progress(
    annotator: str = "mathias",
    db: AsyncSession = Depends(get_db),
):
    """Retourne la progression de l'annotation."""
    result = await db.execute(
        text("""
            SELECT
                COUNT(sp.ig_media_id) AS total,
                COUNT(a.id) AS annotated
            FROM sample_posts sp
            LEFT JOIN annotations a ON a.ig_media_id = sp.ig_media_id AND a.annotator = :annotator
        """),
        {"annotator": annotator},
    )
    row = result.mappings().first()
    return dict(row)


@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """Liste toutes les catégories."""
    result = await db.execute(text("SELECT id, name FROM categories ORDER BY name"))
    return [dict(r) for r in result.mappings().all()]


@router.get("/visual-formats")
async def get_visual_formats(db: AsyncSession = Depends(get_db)):
    """Liste tous les formats visuels."""
    result = await db.execute(text("SELECT id, name FROM visual_formats ORDER BY name"))
    return [dict(r) for r in result.mappings().all()]
