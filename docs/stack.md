# Stack technique

| Composant | Technologie |
|-----------|-------------|
| Backend | FastAPI (Python 3.12) |
| Frontend | Vite + React + TypeScript + Tailwind v4 + shadcn/ui |
| Base de données | PostgreSQL 17 (Docker, port 5433) |
| Modèle vision (classificateur + rewriter) | À confirmer (un seul modèle pour les deux) |
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

## Dépendances backend

FastAPI, SQLAlchemy (async), asyncpg, pydantic-settings, uvicorn, alembic
