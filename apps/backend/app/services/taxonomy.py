from app.exceptions import NotFoundError
from app.repositories.taxonomy import TaxonomyRepository
from app.schemas.taxonomy import TaxonomyItemOut


class TaxonomyService:
    def __init__(self, repository: TaxonomyRepository):
        self.repository = repository

    async def get_visual_formats(self) -> list[TaxonomyItemOut]:
        rows = await self.repository.find_all_visual_formats()
        return [TaxonomyItemOut(**r) for r in rows]

    async def get_categories(self) -> list[TaxonomyItemOut]:
        rows = await self.repository.find_all_categories()
        return [TaxonomyItemOut(**r) for r in rows]

    async def get_strategies(self) -> list[TaxonomyItemOut]:
        rows = await self.repository.find_all_strategies()
        return [TaxonomyItemOut(**r) for r in rows]

    async def update_description(self, axis: str, item_id: int, description: str | None) -> TaxonomyItemOut:
        updaters = {
            "visual-formats": self.repository.update_visual_format_description,
            "categories": self.repository.update_category_description,
            "strategies": self.repository.update_strategy_description,
        }
        updater = updaters.get(axis)
        if not updater:
            raise NotFoundError("axe", axis)
        row = await updater(item_id, description)
        if not row:
            raise NotFoundError(axis, item_id)
        return TaxonomyItemOut(**row)
