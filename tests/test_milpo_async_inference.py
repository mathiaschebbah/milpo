from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from milpo.async_inference import async_classify_post, async_classify_with_features
from milpo.inference import ApiCallLog, PostInput, PromptSet


def _features() -> str:
    return "Slide 1 : Photo plein cadre, titre editorial Views overlay, logo Views en haut à gauche, gabarit reconnaissable."


def _prompt_set() -> PromptSet:
    return PromptSet(
        descriptor_instructions="describe",
        category_instructions="category",
        visual_format_instructions="vf",
        strategy_instructions="strategy",
        descriptor_descriptions="desc",
        category_descriptions="cat desc",
        visual_format_descriptions="vf desc",
        strategy_descriptions="str desc",
    )


def _post() -> PostInput:
    return PostInput(
        ig_media_id=1,
        media_product_type="FEED",
        media_urls=["https://example.com/img.jpg"],
        media_types=["IMAGE"],
        caption="caption",
    )


class AsyncInferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_classify_with_features_uses_precomputed_features(self) -> None:
        desc_log = ApiCallLog("descriptor", "gemini", 10, 2, 20)
        classifier_logs = [
            ("news", "high", "reason", ApiCallLog("category", "qwen", 1, 1, 1)),
            ("post_news", "high", "reason", ApiCallLog("visual_format", "qwen", 1, 1, 1)),
            ("awareness", "medium", "reason", ApiCallLog("strategy", "qwen", 1, 1, 1)),
        ]

        with patch("milpo.async_inference.async_call_classifier", new=AsyncMock(side_effect=classifier_logs)):
            result = await async_classify_with_features(
                post=_post(),
                features=_features(),
                desc_log=desc_log,
                prompts=_prompt_set(),
                category_labels=["news"],
                visual_format_labels=["post_news"],
                strategy_labels=["awareness"],
                client=object(),
                semaphore=asyncio.Semaphore(4),
            )

        self.assertEqual(result.prediction.category, "news")
        self.assertEqual(result.prediction.visual_format, "post_news")
        self.assertEqual(result.prediction.strategy, "awareness")
        self.assertEqual(len(result.api_calls), 4)

    async def test_async_classify_post_calls_descriptor_then_shared_classifier_core(self) -> None:
        with patch(
            "milpo.async_inference.async_call_descriptor",
            new=AsyncMock(return_value=(_features(), ApiCallLog("descriptor", "gemini", 3, 1, 5))),
        ), patch(
            "milpo.async_inference.async_call_classifier",
            new=AsyncMock(side_effect=[
                ("news", "high", "reason", ApiCallLog("category", "qwen", 1, 1, 1)),
                ("post_news", "high", "reason", ApiCallLog("visual_format", "qwen", 1, 1, 1)),
                ("awareness", "low", "reason", ApiCallLog("strategy", "qwen", 1, 1, 1)),
            ]),
        ):
            result = await async_classify_post(
                post=_post(),
                prompts=_prompt_set(),
                category_labels=["news"],
                visual_format_labels=["post_news"],
                strategy_labels=["awareness"],
                client=object(),
                semaphore=asyncio.Semaphore(4),
            )

        self.assertEqual(result.prediction.ig_media_id, 1)
        self.assertEqual(result.prediction.strategy, "awareness")


if __name__ == "__main__":
    unittest.main()
