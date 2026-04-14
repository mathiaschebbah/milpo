"""Client LLM unifié — Google AI direct ou OpenRouter (compatible OpenAI SDK)."""

from __future__ import annotations

from openai import OpenAI

from milpo.config import LLM_API_KEY, LLM_BASE_URL


def get_client() -> OpenAI:
    """Retourne un client OpenAI pointant vers le provider configuré."""
    if not LLM_API_KEY:
        raise RuntimeError(
            "Aucune clé API configurée. "
            "Définir GOOGLE_API_KEY ou OPENROUTER_API_KEY dans .env."
        )
    return OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=20.0,
    )
