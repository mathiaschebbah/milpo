from app.exceptions import AllAnnotatedError
from app.gcs import sign_gcs_url, sign_urls_batch
from app.repositories.posts import PostRepository
from app.schemas.posts import (
    AnnotationValues,
    HeuristicLabels,
    LookupOut,
    MediaOut,
    NextPostOut,
    PostGridItem,
    PostGridPage,
    PostOut,
    ProgressOut,
)


class PostService:
    def __init__(self, repository: PostRepository):
        self.repository = repository

    async def get_next_post(self, annotator: str, exclude: list[int] | None = None, mode: str = "next") -> NextPostOut:
        if mode == "doubtful":
            row = await self.repository.find_next_doubtful(annotator, exclude)
        else:
            row = await self.repository.find_next_unannotated(annotator, exclude)
        if not row:
            raise AllAnnotatedError(annotator)

        media_rows = await self.repository.find_media_by_post(row["ig_media_id"])

        return self._build_next_post_out(row, media_rows)

    async def get_post_by_id(self, ig_media_id: int, annotator: str) -> NextPostOut:
        row = await self.repository.find_post_by_id(ig_media_id, annotator)
        if not row:
            from app.exceptions import NotFoundError
            raise NotFoundError("Post", ig_media_id)

        media_rows = await self.repository.find_media_by_post(row["ig_media_id"])
        return self._build_next_post_out(row, media_rows)

    def _build_next_post_out(self, row: dict, media_rows: list[dict]) -> NextPostOut:
        annotation = None
        if row.get("ann_category_id") is not None:
            annotation = AnnotationValues(
                category_id=row["ann_category_id"],
                visual_format_id=row["ann_visual_format_id"],
                strategy=row["ann_strategy"],
                doubtful=row.get("ann_doubtful", False),
            )

        return NextPostOut(
            post=PostOut(
                ig_media_id=str(row["ig_media_id"]),
                shortcode=row["shortcode"],
                caption=row["caption"],
                timestamp=row["timestamp"],
                media_type=row["media_type"],
                media_product_type=row["media_product_type"],
                split=row.get("split"),
            ),
            heuristic=HeuristicLabels(
                category_id=row["category_id"],
                heuristic_category=row["heuristic_category"],
                visual_format_id=row["visual_format_id"],
                heuristic_visual_format=row["heuristic_visual_format"],
                heuristic_strategy=row["heuristic_strategy"],
                heuristic_subcategory=row.get("heuristic_subcategory"),
            ),
            media=[
                MediaOut(
                    **{**m, "media_url": sign_gcs_url(m.get("media_url")),
                       "thumbnail_url": sign_gcs_url(m.get("thumbnail_url"))}
                )
                for m in media_rows
            ],
            annotation=annotation,
        )

    async def get_progress(self, annotator: str) -> ProgressOut:
        row = await self.repository.count_progress(annotator)
        return ProgressOut(**row)

    async def get_grid(
        self, annotator: str, offset: int, limit: int,
        status: str | None, category: str | None, split: str | None = None,
        visual_format: str | None = None,
    ) -> PostGridPage:
        rows, total = await self.repository.find_all_sample_posts(
            annotator, offset, limit, status, category, split, visual_format,
        )

        # Signer toutes les thumbnails en parallèle (au lieu de séquentiellement)
        all_urls = [r["thumbnail_url"] for r in rows]
        signed_map = await sign_urls_batch(all_urls)

        items = [
            PostGridItem(
                ig_media_id=str(r["ig_media_id"]),
                shortcode=r["shortcode"],
                media_type=r["media_type"],
                media_product_type=r["media_product_type"],
                split=r.get("split"),
                thumbnail_url=signed_map.get(r["thumbnail_url"], r["thumbnail_url"]),
                category=r["category"],
                visual_format=r["visual_format"],
                strategy=r["strategy"],
                annotation_category=r["annotation_category"],
                annotation_visual_format=r["annotation_visual_format"],
                annotation_strategy=r["annotation_strategy"],
                annotation_doubtful=r.get("annotation_doubtful") or False,
                is_annotated=r["annotation_id"] is not None,
            )
            for r in rows
        ]
        return PostGridPage(items=items, total=total, offset=offset, limit=limit)

    async def get_categories(self) -> list[LookupOut]:
        rows = await self.repository.find_all_categories()
        return [LookupOut(**r) for r in rows]

    async def get_visual_formats(self) -> list[LookupOut]:
        rows = await self.repository.find_all_visual_formats()
        return [LookupOut(**r) for r in rows]
