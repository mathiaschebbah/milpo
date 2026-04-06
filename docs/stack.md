# Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | FastAPI (Python 3.12) |
| Frontend | Vite + React + TypeScript + Tailwind v4 + shadcn/ui |
| Base de données | PostgreSQL 17 (Docker, port 5433) |
| Descripteur FEED | Gemini 3 Flash Preview via OpenRouter ($0.50/M in, $3.00/M out — image + vidéo + texte, jusqu'à 20 slides) |
| Descripteur REELS | Gemini 3 Flash Preview via OpenRouter ($0.50/M in, $3.00/M out — image + vidéo + audio + texte, détection voix off) |
| Classifieurs (×3) | Qwen 3.5 Flash via OpenRouter ($0.065/M — texte seul, tool calling forcé) |
| Rewriter (Phase 3) | OpenAI GPT-5.4 via OpenRouter |
| API unifiée | OpenRouter (`/api/v1/chat/completions`, compatible OpenAI SDK) |
| Gestion des dépendances | uv |
| Déploiement | Local (localhost) |

## Architecture backend

```
app/
├── routers/       ← couche HTTP (thin), endpoints /v1/
├── services/      ← logique métier
├── repositories/  ← accès données (SQL)
├── schemas/       ← DTOs Pydantic (request/response)
└── exceptions.py  ← handler global + exceptions custom
```

## Médias GCS

Les images/vidéos sont stockées sur Google Cloud Storage (bucket privé). Le backend signe les URLs à la volée via V4 Signed URLs (IAM Sign Blob). Configuration via `.env` (gitignored) : `HILPO_GCS_SIGN_URLS`, `HILPO_GCS_SIGNING_SA_EMAIL`. Dev local : `gcloud auth application-default login`.

## Dépendances backend

FastAPI, SQLAlchemy (async), asyncpg, pydantic-settings, uvicorn, alembic, google-cloud-storage, google-auth

## Dépendances package hilpo/ (pyproject.toml racine)

openai (SDK compatible OpenRouter), pydantic, psycopg[binary], google-cloud-storage, google-auth, python-dotenv. Optionnel (eval) : scikit-learn, numpy.
