"""Helpers purs partagés par les pipelines d'inférence."""

from __future__ import annotations

from milpo.schemas import PostPrediction


def build_classifier_specs(
    prompts,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
) -> dict[str, tuple[list[str], str, str]]:
    return {
        "category": (
            category_labels,
            prompts.category_instructions,
            prompts.category_descriptions,
        ),
        "visual_format": (
            visual_format_labels,
            prompts.visual_format_instructions,
            prompts.visual_format_descriptions,
        ),
        "strategy": (
            strategy_labels,
            prompts.strategy_instructions,
            prompts.strategy_descriptions,
        ),
    }


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
