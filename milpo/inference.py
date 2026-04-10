"""Pipeline d'inférence MILPO : router → descripteur → 3 classifieurs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from openai import OpenAI

from milpo.agent import call_classifier, call_descriptor
from milpo.client import get_client
from milpo.config import MODEL_CLASSIFIER
from milpo.inference_core import (
    build_classifier_specs,
    build_post_prediction,
    features_to_json,
)
from milpo.router import route
from milpo.schemas import PostPrediction


@dataclass
class PromptSet:
    """Ensemble de prompts pour un scope donné."""

    descriptor_instructions: str
    category_instructions: str
    visual_format_instructions: str
    strategy_instructions: str
    descriptor_descriptions: str
    category_descriptions: str
    visual_format_descriptions: str
    strategy_descriptions: str


@dataclass
class PostInput:
    """Données d'entrée pour classifier un post."""

    ig_media_id: int
    media_product_type: str
    media_urls: list[str]
    media_types: list[str]
    caption: str | None


@dataclass
class ApiCallLog:
    """Log d'un appel API pour traçabilité."""

    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class PipelineResult:
    """Résultat complet du pipeline pour un post."""

    prediction: PostPrediction
    api_calls: list[ApiCallLog] = field(default_factory=list)
    confidences: dict[str, str] = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.api_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.api_calls)

    @property
    def total_latency_ms(self) -> int:
        return sum(call.latency_ms for call in self.api_calls)


def classify_post(
    post: PostInput,
    prompts: PromptSet,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: OpenAI | None = None,
) -> PipelineResult:
    """Exécute le pipeline complet pour un post."""
    if client is None:
        client = get_client()

    api_calls: list[ApiCallLog] = []
    routing = route(post.media_product_type)
    features, desc_usage = call_descriptor(
        client=client,
        model=routing["model_descriptor"],
        media_urls=post.media_urls,
        media_types=post.media_types,
        caption=post.caption,
        instructions=prompts.descriptor_instructions,
        descriptions_taxonomiques=prompts.descriptor_descriptions,
    )
    api_calls.append(ApiCallLog(
        agent="descriptor",
        model=desc_usage["model"],
        input_tokens=desc_usage["input_tokens"],
        output_tokens=desc_usage["output_tokens"],
        latency_ms=desc_usage["latency_ms"],
    ))

    classifiers = build_classifier_specs(
        prompts,
        category_labels,
        visual_format_labels,
        strategy_labels,
    )
    features_json = features_to_json(features)
    results: dict[str, tuple[str, str]] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                call_classifier,
                client=client,
                model=MODEL_CLASSIFIER,
                axis=axis,
                labels=labels,
                features_json=features_json,
                caption=post.caption,
                instructions=instructions,
                descriptions_taxonomiques=descriptions,
            ): axis
            for axis, (labels, instructions, descriptions) in classifiers.items()
        }

        for future in as_completed(futures):
            axis = futures[future]
            label, confidence, clf_usage = future.result()
            results[axis] = (label, confidence)
            api_calls.append(ApiCallLog(
                agent=axis,
                model=clf_usage["model"],
                input_tokens=clf_usage["input_tokens"],
                output_tokens=clf_usage["output_tokens"],
                latency_ms=clf_usage["latency_ms"],
            ))

    prediction = build_post_prediction(
        ig_media_id=post.ig_media_id,
        features=features,
        labels_by_axis={axis: result[0] for axis, result in results.items()},
    )
    return PipelineResult(prediction=prediction, api_calls=api_calls)
