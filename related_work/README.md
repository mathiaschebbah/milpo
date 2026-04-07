# `related_work/` — Baselines empiriques comparées à MILPO

Ce dossier contient des implémentations de méthodes d'optimisation de prompts
**externes à MILPO**, appliquées au même problème de classification multimodale
des posts Instagram du média Views, dans le but de produire des chiffres
comparables au B0 humain et aux runs de la boucle MILPO Phase 3.

L'objectif est méthodologique : positionner MILPO honnêtement face à l'état de
l'art générique de l'optimisation de prompts, et ne pas laisser un jury (ou
un lecteur) se demander « pourquoi ne pas avoir simplement utilisé X ? ».

## Sous-dossiers

- [`dspy_baseline/`](dspy_baseline/) — DSPy MIPROv2 (Stanford). Voir
  [le README dédié](dspy_baseline/README.md) pour les détails du protocole,
  les caveats, et la procédure de reproduction.

D'autres baselines pourront s'ajouter ici (APE, PromptWizard, etc.) sans
toucher à `milpo/`.

## Principe commun à toutes les baselines

**Aucune méthode dans `related_work/` ne devient une dépendance de la
production Views.** Chaque baseline est utilisée uniquement comme générateur
de strings d'instructions hors-ligne. Les instructions produites sont
ensuite **insérées dans la table `prompt_versions`** existante (avec une
valeur dédiée dans la colonne `source` ajoutée par la migration 007), puis
**évaluées via le runtime MILPO existant** (`scripts/run_baseline.py`).

Cela garantit deux propriétés essentielles :

1. **Comparabilité apples-to-apples** : tous les runs (B0 humain, MILPO,
   DSPy, APE, etc.) sont évalués par le même code, sur les mêmes 437 posts
   du test split, avec le même tool calling Qwen, le même async batching,
   le même parsing strict, et le même tracking BDD. La seule variable qui
   change d'un run à l'autre est la string d'instructions.

2. **Isolation de la production** : aucun framework expérimental ne
   contamine `milpo/` ni `apps/`. Si on supprime `related_work/` demain, la
   pipeline Views continue de tourner identique.

## Architecture du tagging multi-source

Migration `007_prompt_source.sql` ajoute une colonne `source VARCHAR(30)` à
`prompt_versions` et fait passer la contrainte d'unicité de
`(agent, scope) WHERE active` à `(agent, scope, source) WHERE active`.

Sources prévues :

| Source             | Origine                                                |
|--------------------|---------------------------------------------------------|
| `human_v0`         | Prompts seedés par migration 006 (default rétro-compat) |
| `dspy_constrained` | DSPy MIPROv2 avec descriptions taxonomiques fixes       |
| `dspy_free`        | DSPy MIPROv2 sans contrainte sur les descriptions       |
| `milpo`            | Réservé pour les prompts issus de la boucle MILPO Phase 3 |

Plusieurs sources peuvent avoir un prompt actif en parallèle dans le même
slot `(agent, scope)`. Le runtime MILPO charge le prompt selon le mode
demandé via `--prompts {v0|active|dspy_constrained|dspy_free}`.
