---
name: setup
description: >
  Initialise le contexte du projet MILPO en début de conversation. Depuis v3.3, ne lit PLUS les docs/ narratives (supprimées car elles dérivaient) : inspecte activement le code, la BDD et les services pour reconstruire un état exact. Utiliser en début de chaque session.
---

# Setup — Initialisation du contexte MILPO (v3.3)

**Philosophie** : la source de vérité est le code + la BDD, pas des résumés narratifs. Ce skill reconstruit le contexte à la volée pour éviter de s'appuyer sur de la doc qui pourrit entre deux sessions (cf. `docs/note_intelligence_artificielle.md` et changelog CLAUDE.md v3.3).

Exécute les étapes suivantes, en parallélisant autant que possible.

## Étape 1 — Lire CLAUDE.md et la matière mémoire conservée

Lis en parallèle :

1. `CLAUDE.md` — index + changelog (source canonique de l'état narratif du projet)
2. `docs/note_intelligence_artificielle.md` — lecture réflexive de Mathias sur l'usage de l'IA
3. `docs/project.md` — hypothèses H1/H2/H3, claim, positionnement
4. `docs/related_work.md` — ProTeGi, DSPy, iPrOp
5. `docs/evaluation.md` — protocole, métriques, résultats B0

Ces fichiers sont **de la matière mémoire brute** (décisions, chiffres, hypothèses qui ne sont pas dérivables du code). Tout le reste doit être reconstruit depuis le code et la BDD.

## Étape 2 — Inspection active du code

En parallèle :

- `ls milpo/` — modules du moteur MILPO
- `ls apps/backend/app/` et `ls apps/frontend/src/` — structure des apps
- `ls scripts/` — scripts d'import, simulation, features
- `ls related_work/` — baselines (DSPy, etc.)
- Read `pyproject.toml` (racine) — dépendances Python + deps optionnelles (dspy)
- Read `apps/frontend/package.json` — deps frontend

Ouvre **au moins** ces modules clés pour savoir ce qui tourne vraiment :

- `milpo/db.py` — accès BDD, fonctions `get_active_prompt`, `promote_prompt`, signatures à jour
- `milpo/rewriter.py` — logique de rewriting des prompts
- `scripts/run_simulation.py` — orchestration de la boucle prequential
- `scripts/run_baseline.py` — B0 et modes DSPy

## Étape 3 — Inspection de la BDD

Les credentials sont dans `.env` (variable `HILPO_DATABASE_DSN` — préfixe hérité avant le rename v3.0). DSN actuel : `postgresql://hilpo:hilpo@localhost:5433/hilpo`. Utilise donc `PGPASSWORD=hilpo psql -h localhost -p 5433 -U hilpo -d hilpo` (si ça échoue, relire `.env` au cas où le DSN aurait changé).

Commandes utiles (à lancer en parallèle) :

```sql
-- Tables et schéma
\dt

-- Volumétrie posts et annotations
SELECT COUNT(*) FROM posts;

-- Splits : la colonne `split` est sur `sample_posts`, pas sur `posts`
SELECT split, COUNT(*) FROM sample_posts GROUP BY split;

SELECT COUNT(*) FROM annotations;

-- Prompts actifs (par agent, scope, source)
SELECT agent, scope, source, version, LEFT(content, 80) AS preview
FROM prompt_versions
WHERE status = 'active' AND simulation_run_id IS NULL
ORDER BY agent, scope, source;

-- Derniers simulation_runs (pas de colonnes `kind` ni `notes` — cf. `\d simulation_runs`)
SELECT id, status, started_at, finished_at, total_cost_usd,
       final_accuracy_category AS cat,
       final_accuracy_visual_format AS vf,
       final_accuracy_strategy AS strat
FROM simulation_runs
ORDER BY id DESC LIMIT 5;

-- Migrations appliquées
\dn
\d prompt_versions  -- vérifier que la colonne `source` existe (migration 007)
```

## Étape 4 — Vérifier les services

- `docker compose ps` — Postgres
- `lsof -ti :8000` — backend FastAPI
- `lsof -ti :5173` — frontend Vite

## Étape 4bis — Vérifier les credentials GCS ADC

Les médias Views sont servis depuis un bucket GCS privé (`postfinder-media-dev`). Le backend signe les URLs V4 via `apps/backend/app/gcs.py`, qui s'appuie sur les **Application Default Credentials** locales (`google.auth.default()`). Ces credentials expirent régulièrement — quand c'est le cas, le backend log une `RefreshError` mais renvoie silencieusement les URLs non signées, et le frontend ne peut pas afficher les médias → l'annotation est bloquée.

Diagnostic (une seule commande, rapide) :

```bash
gcloud auth application-default print-access-token >/dev/null 2>&1 && echo "GCS ADC ✓" || echo "GCS ADC ✗ (expired)"
```

- ✓ → rien à faire, les URLs seront signées.
- ✗ → **ne pas lancer la commande `gcloud` toi-même** (elle est interactive, ouvre un navigateur). Mentionne-le dans la synthèse et suggère à Mathias de lancer :
  ```
  ! gcloud auth application-default login
  ```
  Le préfixe `!` exécute la commande dans la session Claude Code. Après ré-auth, **il faut redémarrer le backend** (les credentials sont mis en cache dans le process au premier appel — un simple kill + relance d'uvicorn suffit).

## Étape 5 — Historique git

- `git log --oneline -15` — derniers commits
- `git status` — working tree

## Étape 6 — Synthèse

Présente un résumé concis :

```
MILPO — État du projet (reconstruit depuis code + BDD)
======================================================
Version CLAUDE.md : vX.Y (dernier changelog : <résumé 1 ligne>)
Dernier commit    : <hash> <message>
Working tree      : clean / N fichiers modifiés

Code
----
- milpo/ : <modules principaux détectés>
- apps/backend : <modules détectés>
- apps/frontend : <modules détectés>
- scripts/ : <scripts détectés>
- related_work/ : <baselines détectées>

BDD (hilpo @ localhost:5433)
----------------------------
- Posts : N total, dev=X / test=Y / unassigned=Z
- Annotations : N
- Prompts actifs : <agent/scope/source/version pour chacun>
- Dernier run : id=N, status=..., cost=$..., cat/vf/strat=...

Services
--------
Postgres ✓/✗ | Backend ✓/✗ | Frontend ✓/✗ | GCS ADC ✓/✗
(si GCS ADC ✗ → suggérer `! gcloud auth application-default login` + redémarrage backend)

Mémoire / contexte
------------------
- Matière mémoire disponible : project.md, related_work.md, evaluation.md, note_intelligence_artificielle.md
- Hypothèses actives : H1/H2/H3 (résumé 1 ligne chacune depuis project.md)
```

Puis demande : « On continue sur quoi ? »

## Ce que ce skill NE fait plus (vs v3.2)

- ❌ Lire tout `docs/` — les docs narratives dérivantes ont été supprimées en v3.3
- ❌ Lancer 5 sub-agents pour résumer le codebase — coûteux et produit une narration qui se substituera au code
- ❌ Mettre à jour `docs/agent_perspective.md` — fichier supprimé, hook retiré

La logique est inversée : **regarde ce qui EST, ne lis pas ce qui a été ÉCRIT sur ce qui est**.
