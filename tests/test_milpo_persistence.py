"""Tests pour milpo.persistence — cycle de vie runs + persistance classifications."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from milpo.inference import ApiCallLog, PipelineResult, PostInput
from milpo.persistence.classification import (
    persist_api_calls,
    persist_pipeline_predictions,
)
from milpo.persistence.runs import (
    create_run,
    fail_run,
    finish_extraction_run,
    finish_run,
    get_or_create_extraction_run,
)


def _features() -> str:
    return "Slide 1 : Photo plein cadre, titre editorial Views overlay, logo Views."


# ── persist_pipeline_predictions ───────────────────────────────


class PersistPredictionsTests(unittest.TestCase):
    def test_stores_three_axes_plus_descriptor(self) -> None:
        from milpo.schemas import PostPrediction

        features = _features()
        prediction = PostPrediction(
            ig_media_id=42,
            category="news",
            visual_format="post_news",
            strategy="awareness",
            features=features,
        )
        result = PipelineResult(prediction=prediction, api_calls=[])

        with unittest.mock.patch("milpo.persistence.classification.store_prediction") as mock_store:
            mock_store.return_value = 99
            persist_pipeline_predictions(
                MagicMock(),
                post_id=42,
                result=result,
                run_id=7,
                store_descriptor=True,
            )

        # 3 axes + 1 descriptor = 4 calls
        self.assertEqual(mock_store.call_count, 4)
        agents_stored = [c.args[2] for c in mock_store.call_args_list]
        self.assertIn("category", agents_stored[:3])
        self.assertIn("visual_format", agents_stored[:3])
        self.assertIn("strategy", agents_stored[:3])

    def test_skips_descriptor_when_disabled(self) -> None:
        from milpo.schemas import PostPrediction

        prediction = PostPrediction(
            ig_media_id=42,
            category="news",
            visual_format="post_news",
            strategy="awareness",
            features=_features(),
        )
        result = PipelineResult(prediction=prediction, api_calls=[])

        with unittest.mock.patch("milpo.persistence.classification.store_prediction") as mock_store:
            mock_store.return_value = 99
            persist_pipeline_predictions(
                MagicMock(),
                post_id=42,
                result=result,
                run_id=7,
                store_descriptor=False,
            )

        # 3 axes only, no descriptor
        self.assertEqual(mock_store.call_count, 3)


# ── persist_api_calls ──────────────────────────────────────────


class PersistApiCallsTests(unittest.TestCase):
    def test_stores_each_api_call(self) -> None:
        api_calls = [
            ApiCallLog("descriptor", "gemini", 100, 50, 200),
            ApiCallLog("category", "qwen", 10, 5, 30),
        ]

        with unittest.mock.patch("milpo.persistence.classification.store_api_call") as mock_store:
            mock_store.return_value = 1
            total = persist_api_calls(
                MagicMock(),
                post_id=42,
                api_calls=api_calls,
                run_id=7,
                call_type="classification",
            )

        self.assertEqual(total, 2)
        self.assertEqual(mock_store.call_count, 2)


# ── Run lifecycle ──────────────────────────────────────────────


class RunLifecycleTests(unittest.TestCase):
    def _mock_conn(self, returning: dict | None = None) -> MagicMock:
        conn = MagicMock()
        if returning:
            conn.execute.return_value.fetchone.return_value = returning
        return conn

    def test_create_run_inserts_and_returns_id(self) -> None:
        conn = self._mock_conn(returning={"id": 42})
        config = {"name": "test", "batch_size": 30}
        run_id = create_run(conn, config)
        self.assertEqual(run_id, 42)
        conn.commit.assert_called_once()

    def test_finish_run_sets_completed(self) -> None:
        conn = self._mock_conn()
        metrics = {
            "accuracy_category": 0.85,
            "accuracy_visual_format": 0.65,
            "accuracy_strategy": 0.94,
            "prompt_iterations": 3,
            "total_api_calls": 1200,
            "total_cost_usd": 2.50,
        }
        finish_run(conn, 42, metrics)
        conn.execute.assert_called_once()
        conn.commit.assert_called_once()
        sql = conn.execute.call_args[0][0]
        self.assertIn("completed", sql)

    def test_fail_run_sets_failed_with_reason(self) -> None:
        conn = self._mock_conn()
        metrics = {
            "accuracy_category": 0.50,
            "accuracy_visual_format": 0.30,
            "accuracy_strategy": 0.60,
            "prompt_iterations": 1,
            "total_api_calls": 400,
            "total_cost_usd": None,
        }
        fail_run(conn, 42, "timeout", metrics)
        conn.execute.assert_called_once()
        conn.commit.assert_called_once()
        sql = conn.execute.call_args[0][0]
        self.assertIn("failed", sql)

    def test_get_or_create_extraction_run_returns_existing(self) -> None:
        conn = self._mock_conn(returning={"id": 99})
        run_id = get_or_create_extraction_run(conn)
        self.assertEqual(run_id, 99)
        # Only one execute (the SELECT), no INSERT
        self.assertEqual(conn.execute.call_count, 1)

    def test_get_or_create_extraction_run_creates_when_absent(self) -> None:
        conn = MagicMock()
        # First SELECT returns None, second INSERT returns the new id
        conn.execute.return_value.fetchone.side_effect = [None, {"id": 100}]
        run_id = get_or_create_extraction_run(conn)
        self.assertEqual(run_id, 100)
        self.assertEqual(conn.execute.call_count, 2)

    def test_finish_extraction_run_updates_config(self) -> None:
        conn = self._mock_conn()
        finish_extraction_run(conn, 99, n_processed=50, n_skipped=10)
        conn.execute.assert_called_once()
        conn.commit.assert_called_once()
        params = conn.execute.call_args[0][1]
        payload = json.loads(params[0])
        self.assertEqual(payload["n_processed"], 50)
        self.assertEqual(payload["n_skipped_already_cached"], 10)


if __name__ == "__main__":
    unittest.main()
