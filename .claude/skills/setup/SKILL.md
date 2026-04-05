---
name: setup
description: >
  Initialise le contexte du projet HILPO en début de conversation. Lit l'état du projet (CLAUDE.md, phases, stack), l'historique git récent, vérifie les services (Postgres, backend, frontend), et présente un résumé. Utiliser en début de chaque session.
---

# Setup — Initialisation du contexte HILPO

Au lancement de cette commande, exécute les étapes suivantes pour te mettre à jour sur l'état du projet.

## Étape 1 — Lire l'état du projet

Lis les fichiers suivants (en parallèle) :

1. `CLAUDE.md` — index versionné + changelog
2. Tous les fichiers du dossier docs/
3. Analyse le codebase entièrement avec 5 sub-agents pour résumer là ou on en est.

## Étape 2 — Historique git récent

Lance `git log --oneline -15` pour voir les derniers commits et comprendre où on en est.

## Étape 3 — État du working tree

Lance `git status` pour voir s'il y a du travail en cours non commité.

## Étape 4 — Vérifier les services

Vérifie si Docker Postgres et les serveurs (backend/frontend) tournent :
- `docker compose ps` (Postgres)
- `lsof -ti :8000` (backend FastAPI)
- `lsof -ti :5173` (frontend Vite)

## Étape 5 — Synthèse

Présente un résumé concis à l'utilisateur :

```
HILPO — État du projet
======================
Version CLAUDE.md : vX.Y
Dernier commit    : <message>
Phase active      : <phase et statut>
Services          : Postgres ✓/✗ | Backend ✓/✗ | Frontend ✓/✗
Working tree      : clean / N fichiers modifiés

Direction : <prochaine étape logique basée sur les phases>
```

Puis demande : "On continue sur quoi ?"
