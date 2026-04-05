# HILPO — Human-In-the-Loop Prompt Optimization

> Version **2.16** — 2026-04-06

## Double dimension du projet

1. **Recherche HILPO** : peut-on classifier des données multimodales sans gros dataset, en optimisant itérativement un prompt via une boucle humain-dans-la-boucle ?
2. **Collaboration Agent-Humain** : le projet lui-même est construit via une collaboration structurée entre Claude Code et l'humain. Les hooks (validation CLAUDE.md, AskUserQuestion) incarnent le paradigme humain-dans-la-boucle au niveau du développement. La progression est traçable dans l'historique git.

## Index

- [Projet](docs/project.md) — hypotheses falsifiables, positionnement, claim vise
- [Etat de l'art](docs/related_work.md) — APE, DSPy, iPrOp, positionnement HILPO
- [Stack](docs/stack.md) — technologies et choix techniques
- [Architecture](docs/architecture.md) — agents, pipeline, formalisation mathematique
- [Schema BDD](docs/schema.md) — tables, relations, contraintes
- [Donnees](docs/data.md) — structure des CSV, axes de classification, taxonomie
- [Phases](docs/phases.md) — phases de dev et avancement
- [Evaluation](docs/evaluation.md) — protocole, metriques, tiers de priorite, checklist recevabilite
- [Reproduire](REPRODUCE.md) — guide de reproduction des résultats (jury/reviewers)
- [Conventions](docs/conventions.md) — règles de collaboration et standards
- [Planning](docs/planning.md) — calendrier jour par jour avec creneaux, 5-18 avril 2026
- [Perspective agent](docs/agent_perspective.md) — snapshots datés de l'état de compréhension de l'agent

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
| 2.16 | 2026-04-06 | Travail taxonomie : 3 fusions, 6 formats ajoutés, 68/68 décrits, critères discriminants, analyse temporelle captions |
| 2.15 | 2026-04-05 | Analyse équilibre dataset : loi de puissance, longue traîne, F1 macro avec/sans classes rares |
| 2.14 | 2026-04-05 | Agent perspective (snapshot + hook PostToolUse auto), hooks PreToolUse→PostToolUse (non bloquant) |
| 2.13 | 2026-04-05 | 4e axe positionnement : transfert zero-shot via descriptions, métrique formats vus vs jamais vus |
| 2.12 | 2026-04-05 | Flag "pas sûr" (touche d), colonne doubtful, filtre/pastille dans grille, re-annotation rapide |
| 2.11 | 2026-04-05 | Ordre test-first, badge dev/test dans UI, filtre split, re-annotation posts test via grille, GET /posts/{id} |
| 2.10 | 2026-04-05 | Séparation backend (HTTP) / engine hilpo/ (IA), contraintes split dev/test, annotation aveugle |
| 2.9 | 2026-04-05 | Description inline dans annotation, split moody monday/sunday, reel_chiffre/interview/evenement |
| 2.8 | 2026-04-05 | Filtrage formats par scope dans le sélecteur, fix crash MediaViewer, ajout reel_chiffre |
| 2.7 | 2026-04-04 | Routage déterministe, taxonomie 59 formats (42 post + 10 reel + 7 story), UI tabs, Y_k^m et Δ^m scopés |
| 2.6 | 2026-04-04 | CRUD taxonomie : descriptions pour formats visuels, catégories, stratégies, page /taxonomy |
| 2.5 | 2026-04-04 | Cadrage recherche : hypothèses H1/H2, état de l'art, formalisation, tiers éval, planning révisé |
| 2.4 | 2026-04-04 | Guard MediaViewer undefined, test E2E validé (22 annotations) |
| 2.3 | 2026-04-04 | Phase 1 terminée — BIGINT string, proxy Vite, skip multi-exclude, vidéo player |
| 2.2 | 2026-04-04 | Infra expérimentale : splits dev/test, ordre déterministe, trigger match, simulation_runs |
| 2.1 | 2026-04-04 | Skill /setup pour initialisation contexte, skills versionnés dans git |
| 2.0 | 2026-04-04 | GCS URLs signées, vue dataset, filtrage Views, conventions typo |
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
