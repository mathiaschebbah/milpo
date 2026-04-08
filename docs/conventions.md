# Conventions

## Collaboration

- **AskUserQuestion intensif** : utiliser AskUserQuestion pour valider les choix, clarifier les ambiguïtés et confirmer les directions avant d'agir. Ne pas deviner, demander.
- **Français avec accents** : tout contenu en français (README, docs, commentaires, messages de commit) doit utiliser les accents corrects (é, è, à, ù, etc.). Toujours relire avant d'écrire un fichier.
- **Interdiction formelle** d'écrire dans [`docs/human_perspective.md`](docs/human_perspective.md)

> **Note sur l'enforcement** : ces trois règles sont des **directives en langage naturel** rappelées à l'agent par le hook `check-claude-md.py` après chaque commit, **pas des guards techniques**. Aucun script ne bloque l'écriture si elles sont violées — c'est une convention de comportement qui dépend de la rigueur de l'agent et du contrôle de l'humain en review.

## API REST

- Endpoints versionnés sous `/v1/`
- POST retourne `201 Created` + header `Location`
- Exceptions custom + handler global (pas de try/catch dans les routers)
- `ig_media_id` sérialisé en **string** partout (JSON perd la précision sur les BIGINT > 2^53)
- Proxy Vite (`/v1` → `127.0.0.1:8000`) — élimine les problèmes CORS en dev
- Skip : exclusion multiple (liste d'IDs skippés en session, pas juste le post courant)

## Typographie frontend

- Pas de `font-mono` sur les labels UI — mono réservé aux données numériques (compteurs, pourcentages)
- Taille minimum `text-[11px]` pour les métadonnées, `text-xs` (12px) pour les labels, `text-sm` (14px) pour les contrôles
- Pas de `uppercase tracking-wider` sur les labels de formulaire
- `max-w-prose` sur les blocs de texte (caption)
- `tabular-nums` uniquement sur les données numériques alignées

## Skills

- **`/setup`** ([`.claude/skills/setup/SKILL.md`](../.claude/skills/setup/SKILL.md)) : initialise le contexte en début de session — lit CLAUDE.md, phases, git log, vérifie les services, présente un résumé.

## Hooks PostToolUse

Les hooks sont **non bloquants** (PostToolUse) : ils envoient un rappel à l'agent après le commit, sans bloquer l'action.

- **`check-claude-md.py`** : après chaque `git commit`, rappelle à l'agent de vérifier si CLAUDE.md et les fichiers `docs/` doivent être mis à jour. L'agent propose via AskUserQuestion, puis fait un commit séparé `docs: update CLAUDE.md` si l'humain valide.
- **`agent-perspective.py`** : tous les 10 commits, rappelle à l'agent de mettre à jour `docs/agent_perspective.md` avec un snapshot daté de son état de compréhension du projet (décisions récentes, dynamiques de collaboration). Sert la dimension 2 du mémoire (collaboration humain-agent).
