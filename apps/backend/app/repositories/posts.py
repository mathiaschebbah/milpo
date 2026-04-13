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
                ORDER BY sp.split DESC, sp.presentation_order
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
                FROM posts p
                LEFT JOIN sample_posts sp ON sp.ig_media_id = p.ig_media_id
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
        year: int | None = None, eval_set: str | None = None,
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

        if split and not eval_set:
            where_clauses.append("sp.split::text = :split")
            params["split"] = split

        if visual_format:
            where_clauses.append("COALESCE(avf.name, vf.name) = :visual_format")
            params["visual_format"] = visual_format

        if year is not None:
            where_clauses.append("EXTRACT(YEAR FROM p.timestamp)::int = :year")
            params["year"] = year

        if eval_set:
            from_sql = "FROM eval_sets es JOIN posts p ON p.ig_media_id = es.ig_media_id"
            where_clauses.insert(0, "es.set_name = :eval_set")
            params["eval_set"] = eval_set
            split_col = "NULL AS split"
            order_sql = "ORDER BY a.id IS NOT NULL DESC, p.timestamp DESC"
        else:
            from_sql = "FROM sample_posts sp JOIN posts p ON p.ig_media_id = sp.ig_media_id"
            split_col = "sp.split"
            order_sql = "ORDER BY sp.split DESC, a.id IS NOT NULL DESC, p.timestamp DESC"

        where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

        result = await self.db.execute(
            text(f"""
                SELECT
                    p.ig_media_id, p.shortcode, p.caption, p.timestamp,
                    p.media_type, p.media_product_type,
                    {split_col},
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
                {from_sql}
                LEFT JOIN heuristic_labels h ON h.ig_media_id = p.ig_media_id
                LEFT JOIN categories c ON c.id = h.category_id
                LEFT JOIN visual_formats vf ON vf.id = h.visual_format_id
                LEFT JOIN annotations a
                    ON a.ig_media_id = p.ig_media_id AND a.annotator = :annotator
                LEFT JOIN categories ac ON ac.id = a.category_id
                LEFT JOIN visual_formats avf ON avf.id = a.visual_format_id
                WHERE 1=1 {where_sql}
                {order_sql}
                OFFSET :offset LIMIT :limit
            """),
            params,
        )
        rows = [dict(r) for r in result.mappings().all()]
        total = rows[0]["total_count"] if rows else 0
        return rows, total

    async def find_eval_set_stats(self, set_name: str, annotator: str) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT
                    avf.name AS format_name,
                    p.media_product_type AS scope,
                    COUNT(*) AS total,
                    COUNT(a.id) AS annotated
                FROM eval_sets es
                JOIN posts p ON p.ig_media_id = es.ig_media_id
                JOIN annotations a ON a.ig_media_id = es.ig_media_id AND a.annotator = :annotator
                JOIN visual_formats avf ON avf.id = a.visual_format_id
                WHERE es.set_name = :set_name
                GROUP BY avf.name, p.media_product_type
                ORDER BY p.media_product_type, avf.name
            """),
            {"set_name": set_name, "annotator": annotator},
        )
        return [dict(r) for r in result.mappings().all()]

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

    async def find_all_years(self) -> list[int]:
        """Retourne les années distinctes présentes dans le sample, tri décroissant."""
        result = await self.db.execute(
            text("""
                SELECT DISTINCT EXTRACT(YEAR FROM p.timestamp)::int AS year
                FROM sample_posts sp
                JOIN posts p ON p.ig_media_id = sp.ig_media_id
                WHERE p.timestamp IS NOT NULL
                ORDER BY year DESC
            """)
        )
        return [r["year"] for r in result.mappings().all()]
