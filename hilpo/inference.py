"""Pipeline d'inférence HILPO : router → descripteur → 3 classifieurs."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from openai import OpenAI

from hilpo.agent import call_classifier, call_descriptor
from hilpo.client import get_client
from hilpo.config import MODEL_CLASSIFIER
from hilpo.router import route
from hilpo.schemas import DescriptorFeatures, PostPrediction


@dataclass
class PromptSet:
    """Ensemble de prompts pour un scope donné."""

    descriptor_instructions: str
    category_instructions: str
    visual_format_instructions: str
    strategy_instructions: str
    descriptor_descriptions: str  # Δ^m descripteur (critères discriminants)
    category_descriptions: str    # Δ^m catégories (15 descriptions)
    visual_format_descriptions: str  # Δ^m formats visuels scopés
    strategy_descriptions: str    # Δ^m stratégies (2 descriptions)


@dataclass
class PostInput:
    """Données d'entrée pour classifier un post."""

    ig_media_id: int
    media_product_type: str  # FEED ou REELS
    media_urls: list[str]    # URLs signées GCS
    media_types: list[str]   # IMAGE ou VIDEO pour chaque média
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

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.api_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.api_calls)

    @property
    def total_latency_ms(self) -> int:
        return sum(c.latency_ms for c in self.api_calls)


def classify_post(
    post: PostInput,
    prompts: PromptSet,
    category_labels: list[str],
    visual_format_labels: list[str],
    strategy_labels: list[str],
    client: OpenAI | None = None,
) -> PipelineResult:
    """Exécute le pipeline complet pour un post.

    1. Routage déterministe
    2. Descripteur multimodal (1 appel)
    3. 3 classifieurs text-only en parallèle
    """
    if client is None:
        client = get_client()

    api_calls: list[ApiCallLog] = []

    # ── 1. Routage ──
    routing = route(post.media_product_type)

    # ── 2. Descripteur multimodal ──
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

    features_json = features.model_dump_json(indent=2)

    # ── 3. Classifieurs text-only en parallèle ──
    classifiers = {
        "category": (category_labels, prompts.category_instructions, prompts.category_descriptions),
        "visual_format": (visual_format_labels, prompts.visual_format_instructions, prompts.visual_format_descriptions),
        "strategy": (strategy_labels, prompts.strategy_instructions, prompts.strategy_descriptions),
    }

    results: dict[str, tuple[str, str]] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for axis, (labels, instructions, descriptions) in classifiers.items():
            future = pool.submit(
                call_classifier,
                client=client,
                model=MODEL_CLASSIFIER,
                axis=axis,
                labels=labels,
                features_json=features_json,
                caption=post.caption,
                instructions=instructions,
                descriptions_taxonomiques=descriptions,
            )
            futures[future] = axis

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

    # ── Assemblage ──
    prediction = PostPrediction(
        ig_media_id=post.ig_media_id,
        category=results["category"][0],
        visual_format=results["visual_format"][0],
        strategy=results["strategy"][0],
        features=features,
    )

    return PipelineResult(prediction=prediction, api_calls=api_calls)
