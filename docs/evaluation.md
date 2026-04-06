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

Exécuté le 2026-04-06. **simulation_run id=7. 437/437 posts classifiés (100% de couverture)**. Configuration : descripteur Gemini 3 Flash Preview pour FEED+REELS (`response_format=json_schema`), classifieurs Qwen 3.5 Flash + tool calling forcé (`tool_choice="auto"`), prompts v0 lockés via [migration 006](../apps/backend/migrations/006_seed_prompts_v0.sql).

### Accuracy globale

| Axe | Accuracy | Correct/Total |
|-----|----------|---------------|
| Catégorie (15 classes) | **86.7%** | 379/437 |
| Visual_format (44 FEED + 16 REELS) | **65.4%** | 286/437 |
| Stratégie (2 classes) | **94.5%** | 413/437 |

### Accuracy par scope

| Axe | FEED (372) | REELS (65) | Δ FEED → REELS |
|-----|------------|------------|----------------|
| Catégorie | 89.0% | 73.8% | -15.2 pts |
| Visual_format | 68.0% | 50.8% | -17.2 pts |
| Stratégie | 94.6% | 93.8% | -0.8 pt |

Les REELS sont significativement plus durs que les FEED sur catégorie et visual_format. La stratégie est stable (signal dans la caption, peu importe le scope).

### Patterns d'erreur principaux (visual_format)

| Expected → Predicted | n | Interprétation |
|---|---|---|
| post_news → post_mood | 22 | Anciens post_news sans texte en overlay (news dans la caption uniquement). La description taxonomique couvre ce cas — les instructions I_t ne le priorisent pas. |
| post_chiffre → post_news | 18 | Le classifieur voit "texte overlay + actualité" et conclut post_news, sans détecter le chiffre marquant en grand. |
| post_selection → post_serie_mood_texte | 12 | Confusion sur les carousels structurés avec texte par slide. |
| reel_news → reel_mood | 10 | Les REELS sans gabarit Views sont classés reel_mood par défaut. |
| reel_interview → reel_sitdown | 5 | Confusion entre 2 types d'interview (face caméra assise vs debout/mouvement). |
| post_wrap_up → post_mood | 4 | Recap événement absorbé par mood. |
| reel_wrap_up → reel_mood | 4 | Idem côté reels. |
| post_en_savoir_plus_selection → post_selection | 3 | Variante non distinguée. |
| post_interview → post_blueprint | 3 | Confusion gabarit. |
| post_news → post_serie_mood_texte | 3 | |

Ces patterns sont **identiques aux observations du run id=2 (pré-fix)** — ce sont des limitations des **prompts v0**, pas du modèle. C'est exactement ce que la boucle HILPO doit corriger en simulation.

### Visual_format — accuracy par format (≥ 3 occurrences test)

22 formats ont au moins 3 occurrences dans le test set, classés par fréquence :

| Format | Scope | Test | OK | Accuracy | Δ vs run id=2 | Note |
|--------|-------|------|----|----------|---------------|------|
| post_mood | FEED | 113 | 109 | **96%** | +2 pts | Format dominant, parfaitement classifié |
| post_news | FEED | 111 | 78 | 70% | +2 pts | Toujours 22 confusions ← post_mood (anciens news) |
| post_chiffre | FEED | 22 | 4 | **18%** | **-23 pts** ⚠️ | Régression : Gemini 3 confond plus avec post_news |
| post_quote | FEED | 21 | 17 | 81% | n/a | Bien classifié, signal "guillemets" clair |
| post_selection | FEED | 20 | 7 | **35%** | **-15 pts** ⚠️ | Régression : confusion avec serie_mood_texte |
| reel_voix_off | REELS | 17 | 15 | **88%** | **+6 pts** | Audio bien détecté par Gemini 3 |
| reel_news | REELS | 16 | 5 | 31% | +6 pts | Reels sans gabarit Views classés reel_mood |
| reel_wrap_up | REELS | 12 | 3 | **25%** | **+25 pts** | Gros gain : Gemini 3 voit le montage post-événement |
| reel_interview | REELS | 8 | 2 | 25% | n/a | Confusion avec reel_sitdown |
| post_wrap_up | FEED | 8 | 0 | 0% | = | Toujours invisible — absorbé par mood |
| post_sorties_musique | FEED | 7 | 5 | 71% | n/a | Bien classifié |
| post_classement | FEED | 7 | 3 | 43% | n/a | |
| post_interview | FEED | 7 | 3 | 43% | n/a | |
| post_serie_mood_texte | FEED | 6 | 2 | 33% | n/a | |
| post_en_savoir_plus_selection | FEED | 6 | 0 | 0% | = | Variante non distinguée |
| post_en_savoir_plus | FEED | 5 | 0 | 0% | = | Toujours invisible |
| post_article | FEED | 4 | 3 | 75% | n/a | |
| post_stills | FEED | 4 | 4 | **100%** | = | Parfait — screenshots distinctifs |
| post_playlist_views_essentials | FEED | 3 | 2 | 67% | n/a | |
| reel_mood | REELS | 3 | 3 | **100%** | n/a | |
| post_frise | FEED | 3 | 0 | 0% | n/a | Format rare invisible |
| post_double_selection | FEED | 3 | 3 | **100%** | n/a | |

**Observation clé** : le changement de descripteur (Qwen → Gemini 3 Flash Preview) a un effet **non uniforme** sur les formats individuels :
- **Gains** sur les REELS (`reel_voix_off` +6, `reel_wrap_up` +25, `reel_news` +6) — Gemini 3 perçoit mieux les vidéos.
- **Gains modérés** sur `post_mood` (+2) et `post_news` (+2).
- **Régressions notables** sur `post_chiffre` (-23) et `post_selection` (-15) — Gemini 3 a tendance à les confondre avec `post_news` et `post_serie_mood_texte` respectivement. Hypothèse : Gemini 3 priorise davantage le texte d'actualité visible que le chiffre marquant comme signal.
- **Stabilité** sur les formats rares à 0% (`post_wrap_up`, `post_en_savoir_plus`) — ils restent invisibles, absorbés par les formats dominants.

Le gain net `+1.1 pt sur visual_format global` masque ces compensations. Ces régressions sur `post_chiffre` et `post_selection` deviennent des **cibles prioritaires pour la boucle HILPO** : ce sont des cas où l'instruction I_t actuelle gagne à être affinée pour mieux discriminer. Les gains sur les REELS, eux, sont structurels (modèle plus capable) et ne nécessitent pas d'optimisation supplémentaire.

### Coût détaillé

| Agent | Modèle | Appels | Tokens in | Tokens out | Latence moy. | Coût |
|-------|--------|--------|-----------|------------|--------------|------|
| Descripteur | Gemini 3 Flash Preview | 437 | 3.37M | 245K | 9.3s | **$2.42** |
| Catégorie | Qwen 3.5 Flash | 437 | 721K | 497K | 12.5s | $0.08 |
| Visual_format | Qwen 3.5 Flash | 437 | 1.55M | 382K | 10.3s | $0.13 |
| Stratégie | Qwen 3.5 Flash | 437 | 616K | 196K | 5.2s | $0.05 |
| **TOTAL** | | **1 748** | **6.26M** | **1.32M** | | **$2.68** |

Durée totale : 25.4 min (concurrence 10 posts × 20 appels API, 1748 appels au total). Coût stocké en BDD via `simulation_runs.total_cost_usd = 2.68`. Tarifs OpenRouter : Gemini 3 Flash Preview $0.50/M input + $3.00/M output, Qwen 3.5 Flash $0.065/M input/output.

### Évolution depuis le run id=2 (5 avril, baseline obsolète)

| Métrique | Run id=2 (5 avril) | Run id=7 (6 avril) | Δ |
|---|---|---|---|
| Couverture | 434/437 (99.3%) | **437/437 (100%)** | +3 posts |
| Accuracy catégorie | 87.3% | 86.7% | -0.6 pt |
| Accuracy visual_format | 64.3% | **65.4%** | +1.1 pt |
| Accuracy stratégie | 93.5% | **94.5%** | +1.0 pt |
| Visual_format FEED | 67.5% | **68.0%** | +0.5 pt |
| **Visual_format REELS** | **46.2%** | **50.8%** | **+4.6 pts** ⭐ |
| Catégorie REELS | 72.3% | **73.8%** | +1.5 pt |
| Coût total | $1.14 | $2.68 | +$1.54 (+135%) |
| Durée wall | ~5 min | 25.4 min | +20 min |

Le passage à Gemini 3 Flash Preview améliore principalement le scope **REELS visual_format (+4.6 pts)**, confirmant que le nouveau descripteur perçoit mieux les vidéos. Les axes catégorie et stratégie sont stables ou légèrement améliorés. La hausse de coût et de latence est le prix de la **fiabilité** : couverture parfaite (100%), pas d'échec sur les gros carousels jusqu'à 20 slides, pas d'effondrement sous concurrence.

### Historique de la baseline (traçabilité)

Le run id=7 est le **3e run B0** du projet — les 2 précédents ont été invalidés par des fixes de pipeline successifs :

1. **Run id=2** (5 avril, supprimé) : 87.3% / 64.3% / 93.5%, $1.14, 434/437. Configuration intermédiaire qui a révélé deux bugs cachés : (a) `response_format=json_schema` strict n'est pas honoré par Qwen sur les enums binaires (commit `0b3bd8b` a fixé le bug en revenant au tool calling), (b) Qwen 3.5 Flash a une limite carousel à ~8 images. Backup SQL conservé dans `data/backups/run_2_2026-04-06_11-32.sql`.
2. **Runs id=4, 5, 6** (6 avril, supprimés) : tous tués en cours par l'humain après détection empirique des bugs descripteurs (Qwen carousels >8 + Gemini 2.5 Flash instable sous concurrence Google AI Studio).
3. **Run id=7** (6 avril, courant) : configuration finale stabilisée — descripteur Gemini 3 Flash Preview pour les 2 scopes (commit `7e352ab`), classifieurs Qwen 3.5 Flash + tool calling, prompts v0 lockés via migration 006. **Couverture 100%, validation empirique complète.**

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
| B0 : zero-shot prompt v0 sur test | Accuracy baseline | ✅ fait — 86.7% / 65.4% / 94.5% (run id=7, 437/437, $2.68) |
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
- [x] B0 (zero-shot v0) — 86.7% / 65.4% / 94.5% (run id=7, 437/437 posts, $2.68, prompts v0 lockés via migration 006)
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
