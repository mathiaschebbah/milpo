from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.repositories.taxonomy import TaxonomyRepository
from app.schemas.taxonomy import DescriptionUpdate, TaxonomyItemOut
from app.services.taxonomy import TaxonomyService

router = APIRouter(prefix="/v1/taxonomy", tags=["taxonomy"])


def get_service(db: AsyncSession = Depends(get_db)) -> TaxonomyService:
    return TaxonomyService(TaxonomyRepository(db))


@router.get("/visual-formats", response_model=list[TaxonomyItemOut])
async def list_visual_formats(service: TaxonomyService = Depends(get_service)):
    return await service.get_visual_formats()


@router.get("/categories", response_model=list[TaxonomyItemOut])
async def list_categories(service: TaxonomyService = Depends(get_service)):
    return await service.get_categories()


@router.get("/strategies", response_model=list[TaxonomyItemOut])
async def list_strategies(service: TaxonomyService = Depends(get_service)):
    return await service.get_strategies()


@router.patch("/{axis}/{item_id}", response_model=TaxonomyItemOut)
async def update_description(
    axis: str,
    item_id: int,
    data: DescriptionUpdate,
    service: TaxonomyService = Depends(get_service),
):
    return await service.update_description(axis, item_id, data.description)
