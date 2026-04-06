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
#
# Descripteurs : Gemini 3 Flash Preview pour FEED et REELS.
# Validation empirique (2026-04-06) :
#   - Carousels jusqu'à 20 images : ✓ (limite Instagram actuelle)
#   - Vidéos REELS via URL GCS : ✓
#   - Détection audio (voix_off_narrative) : ✓
#   - Concurrence (10 parallèles, 2 vagues) : 18/18 ✓
# Alternatives écartées :
#   - Qwen 3.5 Flash : limite carousel ~8 images, échec sur 10+ slides
#   - Gemini 2.5 Flash : réponses vides + 503 sous concurrence (Google AI Studio)
# Les 2 constantes restent séparées pour permettre une éventuelle re-différenciation
# future, mais elles pointent actuellement vers le même modèle.
MODEL_DESCRIPTOR_FEED = "google/gemini-3-flash-preview"
MODEL_DESCRIPTOR_REELS = "google/gemini-3-flash-preview"

# Classifieurs : Qwen 3.5 Flash text-only via tool calling forcé
# (cf. commit 0b3bd8b — fix après bug json_schema strict sur enums binaires).
MODEL_CLASSIFIER = "qwen/qwen3.5-flash-02-23"

MODEL_REWRITER = os.environ.get("HILPO_MODEL_REWRITER", "openai/gpt-5.4")

# GCS
GCS_SIGNING_SA_EMAIL = os.environ.get("HILPO_GCS_SIGNING_SA_EMAIL", "")

# BDD
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)
