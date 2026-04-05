"""Client OpenRouter unifié (compatible OpenAI SDK)."""

from __future__ import annotations

from openai import OpenAI

from hilpo.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL


def get_client() -> OpenAI:
    """Retourne un client OpenAI pointant vers OpenRouter."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY non définie. "
            "Exporte-la dans ton environnement ou .env."
        )
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )
