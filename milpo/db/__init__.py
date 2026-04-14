"""Façade de compatibilité pour l'accès BDD MILPO."""

from __future__ import annotations

from .base import get_conn
from .posts import load_dev_annotations, load_dev_posts, load_post_media, load_posts_media
from .prompts import (
    get_active_prompt,
    get_prompt_version,
    insert_prompt_version,
    promote_prompt,
)
from .runs import store_api_call, store_prediction
from .taxonomy import (
    format_descriptions,
    load_categories,
    load_strategies,
    load_visual_formats,
)

__all__ = [
    "format_descriptions",
    "get_active_prompt",
    "get_conn",
    "get_prompt_version",
    "insert_prompt_version",
    "load_categories",
    "load_dev_annotations",
    "load_dev_posts",
    "load_post_media",
    "load_posts_media",
    "load_strategies",
    "load_visual_formats",
    "promote_prompt",
    "store_api_call",
    "store_prediction",
]
