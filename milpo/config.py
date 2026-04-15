"""Configuration du moteur MILPO — charge .env automatiquement."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Cherche .env à la racine du projet, puis dans apps/backend/
_project_root = Path(__file__).resolve().parent.parent
for _env_path in [_project_root / ".env", _project_root / "apps" / "backend" / ".env"]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break

# LLM Provider — Google AI direct (Gemini) ou OpenRouter (fallback)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

if GOOGLE_API_KEY:
    LLM_API_KEY = GOOGLE_API_KEY
    LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
else:
    LLM_API_KEY = OPENROUTER_API_KEY
    LLM_BASE_URL = "https://openrouter.ai/api/v1"

# Modèles — tout sur Gemini 3.1 Flash Lite par défaut
MODEL_DESCRIPTOR_FEED = os.environ.get("MILPO_MODEL_DESCRIPTOR", "gemini-3.1-flash-lite-preview")
MODEL_DESCRIPTOR_REELS = os.environ.get("MILPO_MODEL_DESCRIPTOR", "gemini-3.1-flash-lite-preview")
MODEL_CLASSIFIER = os.environ.get("MILPO_MODEL_CLASSIFIER", "gemini-3.1-flash-lite-preview")

# Override ciblé : axe le plus difficile (42 classes long-tail, règles
# subtiles). Permet d'utiliser un modèle plus capable uniquement pour
# visual_format tout en gardant Flash Lite pour category et strategy.
# Si non défini, fallback sur MODEL_CLASSIFIER.
MODEL_CLASSIFIER_VISUAL_FORMAT = os.environ.get(
    "MILPO_MODEL_CLASSIFIER_VISUAL_FORMAT", MODEL_CLASSIFIER
)

# Mode --simple : un seul appel multimodal ASSIST (images + caption + 3
# taxonomies + questions ASSIST → 3 labels). Fallback sur l'override
# visual_format parce que c'est le modèle qui doit encaisser l'axe le plus
# difficile en plus des images.
MODEL_SIMPLE = os.environ.get("MILPO_MODEL_SIMPLE", MODEL_CLASSIFIER_VISUAL_FORMAT)


# Prix par modèle en $/M tokens (input, output) — tier Standard, text/image/video.
# Sources : https://ai.google.dev/gemini-api/docs/pricing (Gemini 3 family)
# + Anthropic pricing. À mettre à jour si les providers changent leurs tarifs.
MODEL_PRICES_USD_PER_M: dict[str, tuple[float, float]] = {
    # Gemini 3 family (Standard tier)
    "gemini-3.1-flash-lite-preview": (0.25, 1.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.1-flash": (0.50, 3.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),       # prompts ≤ 200k tokens
    # Gemini 2.5 (older)
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    # Anthropic (pour oracle cascade éventuel)
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Retourne le coût USD d'un appel LLM, ou None si prix inconnu pour le modèle."""
    price = MODEL_PRICES_USD_PER_M.get(model)
    if price is None:
        return None
    in_price, out_price = price
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000

# Conservée uniquement parce que `related_work/dspy_baseline/optimize.py`
# l'utilise pour son proposer model (et pour sa task LM OpenAI-compatible).
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# GCS
GCS_SIGNING_SA_EMAIL = os.environ.get("HILPO_GCS_SIGNING_SA_EMAIL", "")

# BDD
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)
