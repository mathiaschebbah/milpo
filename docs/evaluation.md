# Protocole expérimental

## Métriques de classification

Par axe (visual_format, catégorie, stratégie) et global (3 axes corrects simultanément) :
- Accuracy
- F1 macro (insensible au déséquilibre des classes)
- F1 micro
- Matrice de confusion
- Cohen's kappa (accord modèle/humain)

Rapportés sur 1 run principal (contrainte de coût API). La variance est adressée via les ablations (B=1, 10, 30, 50) qui rejouent la simulation sur les mêmes annotations.

## Significativité statistique

- Test de McNemar (paire par paire) entre B0 et HILPO vN sur le test set
- p-values rapportées, seuil alpha = 0.05

## Protocole B0 → HILPO → BN

Le protocole repose sur la comparaison de deux runs sur le **même test set** (437 posts) :

1. **Annotation** : l'humain annote le dev (1 563 posts) en aveugle (sans voir les prédictions)
2. **B0** (fait) : prompt v0 (écrit à la main) évalué sur test → accuracy baseline
3. **Simulation HILPO** : replay séquentiel des annotations dev dans l'ordre de présentation. Protocole prequential : le prompt évolue v0 → v1 → ... → vN via le rewriter (B=30, delta=2%, patience=3).
4. **BN** : prompt vN (dernier prompt actif après convergence) évalué sur test → accuracy finale

La différence BN - B0 est directement attribuable à HILPO. Même test set, même pipeline, même descripteur, mêmes descriptions taxonomiques — seules les instructions I_t changent.

Chaque run est stocké dans `simulation_runs` avec sa config, ses métriques, et son coût. Reproductible.

## Convergence

- Courbe accuracy vs nombre d'annotations (dev uniquement, rolling window de 50 posts)
- Les moments de rewrite (v0 → v1 → v2...) sont annotés sur la courbe
- Plateau défini comme : variation < 2% sur les 3 dernières itérations
- Les blocs de comparaison incumbent/candidate post-rewrite sont évalués explicitement sur le bloc futur commun (`eval_window=30`)

## Fiabilité de l'annotation

- Kappa intra-annotateur (test-retest à l'aveugle, 50+ posts)
- Kappa inter-annotateur (collaborateur Views, 500+ posts) — si disponible

## Résultats B0 — Baseline zero-shot v0

> ---
> ⚠️ **OBSOLÈTE — en attente de relance**
>
> Les résultats ci-dessous ont été obtenus le 2026-04-05 avec les prompts v0 **avant** le commit `d2e84e9` (*Enforce strict JSON schemas for HILPO outputs*), qui a modifié les 6 prompts pour supprimer les références au tool use. Le `simulation_run id=2` a été supprimé de la BDD le 2026-04-06 (backup SQL conservé dans `data/backups/run_2_2026-04-06_11-32.sql`). Les prompts v0 ont ensuite été lockés en BDD via la migration [`006_seed_prompts_v0.sql`](../apps/backend/migrations/006_seed_prompts_v0.sql).
>
> Un nouveau run B0 doit être lancé (`uv run python scripts/run_baseline.py`) avec les prompts v0 courants. Les chiffres, patterns d'erreur et coûts listés dans cette section resteront ici à titre historique jusqu'à ce que les nouveaux résultats soient disponibles.
> ---

Exécuté le 5 avril 2026. simulation_run id=2. 434/437 posts classifiés (3 échoués — descripteur réponse vide).

### Accuracy globale

| Axe | Accuracy | Correct/Total |
|-----|----------|---------------|
| Catégorie (15 classes) | **87.3%** | 379/434 |
| Visual_format (44 FEED + 16 REELS) | **64.3%** | 279/434 |
| Stratégie (2 classes) | **93.5%** | 406/434 |

### Accuracy par scope

| Axe | FEED (369) | REELS (65) |
|-----|------------|------------|
| Catégorie | 90.0% | 72.3% |
| Visual_format | 67.5% | 46.2% |
| Stratégie | 93.5% | 93.8% |

Les REELS sont significativement plus durs que les FEED sur catégorie (-17.7 pts) et visual_format (-21.3 pts). La stratégie est stable (signal dans la caption).

### Visual_format — accuracy par format (≥ 3 occurrences test)

| Format | Test | Accuracy | Note |
|--------|------|----------|------|
| post_mood | 113 | 94% | Format dominant, bien classé |
| post_news | 111 | 68% | 23 confusions ← post_mood (anciens news sans texte) |
| reel_voix_off | 17 | 82% | Audio détecté par Gemini |
| post_chiffre | 22 | 41% | Confondu avec post_news |
| post_selection | 20 | 50% | Confondu avec serie_mood_texte |
| reel_news | 16 | 25% | Classé reel_mood/reel_wrap_up |
| reel_wrap_up | 12 | 0% | Jamais prédit |
| post_wrap_up | 8 | 0% | Jamais prédit |
| post_en_savoir_plus | 5 | 0% | Jamais prédit |
| post_stills | 4 | 100% | Parfait — screenshots distinctifs |

### Patterns d'erreur principaux

1. **post_mood ← post_news (23 erreurs)** : la règle "pas de texte overlay → post_mood" ignore les anciens post_news (news uniquement dans la caption). La description taxonomique couvre ce cas — les instructions I_t ne le priorisent pas.
2. **post_news ← post_chiffre (13 erreurs)** : le classifieur voit "texte overlay + actualité" et conclut post_news, sans détecter le chiffre marquant en grand.
3. **reel_mood ← reel_wrap_up / reel_news (16 erreurs)** : les REELS sans gabarit Views sont classés reel_mood par défaut.
4. **Formats à 0%** : jamais prédits car absorbés par des formats plus fréquents. L'amélioration des critères sur les formats fréquents devrait libérer les formats rares (effet longue traîne indirect).

### Coût

| Agent | Modèle | Appels | Tokens in | Tokens out | Latence moy. | Coût |
|-------|--------|--------|-----------|------------|--------------|------|
| Descripteur FEED | Qwen 3.5 Flash | 369 | 5.66M | 196K | 6.8s | $0.42 |
| Descripteur REELS | Gemini 2.5 Flash | 65 | 25K | 94K | 17.9s | $0.24 |
| Visual_format | Qwen 3.5 Flash | 434 | 1.59M | 636K | 11.6s | $0.27 |
| Catégorie | Qwen 3.5 Flash | 434 | 769K | 241K | 4.2s | $0.11 |
| Stratégie | Qwen 3.5 Flash | 434 | 665K | 191K | 3.5s | $0.09 |
| **TOTAL** | | **1 736** | **8.72M** | **1.36M** | | **$1.14** |

### Contexte du rewriter — format des batches d'erreurs

Quand le rewriter se déclenche (30 erreurs accumulées), il reçoit pour chaque erreur :

- Le label **prédit** et le label **attendu** (annotation humaine)
- Les **features JSON** extraites par le descripteur (texte_overlay, logos, mise_en_page, etc.)
- Le **résumé visuel** du descripteur
- La **caption** du post
- La **description taxonomique** du format prédit ET du format attendu
- Les **instructions I_t actuelles** du classifieur

Ce format permet au rewriter d'agir comme un ingénieur en debug : il voit le comportement attendu vs observé, les features qui auraient dû déclencher le bon label, et les descriptions taxonomiques qui couvrent le cas. Il peut identifier quelles règles dans I_t sont responsables de l'erreur.

## Tiers de priorité

### Tier 1 — Indispensable

| Action | Résultat attendu | Statut |
|--------|------------------|--------|
| Annoter split test (437 posts) | Ground truth test | ✅ fait |
| B0 : zero-shot prompt v0 sur test | Accuracy baseline | ⚠️ à relancer — prompts v0 modifiés au commit `d2e84e9`, run id=2 supprimé (voir bandeau OBSOLÈTE ci-dessus) |
| Annoter split dev (1 563 posts) | Ground truth dev | ⬜ à faire (annotation aveugle, puis simulation prequential) |
| Kappa intra-annotateur (re-swipe 50 posts) | Fiabilité ≥ 0.7 | ⬜ à faire |

### Tier 2 — Nécessaire pour le claim

| Action | Résultat attendu |
|--------|------------------|
| Phase 3 : rewriter batch=30 + rollback | Prompts v1, v2, ... vN générés |
| Courbe accuracy vs annotations | **LA figure centrale du mémoire** |
| BN : éval prompt vN vs v0 sur split test | **LE chiffre central du mémoire** |

### Tier 3 — Renforce le claim

| Action | Résultat attendu |
|--------|------------------|
| Ablations A1-A4 : batch size 1/10/30/50 | Sensibilité au batch size |
| Baseline B4 : CLIP embeddings + LogReg | Comparaison supervisée |
| Ablation A5 : sans rollback | Utilité du rollback |
| Matrices de confusion par axe | Analyse qualitative des erreurs |

### Tier 4 — Bonus

| Action | Résultat attendu |
|--------|------------------|
| Kappa inter-annotateur | Validité de la taxonomie |
| Ablation A6 : rewrite humain vs LLM | Qualité du rewriter |
| Baseline B1 : zero-shot CLIP | Comparaison embedding-based |
| Analyse qualitative de l'évolution du prompt | Insight interprétatif |

## 4 figures indispensables

1. **Courbe de convergence** : accuracy en Y, nombre d'annotations en X. Montrer dev (rolling window). Annoter les moments de rewrite (v0 → v1 → v2...).
2. **Tableau de comparaison** : B0, B2, HILPO vN, avec accuracy + F1 macro, p-value McNemar.
3. **Ablation batch size** : Barplot ou courbe montrant l'effet de B=1, 10, 30, 50 sur la performance finale.
4. **Matrice de confusion** : Pour visual_format, avant (v0) vs après (vN).

## Ablations

| ID | Variante | Variable testée |
|----|----------|-----------------|
| A0 | Prompt v0 statique | Baseline sans optimisation |
| A1 | HILPO batch=1 | Taille du batch |
| A2 | HILPO batch=10 | Taille du batch |
| A3 | HILPO batch=30 (défaut) | Configuration principale |
| A4 | HILPO batch=50 | Taille du batch |
| A5 | HILPO sans rollback | Effet du mécanisme de rollback |
| A6 | HILPO rewrite humain | LLM rewriter vs humain expert |

## Baselines

| ID | Méthode | Type | Données nécessaires |
|----|---------|------|---------------------|
| B0 | Zero-shot + prompt v0 | Zero-shot | 0 |
| B1 | Zero-shot CLIP | Zero-shot | 0 |
| B2 | Few-shot 5 exemples/classe | Few-shot | ~150 |
| B3 | Few-shot 10 exemples/classe | Few-shot | ~300 |
| B4 | CLIP embeddings + Logistic Regression | Supervisé | 1563 |
| B5 | CLIP embeddings + SVM | Supervisé | 1563 |
| B6 | Fine-tuning LoRA (si faisable) | Supervisé | 1563 |

## Checklist de recevabilité

### Cadrage théorique
- [x] Problématique = hypothèses falsifiables (H1, H2)
- [ ] État de l'art ≥ 15 références (APE, DSPy, iPrOp, ProTeGi, PromptWizard)
- [x] Positionnement explicite (4 axes)
- [x] Formalisation mathématique de la boucle

### Protocole
- [ ] Ground truth ≥ 1563 dev + 437 test
- [ ] Kappa intra-annotateur ≥ 0.7
- [ ] 1 run principal + ablations batch size
- [ ] McNemar sur B0 vs HILPO vN

### Résultats
- [ ] B0 (zero-shot v0) — à relancer avec les prompts v0 lockés via migration 006 (les anciens chiffres 87.3% / 64.3% / 93.5% sont obsolètes depuis le commit `d2e84e9`)
- [ ] B2 (few-shot)
- [ ] HILPO final (BN)
- [ ] Courbe de convergence
- [ ] ≥ 1 ablation (batch size ou rollback)
- [ ] Matrice de confusion avant/après

### Discussion
- [ ] Classes qui bénéficient le plus
- [ ] Évolution qualitative du prompt (v0 → vN)
- [ ] Transfert zero-shot : accuracy formats vus vs jamais vus pendant l'optimisation
- [ ] Longue traîne : amélioration indirecte des formats rares via resserrement des formats fréquents
- [ ] Limites honnêtes
- [ ] Coût comparé (annotations, appels API, $)

### Forme
- [ ] Abstract ≤ 250 mots avec claim + résultat clé
- [ ] Bibliographie ≥ 15 références académiques
- [ ] Code reproductible (repo public, seeds fixées)
