"""Pipeline end-to-end : un seul appel multimodal par post → 3 axes.

Mode `--e2e` : 1 appel par post, T=0. Utilisé pour l'ablation architecture
(comparaison avec la pipeline descripteur + 3 classifieurs).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from openai import AsyncOpenAI

from milpo.async_inference import get_async_client
from milpo.inference import ApiCallLog, PipelineResult, PostInput, PromptSet
from milpo.schemas import PostPrediction

log = logging.getLogger("milpo")

_E2E_SYSTEM_PROMPT = """\
Tu es un classificateur de posts Instagram pour le média Views (@viewsfrance).

Tu reçois les images du post (slides du carousel ou image unique) et la caption.
Tu dois classifier le post sur 3 axes indépendants en un seul appel.

## Formats visuels ({scope})

{vf_descriptions}

## Catégories

{cat_descriptions}

## Stratégies

{strat_descriptions}
"""


async def async_classify_post_e2e(
    client: AsyncOpenAI,
    model: str,
    post: PostInput,
    prompts: PromptSet,
    vf_labels: list[str],
    cat_labels: list[str],
    strat_labels: list[str],
    semaphore: asyncio.Semaphore,
) -> PipelineResult:
    scope = "FEED" if post.media_product_type == "FEED" else "REELS"

    system = _E2E_SYSTEM_PROMPT.format(
        scope=scope,
        vf_descriptions=prompts.visual_format_descriptions,
        cat_descriptions=prompts.category_descriptions,
        strat_descriptions=prompts.strategy_descriptions,
    )

    content: list[dict] = []
    for url, media_type in zip(post.media_urls, post.media_types):
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({
        "type": "text",
        "text": f"Caption du post :\n{post.caption or '(pas de caption)'}",
    })

    tool = {
        "type": "function",
        "function": {
            "name": "classify_post",
            "description": "Classifie le post sur les 3 axes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Raisonnement bref avant de décider.",
                    },
                    "visual_format": {"type": "string", "enum": vf_labels},
                    "category": {"type": "string", "enum": cat_labels},
                    "strategy": {"type": "string", "enum": strat_labels},
                },
                "required": ["reasoning", "visual_format", "category", "strategy"],
                "additionalProperties": False,
            },
        },
    }

    t0 = time.monotonic()
    async with semaphore:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "classify_post"}},
            temperature=0,
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    choice = response.choices[0]
    arguments_raw: str | None = None

    if choice.message.tool_calls:
        arguments_raw = choice.message.tool_calls[0].function.arguments
    else:
        txt = (choice.message.content or "").strip()
        code_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.DOTALL)
        if code_blocks:
            arguments_raw = code_blocks[-1]
        else:
            first_brace = txt.find("{")
            last_brace = txt.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                arguments_raw = txt[first_brace : last_brace + 1]

    if not arguments_raw:
        raise RuntimeError(f"E2E post {post.ig_media_id}: pas de réponse exploitable")

    parsed = json.loads(arguments_raw)
    vf_label = parsed.get("visual_format", vf_labels[0])
    cat_label = parsed.get("category", cat_labels[0])
    strat_label = parsed.get("strategy", strat_labels[0])

    in_tok = response.usage.prompt_tokens if response.usage else 0
    out_tok = response.usage.completion_tokens if response.usage else 0

    prediction = PostPrediction(
        ig_media_id=post.ig_media_id,
        category=cat_label,
        visual_format=vf_label,
        strategy=strat_label,
        features="[e2e — pas de features séparées]",
    )

    api_call = ApiCallLog(
        agent="e2e",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=latency_ms,
    )

    return PipelineResult(
        prediction=prediction,
        api_calls=[api_call],
        confidences={},
        reasonings={"e2e": parsed.get("reasoning", "")},
    )


async def async_classify_e2e_batch(
    posts: list[PostInput],
    prompts_by_scope: dict[str, PromptSet],
    labels_by_scope: dict[str, dict[str, list[str]]],
    model: str,
    max_concurrent: int = 10,
    on_progress=None,
) -> list[PipelineResult]:
    client = get_async_client()
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[PipelineResult | None] = [None] * len(posts)
    done_count = 0
    error_count = 0

    async def process(idx: int, post: PostInput):
        nonlocal done_count, error_count
        scope = "FEED" if post.media_product_type == "FEED" else "REELS"
        prompts = prompts_by_scope[scope]
        labels = labels_by_scope[scope]
        try:
            result = await async_classify_post_e2e(
                client=client,
                model=model,
                post=post,
                prompts=prompts,
                vf_labels=labels["visual_format"],
                cat_labels=labels["category"],
                strat_labels=labels["strategy"],
                semaphore=semaphore,
            )
            results[idx] = result
        except Exception as exc:
            log.warning("E2E post %s error: %s: %s", post.ig_media_id, type(exc).__name__, exc)
            error_count += 1
        done_count += 1
        if on_progress:
            on_progress(done_count, len(posts), error_count)

    await asyncio.gather(*(process(i, p) for i, p in enumerate(posts)))
    return [r for r in results if r is not None]
