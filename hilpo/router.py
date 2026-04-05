"""Routeur déterministe FEED/REELS basé sur media_product_type."""

from __future__ import annotations

from hilpo.config import (
    MODEL_DESCRIPTOR_FEED,
    MODEL_DESCRIPTOR_REELS,
)


SUPPORTED_SCOPES = ("FEED", "REELS")


def route(media_product_type: str) -> dict:
    """Retourne la config de routage pour un post.

    Returns:
        dict avec scope et model_descriptor.
    Raises:
        ValueError si le scope n'est pas supporté.
    """
    scope = media_product_type.upper()
    if scope not in SUPPORTED_SCOPES:
        raise ValueError(
            f"Scope '{scope}' non supporté. "
            f"Attendu : {SUPPORTED_SCOPES}"
        )

    model_map = {
        "FEED": MODEL_DESCRIPTOR_FEED,
        "REELS": MODEL_DESCRIPTOR_REELS,
    }

    return {
        "scope": scope,
        "model_descriptor": model_map[scope],
        "format_prefix": "post_" if scope == "FEED" else "reel_",
    }
