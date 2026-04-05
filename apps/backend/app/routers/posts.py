from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.repositories.posts import PostRepository
from app.schemas.posts import LookupOut, NextPostOut, PostGridPage, ProgressOut
from app.services.posts import PostService

router = APIRouter(prefix="/v1/posts", tags=["posts"])


def get_service(db: AsyncSession = Depends(get_db)) -> PostService:
    return PostService(PostRepository(db))


@router.get("/", response_model=PostGridPage)
async def list_posts(
    annotator: str = "mathias",
    offset: int = 0,
    limit: int = 50,
    status: str | None = None,
    category: str | None = None,
    split: str | None = None,
    visual_format: str | None = None,
    service: PostService = Depends(get_service),
):
    return await service.get_grid(annotator, offset, limit, status, category, split, visual_format)


@router.get("/next", response_model=NextPostOut)
async def get_next_post(
    annotator: str = "mathias",
    exclude: list[int] = Query(default_factory=list),
    mode: str = "next",
    service: PostService = Depends(get_service),
):
    return await service.get_next_post(annotator, exclude, mode)


@router.get("/progress", response_model=ProgressOut)
async def get_progress(
    annotator: str = "mathias",
    service: PostService = Depends(get_service),
):
    return await service.get_progress(annotator)


@router.get("/categories", response_model=list[LookupOut])
async def get_categories(service: PostService = Depends(get_service)):
    return await service.get_categories()


@router.get("/visual-formats", response_model=list[LookupOut])
async def get_visual_formats(service: PostService = Depends(get_service)):
    return await service.get_visual_formats()


@router.get("/{ig_media_id}", response_model=NextPostOut)
async def get_post(
    ig_media_id: int,
    annotator: str = "mathias",
    service: PostService = Depends(get_service),
):
    return await service.get_post_by_id(ig_media_id, annotator)
