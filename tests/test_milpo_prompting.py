from __future__ import annotations

import unittest
from unittest.mock import patch

from milpo.inference import PromptSet
from milpo.prompting import build_prompt_set, load_prompt_bundle


class PromptingTests(unittest.TestCase):
    @patch("milpo.prompting.catalog.load_prompt_record")
    def test_load_prompt_bundle_falls_back_to_v0_for_descriptor_in_dspy(self, mock_load_prompt_record) -> None:
        calls: list[tuple[str, str | None, str]] = []

        def _fake_loader(conn, agent: str, scope: str | None, mode: str):
            calls.append((agent, scope, mode))
            return {"id": len(calls), "content": f"{agent}:{scope}:{mode}", "version": 0}

        mock_load_prompt_record.side_effect = _fake_loader

        records, prompt_ids = load_prompt_bundle(conn=object(), prompt_mode="dspy_constrained")

        self.assertEqual(records[("descriptor", "FEED")]["content"], "descriptor:FEED:v0")
        self.assertEqual(records[("descriptor", "REELS")]["content"], "descriptor:REELS:v0")
        self.assertEqual(records[("category", None)]["content"], "category:None:dspy_constrained")
        self.assertEqual(prompt_ids[("strategy", None)], 6)

    @patch("milpo.prompting.catalog.render_taxonomy_for_scope")
    def test_build_prompt_set_uses_shared_prompt_contents(
        self,
        mock_render_taxonomy_for_scope,
    ) -> None:
        mock_render_taxonomy_for_scope.side_effect = lambda scope: {
            "FEED": "CLASS: post_news",
            "CATEGORY": "CLASS: news",
            "STRATEGY": "CLASS: awareness",
        }[scope]

        prompts = build_prompt_set(
            conn=object(),
            scope="FEED",
            prompt_contents={
                ("descriptor", "FEED"): "descriptor",
                ("category", None): "category",
                ("visual_format", "FEED"): "vf",
                ("strategy", None): "strategy",
            },
        )

        self.assertIsInstance(prompts, PromptSet)
        self.assertEqual(prompts.descriptor_instructions, "descriptor")
        self.assertIn("post_news", prompts.descriptor_descriptions)
        self.assertIn("news", prompts.category_descriptions)
        self.assertIn("awareness", prompts.strategy_descriptions)


if __name__ == "__main__":
    unittest.main()
