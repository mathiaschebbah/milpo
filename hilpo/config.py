"""Configuration du moteur HILPO — charge .env automatiquement."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Cherche .env à la racine du projet, puis dans apps/backend/
_project_root = Path(__file__).resolve().parent.parent
for _env_path in [_project_root / ".env", _project_root / "apps" / "backend" / ".env"]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break

# OpenRouter
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modèles
MODEL_DESCRIPTOR_FEED = "qwen/qwen3.5-flash-02-23"
MODEL_DESCRIPTOR_REELS = "google/gemini-2.5-flash"
MODEL_CLASSIFIER = "qwen/qwen3.5-flash-02-23"
MODEL_REWRITER = os.environ.get("HILPO_MODEL_REWRITER", "openai/gpt-5.4")

# GCS
GCS_SIGNING_SA_EMAIL = os.environ.get("HILPO_GCS_SIGNING_SA_EMAIL", "")

# BDD
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)
