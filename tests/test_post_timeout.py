"""Tests TDD pour le timeout granulaire par post (best effort).

Principe : si un post timeout ou crash, on le skip et on continue.
Le batch ne doit jamais être annulé en entier.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from milpo.async_inference import async_classify_batch
from milpo.inference import ApiCallLog, PostInput, PromptSet


def _prompt_set() -> PromptSet:
    return PromptSet(
        descriptor_instructions="d", category_instructions="c",
        visual_format_instructions="v", strategy_instructions="s",
        descriptor_descriptions="dd", category_descriptions="cd",
        visual_format_descriptions="vd", strategy_descriptions="sd",
    )


def _post(ig_media_id: int = 1) -> PostInput:
    return PostInput(
        ig_media_id=ig_media_id, media_product_type="FEED",
        media_urls=["https://example.com/img.jpg"],
        media_types=["IMAGE"], caption="caption",
    )


def _make_classify_post_mock(slow_ids: set[int], delay: float = 10.0):
    """Create a mock that hangs for posts in slow_ids, returns instantly for others."""
    async def _mock(post, prompts, category_labels, visual_format_labels,
                    strategy_labels, client, semaphore):
        if post.ig_media_id in slow_ids:
            await asyncio.sleep(delay)
        from milpo.schemas import DescriptorFeatures, PostPrediction
        features = DescriptorFeatures.model_validate({
            "resume_visuel": "r", "texte_overlay": {"present": False, "type": None,
            "contenu_resume": None, "chiffre_dominant": False},
            "logos": {"views": True, "specifique": None, "marque_partenaire": None,
            "gabarit_views_identifie": False},
            "mise_en_page": {"fond": "couleur_unie", "nombre_slides": 1,
            "structure": "slide_unique", "carousel_nature": "non_carousel"},
            "contenu_principal": {"personnes_visibles": False, "type_personne": None,
            "screenshots_film": False, "pochettes_album": False, "zoom_objet": False,
            "photos_evenement": False, "chiffre_marquant_visible": False},
            "audio_video": {"voix_off_narrative": False, "interview_face_camera": False,
            "interview_setting": None, "musique_dominante": False, "type_montage": None,
            "montage_recap_evenement": False},
            "analyse_caption": {"longueur": 5, "mentions_marques": [],
            "hashtags_format": None, "mention_partenariat": False, "sujet_resume": "t"},
            "indices_brand_content": {"produit_mis_en_avant": False,
            "mention_partenariat_caption": False, "logo_marque_commerciale": False},
            "elements_discriminants": [],
        })
        from milpo.inference import PipelineResult
        pred = PostPrediction(ig_media_id=post.ig_media_id, category="news",
                              visual_format="post_news", strategy="awareness",
                              features=features)
        return PipelineResult(prediction=pred, api_calls=[
            ApiCallLog("descriptor", "gemini", 100, 1000, 100),
        ])
    return _mock


class PostTimeoutTests(unittest.IsolatedAsyncioTestCase):
    """async_classify_batch doit supporter un per_post_timeout."""

    async def test_fast_posts_returned_when_one_post_hangs(self) -> None:
        """Si 1 post sur 3 hang, les 2 autres doivent quand même revenir."""
        posts = [_post(1), _post(2), _post(3)]
        mock = _make_classify_post_mock(slow_ids={2}, delay=100)

        with patch("milpo.async_inference.async_classify_post", new=mock):
            results = await async_classify_batch(
                posts=posts,
                prompts_by_scope={"FEED": _prompt_set()},
                labels_by_scope={"FEED": {"category": ["news"], "visual_format": ["post_news"], "strategy": ["awareness"]}},
                per_post_timeout=1.0,
            )

        returned_ids = {r.prediction.ig_media_id for r in results}
        self.assertIn(1, returned_ids)
        self.assertIn(3, returned_ids)
        self.assertNotIn(2, returned_ids)

    async def test_all_posts_returned_when_none_hang(self) -> None:
        """Sans timeout, tous les posts reviennent."""
        posts = [_post(1), _post(2), _post(3)]
        mock = _make_classify_post_mock(slow_ids=set())

        with patch("milpo.async_inference.async_classify_post", new=mock):
            results = await async_classify_batch(
                posts=posts,
                prompts_by_scope={"FEED": _prompt_set()},
                labels_by_scope={"FEED": {"category": ["news"], "visual_format": ["post_news"], "strategy": ["awareness"]}},
                per_post_timeout=5.0,
            )

        self.assertEqual(len(results), 3)

    async def test_on_progress_called_for_timed_out_posts(self) -> None:
        """Le callback on_progress doit compter les posts timeout comme errors."""
        posts = [_post(1), _post(2)]
        mock = _make_classify_post_mock(slow_ids={2}, delay=100)
        progress_calls: list[tuple[int, int, int]] = []

        def on_progress(done, total, errors):
            progress_calls.append((done, total, errors))

        with patch("milpo.async_inference.async_classify_post", new=mock):
            await async_classify_batch(
                posts=posts,
                prompts_by_scope={"FEED": _prompt_set()},
                labels_by_scope={"FEED": {"category": ["news"], "visual_format": ["post_news"], "strategy": ["awareness"]}},
                per_post_timeout=0.5,
                on_progress=on_progress,
            )

        # Both posts should have triggered on_progress (done=2)
        final = progress_calls[-1]
        self.assertEqual(final[0], 2)  # done
        self.assertEqual(final[2], 1)  # errors (the timed out one)

    async def test_exception_in_one_post_does_not_kill_others(self) -> None:
        """Un crash dans un post ne doit pas affecter les autres."""
        posts = [_post(1), _post(2), _post(3)]
        call_count = 0

        async def _mock(post, prompts, category_labels, visual_format_labels,
                        strategy_labels, client, semaphore):
            nonlocal call_count
            call_count += 1
            if post.ig_media_id == 2:
                raise RuntimeError("API exploded")
            return await _make_classify_post_mock(set())(
                post, prompts, category_labels, visual_format_labels,
                strategy_labels, client, semaphore,
            )

        with patch("milpo.async_inference.async_classify_post", new=_mock):
            results = await async_classify_batch(
                posts=posts,
                prompts_by_scope={"FEED": _prompt_set()},
                labels_by_scope={"FEED": {"category": ["news"], "visual_format": ["post_news"], "strategy": ["awareness"]}},
                per_post_timeout=5.0,
            )

        returned_ids = {r.prediction.ig_media_id for r in results}
        self.assertIn(1, returned_ids)
        self.assertNotIn(2, returned_ids)
        self.assertIn(3, returned_ids)


if __name__ == "__main__":
    unittest.main()
