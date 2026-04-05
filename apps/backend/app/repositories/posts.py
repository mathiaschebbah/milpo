from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_next_unannotated(self, annotator: str, exclude: list[int] | None = None) -> dict | None:
        exclude = exclude or []
        exclude_clause = ""
        params: dict = {"annotator": annotator}
        if exclude:
            placeholders = []
            for index, media_id in enumerate(exclude):
                key = f"exclude_{index}"
                placeholders.append(f":{key}")
                params[key] = media_id
            exclude_clause = f"AND p.ig_media_id NOT IN ({', '.join(placeholders)})"

        result = await self.db.execute(
            text(f"""
                SELECT
                    p.ig_media_id, p.shortcode, p.caption, p.timestamp,
                    p.media_type, p.media_product_type,
                    sp.split,
                    h.category_id, c.name AS heuristic_category,
                    h.visual_format_id, vf.name AS heuristic_visual_format,
                    h.strategy AS heuristic_strategy,
                    h.subcategory AS heuristic_subcategory
                FROM sample_posts sp
                JOIN posts p ON p.ig_media_id = sp.ig_media_id
                LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
                LEFT JOIN categories c ON c.id = h.category_id
                LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
                LEFT JOIN annotations a
                    ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
                WHERE a.id IS NULL {exclude_clause}
                ORDER BY sp.split DESC,
                    CASE WHEN vf.name IN (
                        'post_news', 'post_quote', 'post_chiffre',
                        'reel_news', 'reel_chiffre'
                    ) THEN 0 ELSE 1 END,
                    sp.presentation_order
                LIMIT 1
            """),
            params,
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def find_next_doubtful(self, annotator: str, exclude: list[int] | None = None) -> dict | None:
        exclude = exclude or []
        exclude_clause = ""
        params: dict = {"annotator": annotator}
        if exclude:
            placeholders = []
            for index, media_id in enumerate(exclude):
                key = f"exclude_{index}"
                placeholders.append(f":{key}")
                params[key] = media_id
            exclude_clause = f"AND p.ig_media_id NOT IN ({', '.join(placeholders)})"

        result = await self.db.execute(
            text(f"""
                SELECT
                    p.ig_media_id, p.shortcode, p.caption, p.timestamp,
                    p.media_type, p.media_product_type,
                    sp.split,
                    h.category_id, c.name AS heuristic_category,
                    h.visual_format_id, vf.name AS heuristic_visual_format,
                    h.strategy AS heuristic_strategy,
                    h.subcategory AS heuristic_subcategory,
                    a.category_id AS ann_category_id,
                    a.visual_format_id AS ann_visual_format_id,
                    a.strategy AS ann_strategy,
                    a.doubtful AS ann_doubtful
                FROM sample_posts sp
                JOIN posts p ON p.ig_media_id = sp.ig_media_id
                LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
                LEFT JOIN categories c ON c.id = h.category_id
                LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
                JOIN annotations a
                    ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
                WHERE a.doubtful = true {exclude_clause}
                ORDER BY sp.split DESC, sp.presentation_order
                LIMIT 1
            """),
            params,
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def find_post_by_id(self, ig_media_id: int, annotator: str) -> dict | None:
        result = await self.db.execute(
            text("""
                SELECT
                    p.ig_media_id, p.shortcode, p.caption, p.timestamp,
                    p.media_type, p.media_product_type,
                    sp.split,
                    h.category_id, c.name AS heuristic_category,
                    h.visual_format_id, vf.name AS heuristic_visual_format,
                    h.strategy AS heuristic_strategy,
                    h.subcategory AS heuristic_subcategory,
                    a.category_id AS ann_category_id,
                    a.visual_format_id AS ann_visual_format_id,
                    a.strategy AS ann_strategy,
                    a.doubtful AS ann_doubtful
                FROM sample_posts sp
                JOIN posts p ON p.ig_media_id = sp.ig_media_id
                LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
                LEFT JOIN categories c ON c.id = h.category_id
                LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
                LEFT JOIN annotations a
                    ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
                WHERE p.ig_media_id = :ig_media_id
            """),
            {"ig_media_id": ig_media_id, "annotator": annotator},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def find_media_by_post(self, ig_media_id: int) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT media_url, thumbnail_url, media_type,
                       media_order, width, height
                FROM post_media
                WHERE parent_ig_media_id = :post_id
                ORDER BY media_order
            """),
            {"post_id": ig_media_id},
        )
        return [dict(r) for r in result.mappings().all()]

    async def count_progress(self, annotator: str) -> dict:
        result = await self.db.execute(
            text("""
                SELECT
                    COUNT(sp.ig_media_id) AS total,
                    COUNT(a.id) AS annotated
                FROM sample_posts sp
                LEFT JOIN annotations a
                    ON a.ig_media_id = sp.ig_media_id AND a.annotator = :annotator
            """),
            {"annotator": annotator},
        )
        return dict(result.mappings().first())

    async def find_all_sample_posts(
        self, annotator: str, offset: int = 0, limit: int = 50,
        status: str | None = None, category: str | None = None,
        split: str | None = None, visual_format: str | None = None,
    ) -> tuple[list[dict], int]:
        where_clauses = []
        params: dict = {"annotator": annotator, "offset": offset, "limit": limit}

        if status == "annotated":
            where_clauses.append("a.id IS NOT NULL")
        elif status == "pending":
            where_clauses.append("a.id IS NULL")
        elif status == "doubtful":
            where_clauses.append("a.doubtful = true")

        if category:
            where_clauses.append("c.name = :category")
            params["category"] = category

        if split:
            where_clauses.append("sp.split::text = :split")
            params["split"] = split

        if visual_format:
            where_clauses.append("COALESCE(avf.name, vf.name) = :visual_format")
            params["visual_format"] = visual_format

        where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

        result = await self.db.execute(
            text(f"""
                SELECT
                    p.ig_media_id, p.shortcode, p.media_type, p.media_product_type,
                    sp.split,
                    c.name AS category, vf.name AS visual_format,
                    h.strategy,
                    ac.name AS annotation_category,
                    avf.name AS annotation_visual_format,
                    a.strategy AS annotation_strategy,
                    a.doubtful AS annotation_doubtful,
                    a.id AS annotation_id,
                    (SELECT COALESCE(pm.thumbnail_url, pm.media_url) FROM post_media pm
                     WHERE pm.parent_ig_media_id = p.ig_media_id
                     ORDER BY pm.media_order LIMIT 1) AS thumbnail_url,
                    COUNT(*) OVER () AS total_count
                FROM sample_posts sp
                JOIN posts p ON p.ig_media_id = sp.ig_media_id
                LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
                LEFT JOIN categories c ON c.id = h.category_id
                LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
                LEFT JOIN annotations a
                    ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
                LEFT JOIN categories ac ON ac.id = a.category_id
                LEFT JOIN visual_formats avf ON avf.id = a.visual_format_id
                WHERE 1=1 {where_sql}
                ORDER BY sp.split DESC, a.id IS NOT NULL DESC, p.timestamp DESC
                OFFSET :offset LIMIT :limit
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]
        total = rows[0]["total_count"] if rows else 0
        return rows, total

    async def find_all_categories(self) -> list[dict]:
        result = await self.db.execute(
            text("SELECT id, name FROM categories ORDER BY name")
        )
        return [dict(r) for r in result.mappings().all()]

    async def find_all_visual_formats(self) -> list[dict]:
        result = await self.db.execute(
            text("SELECT id, name FROM visual_formats ORDER BY name")
        )
        return [dict(r) for r in result.mappings().all()]
