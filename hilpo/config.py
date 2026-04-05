"""Configuration du moteur HILPO."""

import os

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Modèles par rôle et scope
MODEL_DESCRIPTOR_FEED = "qwen/qwen3.5-flash-02-23"
MODEL_DESCRIPTOR_REELS = "google/gemini-2.5-flash"
MODEL_CLASSIFIER = "qwen/qwen3.5-flash-02-23"

# BDD (même config que le backend)
DATABASE_DSN = os.environ.get(
    "HILPO_DATABASE_DSN",
    "postgresql://hilpo:hilpo@localhost:5433/hilpo",
)
