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

# Modèles — tout sur Gemini 2.5 Flash Lite
MODEL_DESCRIPTOR_FEED = os.environ.get("MILPO_MODEL_DESCRIPTOR", "gemini-3.1-flash-lite-preview")
MODEL_DESCRIPTOR_REELS = os.environ.get("MILPO_MODEL_DESCRIPTOR", "gemini-3.1-flash-lite-preview")
MODEL_CLASSIFIER = os.environ.get("MILPO_MODEL_CLASSIFIER", "gemini-3.1-flash-lite-preview")

MODEL_REWRITER = os.environ.get("HILPO_MODEL_REWRITER", "gpt-5.4")

# Le rewriter utilise l'API OpenAI directe
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REWRITER_API_KEY = OPENAI_API_KEY
REWRITER_BASE_URL = "https://api.openai.com/v1"

# Modèles pour la boucle ProTeGi (mode --mode protegi).
# Par défaut tous = MODEL_REWRITER pour isoler l'effet de la décomposition
# algorithmique (critic / editor / paraphraser séparés) de l'effet d'un mélange
# de modèles. Surchargeable via env vars pour ablations.
MODEL_CRITIC = os.environ.get("HILPO_MODEL_CRITIC", MODEL_REWRITER)
MODEL_EDITOR = os.environ.get("HILPO_MODEL_EDITOR", MODEL_REWRITER)
MODEL_PARAPHRASER = os.environ.get("HILPO_MODEL_PARAPHRASER", MODEL_REWRITER)

# Oracle cascade — Claude Sonnet 4.6 appelé sur les prédictions classifieur
# avec confidence synthétique medium/low (vote self-consistency <k/k).
# Désactivé automatiquement si ANTHROPIC_API_KEY n'est pas set.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL_ORACLE = os.environ.get("MILPO_MODEL_ORACLE", "claude-sonnet-4-6")
ORACLE_ENABLED = bool(ANTHROPIC_API_KEY)

# GCS
GCS_SIGNING_SA_EMAIL = os.environ.get("HILPO_GCS_SIGNING_SA_EMAIL", "")

# BDD
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)
