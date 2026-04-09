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

- Test de McNemar (paire par paire) entre B0 et MILPO vN sur le test set
- p-values rapportées, seuil alpha = 0.05

## Protocole B0 → MILPO → BN

Le protocole repose sur la comparaison de deux runs sur le **même test set** (437 posts) :

1. **Annotation** : l'humain annote le dev (1 563 posts) en aveugle (sans voir les prédictions)
2. **B0** (fait) : prompt v0 (écrit à la main) évalué sur test → accuracy baseline
3. **Simulation MILPO** : replay séquentiel des annotations dev dans l'ordre de présentation. Protocole prequential : le prompt évolue v0 → v1 → ... → vN via le rewriter (B=30, delta=2%, patience=3).
4. **BN** : prompt vN (dernier prompt actif après convergence) évalué sur test → accuracy finale

La différence BN - B0 est directement attribuable à MILPO. Même test set, même pipeline, même descripteur, mêmes descriptions taxonomiques — seules les instructions I_t changent.

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

Ces patterns d'erreur sont des **limitations des prompts v0**, pas du modèle — c'est exactement ce que la boucle MILPO doit corriger en simulation.

### Visual_format — accuracy par format (≥ 3 occurrences test)

22 formats ont au moins 3 occurrences dans le test set, classés par fréquence :

| Format | Scope | Test | OK | Accuracy | Note |
|--------|-------|------|----|----------|------|
| post_mood | FEED | 113 | 109 | **96%** | Format dominant, parfaitement classifié |
| post_news | FEED | 111 | 78 | 70% | 22 confusions ← post_mood (anciens news sans overlay) |
| post_chiffre | FEED | 22 | 4 | **18%** | Confusion avec post_news (chiffre marquant sous-priorisé face au texte d'actualité) |
| post_quote | FEED | 21 | 17 | 81% | Bien classifié, signal "guillemets" clair |
| post_selection | FEED | 20 | 7 | **35%** | Confusion avec serie_mood_texte sur les carousels structurés |
| reel_voix_off | REELS | 17 | 15 | **88%** | Audio bien détecté par le descripteur |
| reel_news | REELS | 16 | 5 | 31% | Reels sans gabarit Views classés reel_mood |
| reel_wrap_up | REELS | 12 | 3 | **25%** | Montage post-événement partiellement détecté |
| reel_interview | REELS | 8 | 2 | 25% | Confusion avec reel_sitdown |
| post_wrap_up | FEED | 8 | 0 | 0% | Invisible — absorbé par mood |
| post_sorties_musique | FEED | 7 | 5 | 71% | Bien classifié |
| post_classement | FEED | 7 | 3 | 43% | |
| post_interview | FEED | 7 | 3 | 43% | |
| post_serie_mood_texte | FEED | 6 | 2 | 33% | |
| post_en_savoir_plus_selection | FEED | 6 | 0 | 0% | Variante non distinguée |
| post_en_savoir_plus | FEED | 5 | 0 | 0% | Invisible |
| post_article | FEED | 4 | 3 | 75% | |
| post_stills | FEED | 4 | 4 | **100%** | Parfait — screenshots distinctifs |
| post_playlist_views_essentials | FEED | 3 | 2 | 67% | |
| reel_mood | REELS | 3 | 3 | **100%** | |
| post_frise | FEED | 3 | 0 | 0% | Format rare invisible |
| post_double_selection | FEED | 3 | 3 | **100%** | |

**Observation clé** : l'architecture (descripteur Gemini 3 Flash Preview + classifieurs Qwen 3.5 Flash) n'est **pas uniforme** sur les formats :

- **FEED dominants** bien ou parfaitement classés (`post_mood` 96%, `post_quote` 81%, `post_stills` 100%) — signaux visuels clairs.
- **REELS** bien détectés quand l'audio ou le montage est distinctif (`reel_voix_off` 88%, `reel_mood` 100%), plus faibles sans gabarit identifiable (`reel_news` 31%, `reel_interview` 25%, `reel_wrap_up` 25%).
- **Confusions persistantes** sur `post_chiffre` (18%, absorbé par post_news) et `post_selection` (35%, absorbé par serie_mood_texte). Ce sont les **cibles prioritaires pour la boucle MILPO** : cas où l'instruction I_t gagne à être affinée pour mieux discriminer.
- **Formats rares invisibles** : `post_wrap_up`, `post_en_savoir_plus`, `post_en_savoir_plus_selection`, `post_frise` restent à 0% — absorbés par les formats dominants.

### Coût détaillé

| Agent | Modèle | Appels | Tokens in | Tokens out | Latence moy. | Coût |
|-------|--------|--------|-----------|------------|--------------|------|
| Descripteur | Gemini 3 Flash Preview | 437 | 3.37M | 245K | 9.3s | **$2.42** |
| Catégorie | Qwen 3.5 Flash | 437 | 721K | 497K | 12.5s | $0.08 |
| Visual_format | Qwen 3.5 Flash | 437 | 1.55M | 382K | 10.3s | $0.13 |
| Stratégie | Qwen 3.5 Flash | 437 | 616K | 196K | 5.2s | $0.05 |
| **TOTAL** | | **1 748** | **6.26M** | **1.32M** | | **$2.68** |

Durée totale : 25.4 min (concurrence 10 posts × 20 appels API, 1748 appels au total). Coût stocké en BDD via `simulation_runs.total_cost_usd = 2.68`. Tarifs OpenRouter : Gemini 3 Flash Preview $0.50/M input + $3.00/M output, Qwen 3.5 Flash $0.065/M input/output.

### Comparaison empirique avec DSPy MIPROv2 (related_work/dspy_baseline)

Pour positionner MILPO empiriquement face à l'état de l'art générique de l'optimisation de prompts, on lance DSPy MIPROv2 (zero-shot, instructions seulement) sur les **mêmes** 4 classifieurs text-only (`category`, `visual_format` FEED/REELS, `strategy`), avec deux modes : `constrained` (descriptions taxonomiques fixes, apples-to-apples avec MILPO) et `free` (MIPROv2 peut tout réécrire, borne supérieure).

Architecture : DSPy est utilisé **uniquement comme générateur de strings d'instructions** hors-ligne. Les instructions optimisées sont insérées dans `prompt_versions` avec `source='dspy_constrained'` ou `'dspy_free'` (migration 007), puis évaluées via le **runtime MILPO existant** (`run_baseline.py --prompts dspy_*`). La seule variable qui change entre B0 et B_dspy_in_milpo est la string d'instructions — le tool calling, l'async, le parsing, les posts test sont identiques. Voir [`related_work/dspy_baseline/README.md`](../related_work/dspy_baseline/README.md) pour le protocole détaillé.

#### Tableau de comparaison (à compléter après les runs)

| Run | Source instructions | Runtime éval | Catégorie | Visual_format | Stratégie | Coût | Notes |
|---|---|---|---|---|---|---|---|
| **B0** (run id=7) | Humain v0 | MILPO | **86,7%** | **65,4%** | **94,5%** | $2,68 | Référence |
| B_dspy_native_constrained | DSPy MIPROv2 | DSPy | ?? | ?? | ?? | ~$1 | Borne native, pas comparable directement à B0 (runtime ≠) |
| **B_dspy_in_milpo_constrained** | DSPy MIPROv2 | MILPO | ?? | ?? | ?? | ~$2,7 | **Apples-to-apples vs B0** — seule variable : la string d'instructions |
| B_dspy_native_free | DSPy MIPROv2 (free) | DSPy | ?? | ?? | ?? | ~$1 | Borne native upper |
| **B_dspy_in_milpo_free** | DSPy MIPROv2 (free) | MILPO | ?? | ?? | ?? | ~$2,7 | Upper bound apples-to-apples (DSPy peut réécrire les descriptions) |
| **B_milpo** (Phase 3) | MILPO boucle ProTeGi (gradient + edit + paraphrase + Successive Rejects) | MILPO | ?? | ?? | ?? | ?? | Comparaison principale vs B_dspy_in_milpo_constrained — deux méthodes d'optimisation de prompts à infrastructure identique |

#### Lectures attendues du tableau

1. **B_dspy_in_milpo_constrained vs B0** : mesure du gain (ou de la perte) de MIPROv2 par rapport aux instructions humaines, *à descriptions et runtime constants*. C'est la comparaison principale pour évaluer si MIPROv2 sait faire mieux qu'un humain expert sur ce problème.

2. **B_dspy_in_milpo_free vs B_dspy_in_milpo_constrained** : mesure du **coût (ou bénéfice) de l'invariant humain**. Si la version free fait significativement mieux, c'est que les descriptions humaines limitent le système ; si c'est égal ou pire, les descriptions humaines sont au moins aussi bonnes que ce que MIPROv2 sait écrire.

3. **B_dspy_native vs B_dspy_in_milpo (à mode constant)** : mesure de la **contribution empirique du runtime à la performance**. Si l'écart est faible, le runtime DSPy et le runtime MILPO produisent des résultats équivalents pour les mêmes instructions. Si l'écart est large, un des deux runtimes est mieux adapté aux particularités de Qwen 3.5 Flash via OpenRouter (potentiellement à cause du tool calling forcé vs parse texte).

4. **B_milpo vs B_dspy_in_milpo_constrained** : la comparaison de fond du mémoire — deux méthodes d'optimisation de prompts (boucle ProTeGi à la Pryzant et al. vs Bayesian search MIPROv2) confrontées à infrastructure strictement identique sur le même cas industriel.

**Statut** : protocole et code en place. Runs en attente — l'extension du dev split annoté (actuellement 237 posts, idéalement 400-500+) conditionne la robustesse statistique des résultats DSPy.

### Contexte de la boucle ProTeGi — format des batches d'erreurs

Quand la boucle ProTeGi se déclenche (30 erreurs accumulées sur la cible la plus erronée), trois LLMs distincts sont appelés en chaîne (`milpo/rewriter.py`).

**1. LLM_∇ (critic) — diagnostic.** Reçoit les instructions $I_t$ et le batch d'erreurs filtrées pour la cible. Pour chaque erreur :

- Le label **prédit** et le label **attendu** (annotation humaine)
- Les **features JSON** extraites par le descripteur (texte_overlay, logos, mise_en_page, etc.)
- Le **résumé visuel** du descripteur
- La **caption** du post
- La **description taxonomique** du label prédit ET du label attendu

Le critic produit exactement $m$ critiques distinctes en langage naturel — le **« gradient textuel »** au sens de Pryzant et al. — sans jamais réécrire $I_t$. Le prompt système le contraint explicitement à ne pas suggérer d'édition. Le gradient est matérialisé en BDD (`rewrite_gradients`, migration 008) avec son texte intégral, le nombre de critiques, le modèle utilisé et les coûts.

**2. LLM_δ (editor) — édition à partir du gradient.** Reçoit $I_t$, le gradient textuel, les erreurs et les descriptions taxonomiques (fixes). Produit $c$ candidats édités dans la direction sémantique opposée du gradient. Chaque candidat doit corriger au moins un défaut listé et être substantiellement différent des autres (vraie diversité, pas paraphrase). Température 0.7 pour favoriser cette diversité entre candidats.

**3. LLM_mc (paraphraser) — diversification monte-carlo.** Skippé si $p = 1$ (défaut pragmatique). Sinon prend chaque candidat de l'editor et produit $p$ paraphrases sémantiquement équivalentes (synonymes, réorganisation syntaxique, sans ajouter ni retirer de règle). Total de candidats évalués : $c \cdot p$.

**Évaluation et sélection.** Les $c$ (ou $c \cdot p$) candidats sont insérés en `prompt_versions` avec `status='draft'` et `parent_id` pointant vers l'incumbent (lineage), puis évalués en parallèle (un thread par bras) sur les 30 prochains posts dev avec leur ground truth. La fonction `multi_evaluate` gère le scope-mismatch (post FEED vs cible REELS) en propageant les matches incumbent à tous les bras concernés. Les accuracies par bras sont persistées dans `rewrite_beam_candidates.eval_accuracy`.

**Best arm identification.** La sélection finale utilise **Successive Rejects** (Audibert & Bubeck 2010, COLT), un bandit *parameter-free* recommandé par ProTeGi pour la *best arm identification*. L'implémentation post-hoc (`milpo/bandits.py`) procède en $K - 1$ phases : à chaque phase elle élimine le bras de plus faible accuracy parmi ceux qui restent, et trace le numéro de phase d'élimination dans `rewrite_beam_candidates.sr_phase`. Le winner final a `is_winner=TRUE` et `sr_phase IS NULL`.

**Promotion ou rollback.** Le winner Successive Rejects est promu si son accuracy dépasse l'incumbent de $\Delta \geq 2\%$, sinon rollback. Une row dans `rewrite_logs` est créée dans tous les cas avec `accepted = True/False` et la référence au gradient. La patience est de 3 rollbacks consécutifs avant arrêt des rewrites.

Ce découpage en 3 LLMs distincts est la **différence centrale avec le rewriter unifié** d'une approche naïve : le gradient est matérialisé comme objet indépendant, citable et auditable, et la sélection des candidats utilise un bandit honnête plutôt qu'un argmax sur un seul candidat.

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
2. **Tableau de comparaison** : B0, B2, MILPO vN, avec accuracy + F1 macro, p-value McNemar.
3. **Ablation batch size** : Barplot ou courbe montrant l'effet de B=1, 10, 30, 50 sur la performance finale.
4. **Matrice de confusion** : Pour visual_format, avant (v0) vs après (vN).

## Ablations

| ID | Variante | Variable testée |
|----|----------|-----------------|
| A0 | Prompt v0 statique | Baseline sans optimisation |
| A1 | MILPO batch=1 | Taille du batch |
| A2 | MILPO batch=10 | Taille du batch |
| A3 | MILPO batch=30 (défaut) | Configuration principale |
| A4 | MILPO batch=50 | Taille du batch |
| A5 | MILPO sans rollback | Effet du mécanisme de rollback |
| A6 | MILPO rewrite humain | LLM rewriter vs humain expert |

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
- [ ] McNemar sur B0 vs MILPO vN

### Résultats
- [x] B0 (zero-shot v0) — 86.7% / 65.4% / 94.5% (run id=7, 437/437 posts, $2.68, prompts v0 lockés via migration 006)
- [ ] B2 (few-shot)
- [ ] MILPO final (BN)
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
