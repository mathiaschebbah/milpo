"""Helpers purs partagés par les pipelines d'inférence."""

from __future__ import annotations

from milpo.schemas import PostPrediction


def build_post_prediction(
    *,
    ig_media_id: int,
    features: str,
    labels_by_axis: dict[str, str],
) -> PostPrediction:
    return PostPrediction(
        ig_media_id=ig_media_id,
        category=labels_by_axis["category"],
        visual_format=labels_by_axis["visual_format"],
        strategy=labels_by_axis["strategy"],
        features=features,
    )
