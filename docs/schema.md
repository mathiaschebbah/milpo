# Schéma BDD

Fichiers :
- [`001_initial_schema.sql`](../apps/backend/migrations/001_initial_schema.sql) — tables de base
- [`002_experiment_infra.sql`](../apps/backend/migrations/002_experiment_infra.sql) — reproductibilité + simulations
- [`003_taxonomy_descriptions.sql`](../apps/backend/migrations/003_taxonomy_descriptions.sql) — colonne description sur lookups + table strategies
- [`003_descriptor_agent.sql`](../apps/backend/migrations/003_descriptor_agent.sql) — ajout `descriptor` à l'enum `agent_type`

## Tables

| Table | Rôle |
|-------|------|
| `posts` | Posts Instagram bruts (import CSV) |
| `post_media` | Fichiers média individuels — images/vidéos, URLs GCS (import CSV) |
| `categories` | Lookup — 15 catégories éditoriales (+ description) |
| `visual_formats` | Lookup — 68 formats visuels (44 post + 16 reel + 8 story) (+ description) |
| `strategies` | Lookup — 2 stratégies (Organic, Brand Content) (+ description) |
| `heuristic_labels` | Catégorisation v0 — heuristique imprécise (import CSV) |
| `sample_posts` | Échantillon 2000 posts + split dev/test + ordre de présentation |
| `annotations` | Annotations humaines (corrections/validations, flag `doubtful` pour re-review) |
| `prompt_versions` | Prompts versionnés **par agent × scope** (type de post) |
| `predictions` | Prédictions par agent + match auto-calculé par trigger |
| `rewrite_logs` | Historique des réécritures de prompt (avant/après, raisonnement) |
| `api_calls` | Traçabilité complète des appels API (tokens, coût, latence) |
| `simulation_runs` | Runs de simulation (Phase D) avec config, résultats, coûts |
| `prompt_metrics` | Vue — accuracy agrégée par version de prompt × agent × simulation |

## Descriptions taxonomie

Les trois tables de lookup (`visual_formats`, `categories`, `strategies`) ont une colonne `description TEXT` pour stocker la description visuelle/éditoriale rédigée par l'humain. Ces descriptions sont éditables via l'interface `/taxonomy` et seront injectées dans le prompt du classificateur (Phase 2).

## Reproductibilité

- `sample_posts.presentation_order` — ordre de présentation déterministe (shuffled avec seed), plus de RANDOM()
- `sample_posts.split` — dev (1563) / test (437), stratifié sur visual_format × strategy
- `predictions.simulation_run_id` — distingue live (NULL) des simulations multi-splits
- `api_calls.simulation_run_id` — idem pour la traçabilité des coûts

## Match auto-calculé

Trigger `trg_prediction_match` : à chaque INSERT/UPDATE sur `predictions`, compare `predicted_value` avec l'annotation humaine correspondante et met à jour `match` automatiquement.

## Modèle multi-agents

Chaque agent a ses propres prompts, versionnés indépendamment et scopés par type de post :

```
prompt_versions.agent  = descriptor | category | visual_format | strategy
prompt_versions.scope  = FEED | REELS | STORY | NULL (tous types)
```

Un seul prompt actif par combinaison `(agent, scope)` — index unique partiel.

## Contraintes clés

- `UNIQUE (agent, scope) WHERE status = 'active'` — un seul prompt actif par agent × scope
- `UNIQUE (ig_media_id, annotator)` — une annotation par post par annotateur
- `UNIQUE (parent_ig_media_id, media_order)` — ordre des médias dans un carousel
