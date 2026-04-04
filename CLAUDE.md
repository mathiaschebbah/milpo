# HILPO — Human-In-the-Loop Prompt Optimization

> Version **1.9** — 2026-04-04

## Double dimension du projet

1. **Recherche HILPO** : peut-on classifier des données multimodales sans gros dataset, en optimisant itérativement un prompt via une boucle humain-dans-la-boucle ?
2. **Collaboration Agent-Humain** : le projet lui-même est construit via une collaboration structurée entre Claude Code et l'humain. Les hooks (validation CLAUDE.md, AskUserQuestion) incarnent le paradigme humain-dans-la-boucle au niveau du développement. La progression est traçable dans l'historique git.

## Index

- [Projet](docs/project.md) — contexte, problematique, hypothese, contraintes
- [Stack](docs/stack.md) — technologies et choix techniques
- [Architecture](docs/architecture.md) — agents, pipeline, flux de donnees
- [Schema BDD](docs/schema.md) — tables, relations, contraintes
- [Donnees](docs/data.md) — structure des CSV, axes de classification, taxonomie
- [Phases](docs/phases.md) — phases de dev et avancement
- [Evaluation](docs/evaluation.md) — protocole experimental, metriques, baselines, ablations
- [Conventions](docs/conventions.md) — règles de collaboration et standards

## Monorepo

```
hilpo/                 ← repo root
├── hilpo/             ← package Python (engine HILPO)
├── apps/
│   ├── frontend/      ← React (interface de swipe)
│   └── backend/       ← FastAPI (API)
├── scripts/           ← Import CSV, simulations, figures
├── docs/              ← Documentation versionnée
├── data/              ← Données brutes (gitignored)
├── CLAUDE.md          ← Index versionné
└── README.md
```

## Repo

- **GitHub** : [mathiaschebbah/hilpo](https://github.com/mathiaschebbah/hilpo) (open-source)
- **Auteur** : Mathias Chebbah, M1 MIAGE, Université Paris Dauphine

## Changelog

| Version | Date | Changements |
|---------|------|-------------|
| 1.9 | 2026-04-04 | Frontend React + shadcn/ui, Phase 1 quasi complète |
| 1.8 | 2026-04-04 | Architecture en couches (routers→services→repos), API versionnée /v1/ |
| 1.7 | 2026-04-04 | Backend FastAPI + Docker Postgres, Phase 1 en cours, hook → PreToolUse |
| 1.6 | 2026-04-04 | Schéma BDD multi-agents × scope, architecture pipeline 4 agents |
| 1.5 | 2026-04-04 | Hook natif Claude Code remplace hookify, conventions mises à jour |
| 1.4 | 2026-04-04 | Analyse données complète, 44 formats visuels, CSV = heuristique v0 à remplacer |
| 1.3 | 2026-04-04 | Structure monorepo (hilpo/, apps/, scripts/), auteur M1 MIAGE Dauphine |
| 1.2 | 2026-04-04 | Double dimension du projet : recherche HILPO + collaboration Agent-Humain |
| 1.1 | 2026-04-04 | Ajout README, conventions (AskUserQuestion + accents FR), repo GitHub open-source |
| 1.0 | 2026-04-04 | Création initiale — structure du projet posée à partir du document HILPO |
