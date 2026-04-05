# Reproduire les résultats de HILPO

Ce guide permet de reproduire l'état actuel des résultats disponibles dans le dépôt et de documenter le protocole expérimental visé pour la Phase 3.

## Prérequis

| Outil | Version | Installation |
|-------|---------|-------------|
| Docker | 24+ | [docker.com](https://docs.docker.com/get-docker/) |
| Python | 3.12 | via pyenv ou [python.org](https://www.python.org/) |
| uv | 0.7+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 22+ | via nvm ou [nodejs.org](https://nodejs.org/) |
| Clé API | OpenRouter | Variable d'environnement `OPENROUTER_API_KEY` |

## 1. Cloner et installer

```bash
git clone https://github.com/mathiaschebbah/hilpo.git
cd hilpo
uv sync
```

## 2. Données

Les données brutes (posts Instagram Views) ne sont pas incluses dans le repo pour des raisons de propriété intellectuelle et de copyright sur les médias. Elles sont disponibles **sur demande** auprès de l'auteur (mathias.chebbah@dauphine.eu).

### Fichiers attendus

Placer les 3 fichiers CSV dans `data/` :

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `core_posts_rows.csv` | 21 425 | Posts Instagram (id, caption, timestamp, type) |
| `core_post_categories_rows.csv` | 19 353 | Labels heuristiques v0 (category, visual_format, strategy) |
| `core_post_media_rows.csv` | 84 019 | Médias (URLs GCS, dimensions, durée) |

### Vérification d'intégrité

```bash
sha256sum data/*.csv
# Checksums attendus :
# [À COMPLÉTER après stabilisation des données]  core_posts_rows.csv
# [À COMPLÉTER après stabilisation des données]  core_post_categories_rows.csv
# [À COMPLÉTER après stabilisation des données]  core_post_media_rows.csv
```

### Médias (images/vidéos)

Les URLs dans `core_post_media_rows.csv` pointent vers un bucket Google Cloud Storage privé. Pour la reproduction :

- **Avec accès GCS** : configurer `HILPO_GCS_SIGN_URLS=true` et un compte de service avec le rôle `storage.objects.get`.
- **Sans accès GCS** : l'annotation et les métriques fonctionnent sans les médias. Seule l'interface visuelle d'annotation est impactée. Les métadonnées (caption, type, catégorie) suffisent pour vérifier les résultats.

## 3. Base de données

```bash
# Démarrer PostgreSQL 17 (port 5433)
docker compose up -d

# Vérifier que le service est healthy
docker compose ps
# db   postgres:17   Up (healthy)   0.0.0.0:5433->5432/tcp
```

Les migrations SQL (`apps/backend/migrations/001_*.sql`, `002_*.sql`, `003_*.sql`) sont appliquées automatiquement au premier démarrage via `docker-entrypoint-initdb.d`.

## 4. Import des données

```bash
cd apps/backend
uv sync
uv run python ../../scripts/import_csv.py
```

Le script :
- Importe les 21 425 posts, 19 353 labels, 84 019 médias
- Peuple les lookups (15 catégories, 68 formats visuels ; table `strategies` via migration)
- Échantillonne 2 000 posts stratifiés sur `visual_format × strategy`
- Sépare en dev (1 563) / test (437) stratifié sur `media_product_type`
- Fixe l'ordre de présentation (seed PostgreSQL `setseed(0.42)`)

**Seed** : le script appelle `setseed(0.42)` en début de session PostgreSQL. Toutes les opérations `RANDOM()` qui suivent (échantillonnage, splits, ordre) sont déterministes dans une même session.

## 5. Backend

```bash
cd apps/backend
cp .env.example .env
# Éditer .env si nécessaire (les défauts fonctionnent pour le dev local)

uv run uvicorn app.main:app --port 8000
```

Vérifier : `curl http://localhost:8000/health` → `{"status": "ok"}`

## 6. Frontend

```bash
cd apps/frontend
npm ci
npm run dev
```

Ouvrir http://localhost:5173. L'API est proxifiée automatiquement vers le backend (`/v1` → `localhost:8000`).

## 7. Reproduire les expériences

À l'état actuel du dépôt, l'import, l'annotation et la baseline B0 sont directement rejouables. La simulation HILPO, les métriques agrégées et les figures sont documentées ci-dessous comme interface cible, mais les scripts correspondants ne sont pas encore présents dans la repo au 5 avril 2026.

### Phase 1 — Annotations (données fournies)

Les annotations humaines sont stockées dans la table `annotations`. Pour une reproduction complète, l'annotateur re-swipe les 2 000 posts via l'interface. Pour une vérification, un dump SQL des annotations est fourni sur demande.

### Phase 2 — Baseline zero-shot (B0)

```bash
uv run python scripts/run_baseline.py
```

Évalue le prompt v0 sur les 437 posts test. Résultat stocké dans `simulation_runs`.

### Phase 3 — Simulation HILPO

Le script `scripts/run_simulation.py` est implémenté et fonctionnel :

```bash
uv run python scripts/run_simulation.py --batch-size 30
```

Rejoue les annotations dev dans l'ordre de présentation. Le prompt évolue via le rewriter (protocole prequential). Résultat stocké dans `simulation_runs`.

### Ablations

```bash
uv run python scripts/run_simulation.py --batch-size 1
uv run python scripts/run_simulation.py --batch-size 10
uv run python scripts/run_simulation.py --batch-size 50
```

Même annotations, même ordre — seul le batch size change.

### Évaluation finale (BN)

Réutilise le pipeline de `run_baseline.py` avec le prompt vN (dernier prompt actif après simulation).

### Métriques et figures

Les commandes cibles pour les métriques et figures :

```bash
uv run python scripts/metrics.py --output results/
uv run python scripts/figures.py --input results/ --output figures/
```

**Figures générées :**
1. `convergence.pdf` — accuracy en rolling window vs posts traités (dev), rewrites annotés
2. `comparison.pdf` — Tableau B0 vs HILPO vN (accuracy, F1 macro, p-value McNemar)
3. `ablation_batch.pdf` — Effet du batch size (B=1, 10, 30, 50)
4. `confusion_matrix.pdf` — Matrice de confusion visual_format v0 vs vN

## 8. Vérification

| Vérification | Commande |
|-------------|----------|
| Nombre de posts importés | `psql -h localhost -p 5433 -U hilpo -d hilpo -c "SELECT COUNT(*) FROM sample_posts"` → 2 000 |
| Splits dev/test | `... -c "SELECT split, COUNT(*) FROM sample_posts GROUP BY split"` → dev 1563, test 437 |
| Seed stockée | `... -c "SELECT DISTINCT seed FROM sample_posts"` → 42 |
| Annotations existantes | `... -c "SELECT COUNT(*) FROM annotations"` |
| Prompts versionnés | `... -c "SELECT agent, scope, version, status FROM prompt_versions ORDER BY agent, version"` |
| Coût total API | `... -c "SELECT call_type, COUNT(*), SUM(cost_usd) FROM api_calls GROUP BY call_type"` |

## Architecture du repo

```
hilpo/
├── REPRODUCE.md            ← ce fichier
├── CLAUDE.md               ← index versionné du projet
├── docker-compose.yml      ← PostgreSQL 17
├── apps/
│   ├── backend/            ← FastAPI (Python 3.12, uv)
│   │   ├── app/            ← routers, services, repositories, schemas
│   │   ├── migrations/     ← 001, 002, 003 SQL (appliquées par Docker)
│   │   └── .env.example    ← variables d'environnement
│   └── frontend/           ← React + Vite + TypeScript + shadcn/ui
├── scripts/
│   ├── import_csv.py       ← import données + échantillonnage
│   └── run_baseline.py     ← [Phase 2] baseline zero-shot B0
├── data/                   ← CSV (gitignored, sur demande)
├── results/                ← métriques exportées (gitignored)
├── figures/                ← PDF/PNG des figures (gitignored)
└── docs/                   ← documentation versionnée
    ├── project.md          ← hypothèses, positionnement, claim
    ├── architecture.md     ← pipeline, formalisation p_t = (I_t, Δ)
    ├── evaluation.md       ← protocole, métriques, tiers, checklist
    ├── schema.md           ← tables, relations, triggers
    └── ...
```

Scripts prévus :
- `scripts/metrics.py` — calcul F1, kappa, McNemar
- `scripts/figures.py` — génération des figures du mémoire

## Reproductibilité — design

| Mécanisme | Implémentation |
|-----------|---------------|
| **Seeds fixées** | `setseed(0.42)` dans import, `sample_posts.seed` en BDD |
| **Simulation rejouable** | Même annotations, même ordre → résultats déterministes |
| **Prompt versionné** | `prompt_versions.content` stocke le texte intégral, parent_id trace l'historique |
| **Match auto-calculé** | Trigger `trg_prediction_match` compare prédiction vs annotation |
| **Traçabilité API** | `api_calls` : tokens, coût, latence, agent, prompt_version par appel |
| **Runs versionnés** | `simulation_runs` : seed, batch_size, config, résultats agrégés |
| **Descriptions fixes** | Taxonomie rédigée par l'humain (Δ), injectée dans le prompt, non modifiée par le rewriter |

## Contact

Mathias Chebbah — mathias.chebbah@dauphine.eu
Master 1 MIAGE, Université Paris Dauphine — PSL
