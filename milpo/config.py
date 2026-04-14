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
