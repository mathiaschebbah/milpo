"""Configuration de la pipeline agentique A0/A1."""

import os

from milpo.config import MODEL_DESCRIPTOR_FEED

# Anthropic API (direct, pas OpenRouter — requis pour l'advisor tool beta)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Executor : Haiku 4.5 (rapide, peu cher, multimodal)
MODEL_EXECUTOR = os.environ.get("AGENT_EXECUTOR_MODEL", "claude-sonnet-4-6")

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
MAX_BOUNDED_AGENT_ROUNDS = int(os.environ.get("AGENT_BOUNDED_MAX_ROUNDS", "2"))
MAX_TOKENS_BOUNDED_TURN = int(os.environ.get("AGENT_BOUNDED_MAX_TOKENS", "300"))

# Advisor
ADVISOR_MAX_USES = 2          # max appels advisor par phase (requête)
ADVISOR_CACHE_TTL = os.environ.get("AGENT_ADVISOR_CACHE_TTL", "1h")
BOUNDED_ADVISOR_MAX_USES = int(os.environ.get("AGENT_BOUNDED_ADVISOR_MAX_USES", "1"))
BOUNDED_EXAMPLE_CALLS_MAX = int(os.environ.get("AGENT_BOUNDED_EXAMPLE_CALLS_MAX", "1"))
BOUNDED_EXAMPLES_PER_CALL_MAX = int(os.environ.get("AGENT_BOUNDED_EXAMPLES_PER_CALL_MAX", "2"))

# Rate limits Anthropic (modifiable via env si le tier change)
RATE_LIMIT_INPUT_TOKENS_PER_MINUTE = int(os.environ.get("AGENT_RATE_LIMIT_INPUT_TPM", "50000"))
RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.environ.get("AGENT_RATE_LIMIT_RPM", "200"))
RATE_LIMIT_OUTPUT_TOKENS_PER_MINUTE = int(os.environ.get("AGENT_RATE_LIMIT_OUTPUT_TPM", "0"))
RATE_LIMIT_WARMUP_CONCURRENCY = int(os.environ.get("AGENT_RATE_LIMIT_WARMUP_CONCURRENCY", "4"))
