from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(prefix="/annotations", tags=["annotations"])


class AnnotationCreate(BaseModel):
    ig_media_id: int
    category_id: int
    visual_format_id: int
    strategy: str  # "Organic" | "Brand Content"
    annotator: str = "mathias"


@router.post("/")
async def create_annotation(
    annotation: AnnotationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Enregistre une annotation humaine."""
    if annotation.strategy not in ("Organic", "Brand Content"):
        raise HTTPException(400, "strategy doit être 'Organic' ou 'Brand Content'")

    result = await db.execute(
        text("""
            INSERT INTO annotations (ig_media_id, category_id, visual_format_id, strategy, annotator)
            VALUES (:ig_media_id, :category_id, :visual_format_id, :strategy, :annotator)
            ON CONFLICT (ig_media_id, annotator) DO UPDATE SET
                category_id = EXCLUDED.category_id,
                visual_format_id = EXCLUDED.visual_format_id,
                strategy = EXCLUDED.strategy,
                created_at = NOW()
            RETURNING id
        """),
        annotation.model_dump(),
    )
    await db.commit()
    row = result.mappings().first()
    return {"id": row["id"]}
