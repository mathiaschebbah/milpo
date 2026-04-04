from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TaxonomyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_all_visual_formats(self) -> list[dict]:
        result = await self.db.execute(
            text("SELECT id, name, description FROM visual_formats ORDER BY name")
        )
        return [dict(r) for r in result.mappings().all()]

    async def find_all_categories(self) -> list[dict]:
        result = await self.db.execute(
            text("SELECT id, name, description FROM categories ORDER BY name")
        )
        return [dict(r) for r in result.mappings().all()]

    async def find_all_strategies(self) -> list[dict]:
        result = await self.db.execute(
            text("SELECT id, name::text AS name, description FROM strategies ORDER BY id")
        )
        return [dict(r) for r in result.mappings().all()]

    async def update_visual_format_description(self, item_id: int, description: str | None) -> dict | None:
        result = await self.db.execute(
            text("""
                UPDATE visual_formats SET description = :description
                WHERE id = :id
                RETURNING id, name, description
            """),
            {"id": item_id, "description": description},
        )
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def update_category_description(self, item_id: int, description: str | None) -> dict | None:
        result = await self.db.execute(
            text("""
                UPDATE categories SET description = :description
                WHERE id = :id
                RETURNING id, name, description
            """),
            {"id": item_id, "description": description},
        )
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def update_strategy_description(self, item_id: int, description: str | None) -> dict | None:
        result = await self.db.execute(
            text("""
                UPDATE strategies SET description = :description
                WHERE id = :id
                RETURNING id, name::text AS name, description
            """),
            {"id": item_id, "description": description},
        )
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None
