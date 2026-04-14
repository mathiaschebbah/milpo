from __future__ import annotations

import argparse
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from milpo.inference import PostInput


class BaselineWorkflowTests(unittest.IsolatedAsyncioTestCase):
    @patch("milpo.workflows.baseline.finish_run")
    @patch("milpo.workflows.baseline.store_results")
    @patch("milpo.workflows.baseline.async_classify_batch")
    @patch("milpo.workflows.baseline.build_labels")
    @patch("milpo.workflows.baseline.build_prompt_set")
    @patch("milpo.workflows.baseline.load_prompt_bundle")
    @patch("milpo.workflows.baseline.sign_all_posts_media")
    @patch("milpo.workflows.baseline.create_run")
    @patch("milpo.workflows.baseline.get_conn")
    async def test_run_baseline_wires_shared_helpers(
        self,
        mock_get_conn,
        mock_create_run,
        mock_sign_media,
        mock_load_prompt_bundle,
        mock_build_prompt_set,
        mock_build_labels,
        mock_async_classify_batch,
        mock_store_results,
        mock_finish_run,
    ) -> None:
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [{
            "ig_media_id": 1,
            "caption": "caption",
            "media_type": "IMAGE",
            "media_product_type": "FEED",
        }]
        mock_get_conn.return_value = conn
        mock_create_run.return_value = 11
        mock_sign_media.return_value = {1: [("https://example.com/img.jpg", "IMAGE")]}
        mock_load_prompt_bundle.return_value = (
            {
                ("descriptor", "FEED"): {"content": "desc"},
                ("descriptor", "REELS"): {"content": "desc-r"},
                ("category", None): {"content": "cat"},
                ("visual_format", "FEED"): {"content": "vf"},
                ("visual_format", "REELS"): {"content": "vf-r"},
                ("strategy", None): {"content": "str"},
            },
            {("descriptor", "FEED"): 1},
        )
        mock_build_prompt_set.return_value = MagicMock()
        mock_build_labels.return_value = {
            "category": ["news"],
            "visual_format": ["post_news"],
            "strategy": ["awareness"],
        }
        fake_result = MagicMock()
        fake_result.prediction.ig_media_id = 1
        fake_result.api_calls = []
        mock_async_classify_batch.return_value = [fake_result]
        mock_store_results.return_value = ({"category": 1, "visual_format": 1, "strategy": 1}, 4)

        from milpo.workflows.baseline import run_baseline

        run_id = await run_baseline(argparse.Namespace(
            prompts="v0",
            split="test",
            since=None,
            eval_set=None,
            e2e=False,
        ))

        self.assertEqual(run_id, 11)
        mock_build_prompt_set.assert_called()
        mock_build_labels.assert_called()
        mock_store_results.assert_called_once()
        mock_finish_run.assert_called_once()


class FeatureCacheWorkflowTests(unittest.IsolatedAsyncioTestCase):
    @patch("milpo.workflows.feature_cache.finish_extraction_run")
    @patch("milpo.workflows.feature_cache.load_annotated_dev_posts_without_features")
    @patch("milpo.workflows.feature_cache.get_or_create_extraction_run")
    @patch("milpo.workflows.feature_cache.get_conn")
    async def test_run_feature_cache_short_circuits_when_nothing_to_do(
        self,
        mock_get_conn,
        mock_get_or_create_extraction_run,
        mock_load_posts,
        mock_finish_extraction_run,
    ) -> None:
        mock_get_conn.return_value = MagicMock()
        mock_get_or_create_extraction_run.return_value = 21
        mock_load_posts.return_value = []

        from milpo.workflows.feature_cache import run_feature_cache

        run_id = await run_feature_cache(
            argparse.Namespace(limit=None, force=False, max_concurrent_api=20)
        )

        self.assertEqual(run_id, 21)
        mock_finish_extraction_run.assert_called_once_with(mock_get_conn.return_value, 21, n_processed=0, n_skipped=0)


if __name__ == "__main__":
    unittest.main()
