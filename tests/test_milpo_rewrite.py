from __future__ import annotations

import unittest

from milpo.rewriter import ErrorCase
from milpo.simulation.rewrite import get_target_errors, pick_rewrite_target


def _error(
    *,
    ig_media_id: int,
    axis: str,
    prompt_scope: str | None,
    post_scope: str,
) -> ErrorCase:
    return ErrorCase(
        ig_media_id=ig_media_id,
        axis=axis,
        prompt_scope=prompt_scope,
        post_scope=post_scope,
        predicted="pred",
        expected="exp",
        features_json="{}",
        caption="caption",
        desc_predicted="pred desc",
        desc_expected="exp desc",
    )


class RewriteSelectionTests(unittest.TestCase):
    def test_pick_rewrite_target_prioritizes_descriptor_on_multi_axis_failures(self) -> None:
        errors = [
            _error(ig_media_id=1, axis="category", prompt_scope=None, post_scope="FEED"),
            _error(ig_media_id=1, axis="strategy", prompt_scope=None, post_scope="FEED"),
        ]

        self.assertEqual(pick_rewrite_target(errors), ("descriptor", "FEED"))

    def test_get_target_errors_filters_non_descriptor_by_axis_and_scope(self) -> None:
        errors = [
            _error(ig_media_id=1, axis="visual_format", prompt_scope="FEED", post_scope="FEED"),
            _error(ig_media_id=2, axis="visual_format", prompt_scope="REELS", post_scope="REELS"),
            _error(ig_media_id=3, axis="category", prompt_scope=None, post_scope="FEED"),
        ]

        filtered = get_target_errors(errors, "visual_format", "FEED")

        self.assertEqual([error.ig_media_id for error in filtered], [1])

    def test_get_target_errors_returns_all_scope_errors_for_descriptor(self) -> None:
        """Le descripteur reçoit toutes les erreurs du scope ciblé."""
        errors = [
            _error(ig_media_id=7, axis="category", prompt_scope=None, post_scope="REELS"),
            _error(ig_media_id=7, axis="strategy", prompt_scope=None, post_scope="REELS"),
            _error(ig_media_id=8, axis="category", prompt_scope=None, post_scope="REELS"),
            _error(ig_media_id=9, axis="visual_format", prompt_scope="FEED", post_scope="FEED"),
        ]

        filtered = get_target_errors(errors, "descriptor", "REELS")

        # Seules les erreurs REELS sont retournées (ig_media_id 7, 7, 8)
        self.assertEqual([error.ig_media_id for error in filtered], [7, 7, 8])
        # FEED errors excluded
        self.assertNotIn(9, [e.ig_media_id for e in filtered])


if __name__ == "__main__":
    unittest.main()
