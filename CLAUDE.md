# HILPO — Human-In-the-Loop Prompt Optimization

> Version **2.29** — 2026-04-06

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
- [Prompts v0](docs/prompts_v0.md) — référence humaine miroir des 6 prompts v0 seedés par la migration 006
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
| 2.29 | 2026-04-06 | Ajout table "Visual_format — accuracy par format (≥3 occ)" dans `evaluation.md` : 22 formats listés avec deltas vs run id=2, scope FEED/REELS, observations sur l'effet non uniforme du switch Gemini 3 (gros gains REELS `reel_wrap_up` +25 / `reel_voix_off` +6, mais régressions `post_chiffre` -23 et `post_selection` -15). Ces régressions deviennent cibles prioritaires pour la boucle HILPO. |
| 2.28 | 2026-04-06 | **B0 stabilisé** — run id=7, **437/437 posts (100% couverture)**, accuracies **86.7% / 65.4% / 94.5%**, coût **$2.68**, 25.4 min. Gain principal vs run id=2 obsolète : visual_format REELS **+4.6 pts** (46.2 → 50.8) grâce à Gemini 3 Flash Preview qui perçoit mieux les vidéos. Patterns d'erreur identiques (post_news ← mood, post_chiffre ← news, etc.) — confirme que ce sont des limitations des prompts v0 que HILPO doit corriger en simulation. Coût stocké en BDD via `simulation_runs.total_cost_usd`. Phase 2 ✅. Docs synchronisés (evaluation, project, phases). |
| 2.27 | 2026-04-06 | Switch descripteur (FEED+REELS) vers `google/gemini-3-flash-preview` après diagnostic des 5 posts échoués au run id=6 (Qwen 3.5 Flash limite carousel ~8 images, Gemini 2.5 Flash via Google AI Studio instable sous concurrence). Validation empirique : 18/18 sous concurrence (10 parallèles), 3/3 carousels 20 slides, audio détecté correctement (commit `7e352ab`). Coût ~$0.50/M (vs $0.065-0.30/M précédemment), justifié par la fiabilité. Classifieurs restent sur Qwen 3.5 Flash text-only via tool calling. Aussi fix : compteur `error_count` propagé dans `async_classify_batch.on_progress(done, total, errors)`. Docs synchronisés (architecture, stack, evaluation, agent_perspective). |
| 2.26 | 2026-04-06 | Fix Qwen tool calling : revert des 3 classifieurs de `response_format=json_schema` strict (cassé sur enums binaires) vers tool calling forcé via `tools=[tool] + tool_choice="auto"` (commit `0b3bd8b`). Ajout de `build_classifier_tool` et `parse_classifier_arguments`. Le descripteur garde `json_schema`. Validation empirique 18/18 ✅. Prompts v0 inchangés (migration 006 toujours valide). Docs synchronisés (architecture, evaluation, agent_perspective). |
| 2.25 | 2026-04-06 | Lock des prompts v0 en BDD via migration 006 (source de vérité unique), suppression `hilpo/prompts_v0.py`, refactor `run_simulation.py` (`load_prompt_state_from_db`), suppression du run 2 obsolète (backup SQL), `docs/prompts_v0.md` miroir, B0 à relancer |
| 2.24 | 2026-04-05 | Robustesse boucle : promotion atomique (promote_prompt), tracking versions par run (migration 005), contexte rewriter complet pour le descripteur |
| 2.23 | 2026-04-05 | Phase 3 implémentée : rewriter.py (GPT-5.4), eval.py, run_simulation.py (boucle prequential), migration 004, docs synchronisés |
| 2.22 | 2026-04-05 | Fix ensure_prompts_v0 dans run_baseline, refs prequential (Dawid 1984, Gama 2014), async_inference dans architecture, backup BDD |
| 2.21 | 2026-04-05 | Docs harmonisées sur le protocole offline/prequential, reliquats live supprimés, REPRODUCE réaligné sur l'état réel de la repo |
| 2.20 | 2026-04-05 | B0 terminé (87.3% / 64.3% / 93.5%, $1.14), résultats documentés, protocole B0→BN explicité, Phase 2 ✅ |
| 2.19 | 2026-04-05 | Pipeline E2E fonctionnel (3/3 match), prompts v0 en BDD, GCS signing, google-cloud-storage dans pyproject |
| 2.18 | 2026-04-05 | Squelette hilpo/ implémenté (7 modules), migration 003 descriptor, pyproject.toml racine, docs corrigés |
| 2.17 | 2026-04-05 | Architecture Phase 2 : descripteur multimodal (Qwen 3.5 Flash FEED / Gemini 2.5 Flash REELS) + 3 classifieurs text-only, schema features JSON, 6 prompts optimisables, setup skill chargé conventions |
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
