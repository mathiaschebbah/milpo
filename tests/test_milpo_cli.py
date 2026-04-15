"""Tests de la CLI classification (parsing, dispatch, orchestration)."""

from __future__ import annotations

import argparse
import unittest
from unittest.mock import MagicMock, patch

from milpo.cli import (
    _models_config,
    _pick_dataset,
    _pick_mode,
    build_parser,
)


class ParserTests(unittest.TestCase):
    def test_mode_required(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--alpha"])  # pas de mode

    def test_dataset_required(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--alma"])  # pas de dataset

    def test_alma_alpha_ok(self) -> None:
        args = build_parser().parse_args(["--alma", "--alpha"])
        self.assertTrue(args.alma)
        self.assertFalse(args.simple)
        self.assertTrue(args.alpha)
        self.assertFalse(args.dev)
        self.assertFalse(args.test)

    def test_simple_test_ok(self) -> None:
        args = build_parser().parse_args(["--simple", "--test"])
        self.assertTrue(args.simple)
        self.assertTrue(args.test)

    def test_alma_dev_with_options(self) -> None:
        args = build_parser().parse_args(
            ["--alma", "--dev", "--limit", "20", "--no-persist"]
        )
        self.assertEqual(args.limit, 20)
        self.assertTrue(args.no_persist)
        self.assertIsNone(args.since)

    def test_alma_and_simple_are_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--alma", "--simple", "--dev"])

    def test_dev_test_alpha_are_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--alma", "--dev", "--test"])


class DispatchTests(unittest.TestCase):
    def test_pick_mode_alma(self) -> None:
        args = argparse.Namespace(alma=True, simple=False)
        self.assertEqual(_pick_mode(args), "alma")

    def test_pick_mode_simple(self) -> None:
        args = argparse.Namespace(alma=False, simple=True)
        self.assertEqual(_pick_mode(args), "simple")

    def test_pick_dataset(self) -> None:
        self.assertEqual(
            _pick_dataset(argparse.Namespace(dev=True, test=False, alpha=False)),
            "dev",
        )
        self.assertEqual(
            _pick_dataset(argparse.Namespace(dev=False, test=True, alpha=False)),
            "test",
        )
        self.assertEqual(
            _pick_dataset(argparse.Namespace(dev=False, test=False, alpha=True)),
            "alpha",
        )

    def test_models_config_alma_keys(self) -> None:
        config = _models_config("alma", None)
        self.assertIn("descriptor_feed", config)
        self.assertIn("classifier", config)
        self.assertIn("classifier_visual_format", config)

    def test_models_config_simple_keys(self) -> None:
        config = _models_config("simple", None)
        self.assertEqual(set(config), {"simple"})

    def test_tier_flash_lite_uses_flash_lite_everywhere(self) -> None:
        alma = _models_config("alma", "flash-lite")
        for value in alma.values():
            self.assertEqual(value, "gemini-3.1-flash-lite-preview")
        simple = _models_config("simple", "flash-lite")
        self.assertEqual(simple["simple"], "gemini-3.1-flash-lite-preview")

    def test_tier_flash_alma_only_swaps_visual_format(self) -> None:
        """Reproduit le design des runs 90-91 : flash uniquement sur visual_format."""
        alma = _models_config("alma", "flash")
        # descripteur reste flash-lite (cf. api_calls des runs 90-91)
        self.assertEqual(alma["descriptor_feed"], "gemini-3.1-flash-lite-preview")
        self.assertEqual(alma["descriptor_reels"], "gemini-3.1-flash-lite-preview")
        # category + strategy restent flash-lite
        self.assertEqual(alma["classifier"], "gemini-3.1-flash-lite-preview")
        # seul visual_format passe à flash
        self.assertEqual(alma["classifier_visual_format"], "gemini-3-flash-preview")

    def test_tier_flash_simple_uses_flash(self) -> None:
        """En tier flash, simple met l'unique appel sur flash."""
        simple = _models_config("simple", "flash")
        self.assertEqual(simple["simple"], "gemini-3-flash-preview")


class RunClassificationWiringTests(unittest.IsolatedAsyncioTestCase):
    """Smoke test du pipeline complet avec tous les helpers mockés."""

    @patch("milpo.cli.finish_run")
    @patch("milpo.cli.store_results")
    @patch("milpo.cli.async_classify_alma_batch")
    @patch("milpo.cli.build_labels")
    @patch("milpo.cli.sign_all_posts_media")
    @patch("milpo.cli.create_run")
    @patch("milpo.cli.get_conn")
    async def test_run_classification_alma_alpha_wires_helpers(
        self,
        mock_get_conn,
        mock_create_run,
        mock_sign_media,
        mock_build_labels,
        mock_alma_batch,
        mock_store_results,
        mock_finish_run,
    ) -> None:
        from milpo.cli import run_classification

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {
                "ig_media_id": 1,
                "caption": "caption",
                "media_type": "IMAGE",
                "media_product_type": "FEED",
                "posted_at": None,
                "gt_category": "news",
                "gt_visual_format": "post_news",
                "gt_strategy": "awareness",
            }
        ]
        mock_get_conn.return_value = conn
        mock_create_run.return_value = 42
        mock_sign_media.return_value = {1: [("https://example.com/img.jpg", "IMAGE")]}
        mock_build_labels.return_value = {
            "category": ["news"],
            "visual_format": ["post_news"],
            "strategy": ["awareness"],
        }
        fake_result = MagicMock()
        fake_result.prediction.ig_media_id = 1
        fake_result.api_calls = []
        mock_alma_batch.return_value = [fake_result]
        mock_store_results.return_value = (
            {"category": 1, "visual_format": 1, "strategy": 1},
            4,
        )

        run_id = await run_classification(
            argparse.Namespace(
                alma=True,
                simple=False,
                dev=False,
                test=False,
                alpha=True,
                limit=None,
                since=None,
                no_persist=False,
                model=None,
                post=None,
            )
        )

        self.assertEqual(run_id, 42)
        mock_create_run.assert_called_once()
        config_payload = mock_create_run.call_args[0][1]
        self.assertEqual(config_payload["pipeline_mode"], "alma")
        self.assertEqual(config_payload["dataset"], "alpha")
        mock_alma_batch.assert_called_once()
        mock_store_results.assert_called_once()
        mock_finish_run.assert_called_once()

    @patch("milpo.cli.async_classify_simple_batch")
    @patch("milpo.cli.build_labels")
    @patch("milpo.cli.sign_all_posts_media")
    @patch("milpo.cli.get_conn")
    async def test_run_classification_simple_with_no_persist(
        self,
        mock_get_conn,
        mock_sign_media,
        mock_build_labels,
        mock_simple_batch,
    ) -> None:
        from milpo.cli import run_classification

        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {
                "ig_media_id": 1,
                "caption": "caption",
                "media_type": "IMAGE",
                "media_product_type": "FEED",
                "posted_at": None,
                "gt_category": "news",
                "gt_visual_format": "post_news",
                "gt_strategy": "awareness",
            }
        ]
        mock_get_conn.return_value = conn
        mock_sign_media.return_value = {1: [("https://example.com/img.jpg", "IMAGE")]}
        mock_build_labels.return_value = {
            "category": ["news"],
            "visual_format": ["post_news"],
            "strategy": ["awareness"],
        }
        fake_result = MagicMock()
        fake_result.prediction.ig_media_id = 1
        fake_result.api_calls = []
        mock_simple_batch.return_value = [fake_result]

        run_id = await run_classification(
            argparse.Namespace(
                alma=False,
                simple=True,
                dev=False,
                test=True,
                alpha=False,
                limit=5,
                since=None,
                no_persist=True,
                model=None,
                post=None,
            )
        )

        self.assertEqual(run_id, 0)  # no_persist → pas de run_id
        mock_simple_batch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
