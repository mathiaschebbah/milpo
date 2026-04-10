"""Configuration de la pipeline agentique A0 — Haiku executor + Opus advisor."""

import os

from milpo.config import (
    DATABASE_DSN,
    MODEL_DESCRIPTOR_FEED,
    MODEL_DESCRIPTOR_REELS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)

# Anthropic API (direct, pas OpenRouter — requis pour l'advisor tool beta)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Executor : Haiku 4.5 (rapide, peu cher, multimodal)
MODEL_EXECUTOR = "claude-haiku-4-5-20251001"

# Advisor : Opus 4.6 (haute intelligence, appelé par Haiku quand il hésite)
MODEL_ADVISOR = "claude-opus-4-6"

# Descripteur : même modèle que la pipeline classique (Gemini 3 Flash Preview)
# Appelé via OpenRouter. Les deux constantes pointent vers le même modèle
# mais restent séparées pour cohérence avec milpo/config.py.
MODEL_DESCRIPTOR = MODEL_DESCRIPTOR_FEED

# Few-shot examples
DEFAULT_EXAMPLES = 3
MAX_EXAMPLES_PER_CALL = 5

# Agentic loop
MAX_TOOL_ROUNDS = 15  # safety: max de rounds tool-use par phase
MAX_TOKENS_PER_TURN = 4096
