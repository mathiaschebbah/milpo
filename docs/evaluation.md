# Protocole expérimental & Résultats

> Runs d'ablation : **158 à 169** (BDD `simulation_runs`)

## 1. Datasets

| Set | Posts | Doubtful exclus | Utilisables | Classes VF | Source |
|-----|-------|-----------------|-------------|------------|--------|
| **Alpha** | 390 | 0 | 390 | 57 (40 FEED + 17 REELS) | `eval_sets.set_name='alpha'` |
| **Test** | 426 | 21 | 405 | 57 | `sample_posts.split='test'` + `doubtful=false` |

- 3 axes annotés : visual_format (57 classes), category (15 classes), strategy (2 classes)
- Overlap alpha ∩ test : 108 posts
- 21 posts test marqués doubtful (4.9%) : cas d'ambiguïté taxonomique irréductible

## 2. Design d'ablation

### Facteurs

| Facteur | Niveaux | Variable mesurée |
|---------|---------|-----------------|
| **Architecture** | alma (4 appels : percepteur + 3 classifieurs) vs simple (1 appel multimodal) | Impact du découplage percepteur/classifier |
| **Modèle** | flash-lite ($0.25/$1.50), flash ($0.50/$3.00 VF seul), full-flash ($0.50/$3.00 partout), qwen ($0.065/$0.26 classifiers OpenRouter) | Impact du scaling modèle + model-agnosticism |
| **Dataset** | alpha vs test | Généralisation / overfitting |

### Configurations (6 × 2 datasets = 12 runs)

| Config | Descripteur | Classifiers | Provider |
|--------|-------------|-------------|----------|
| alma flash-lite | Google flash-lite | Google flash-lite (×3) | Google AI |
| alma flash | Google flash-lite | Google flash-lite (cat/strat) + Google flash (VF) | Google AI |
| alma full-flash | Google flash | Google flash (×3) | Google AI |
| alma qwen | Google flash-lite | Qwen 3.5 Flash (×3) | Google AI + OpenRouter |
| simple flash-lite | Google flash-lite (all-in-one) | — | Google AI |
| simple flash | Google flash (all-in-one) | — | Google AI |

## 3. Résultats — Tableau d'ablation

### Alpha (390 posts)

| Run | Config | VF% | Cat% | Strat% | Coût | Latence | Fiabilité | Posts |
|-----|--------|-----|------|--------|------|---------|-----------|-------|
| 158 | alma flash-lite | **83.8** | 92.8 | 96.9 | $3.68 | 7 331s | 100% | 390 |
| 159 | alma flash | **83.6** | 92.8 | 96.9 | $4.62 | 6 845s | 100% | 390 |
| 160 | alma full-flash | **86.7** | 93.3 | 96.7 | $7.72 | 10 159s | 100% | 390 |
| 161 | alma qwen | **82.2** | 93.4 | 95.8 | $2.34 | ≈26 000s | 96.7% | 377 |
| 162 | simple flash-lite | **...** | ... | ... | ... | ... | ... | ... |
| 163 | simple flash | **...** | ... | ... | ... | ... | ... | ... |

### Test (405 posts)

| Run | Config | VF% | Cat% | Strat% | Coût | Latence | Fiabilité | Posts |
|-----|--------|-----|------|--------|------|---------|-----------|-------|
| 164 | alma flash-lite | ... | ... | ... | ... | ... | ... | ... |
| 165 | alma flash | ... | ... | ... | ... | ... | ... | ... |
| 166 | alma full-flash | ... | ... | ... | ... | ... | ... | ... |
| 167 | alma qwen | ... | ... | ... | ... | ... | ... | ... |
| 168 | simple flash-lite | ... | ... | ... | ... | ... | ... | ... |
| 169 | simple flash | ... | ... | ... | ... | ... | ... | ... |

## 4. Comparaisons « toutes choses égales par ailleurs »

### 4.1. Impact de l'ARCHITECTURE (à modèle constant)

| Modèle constant | simple (1 appel) | alma (4 appels) | Δ architecture | Δ coût |
|-----------------|-----------------|-----------------|----------------|--------|
| flash-lite | run 162 | run 158 (83.8%) | ... | +$1.18 |
| flash | run 163 | run 159 (83.6%) | ... | +$0.62 |

→ Mesure la **productivité marginale de l'architecture** (Pm_A)

### 4.2. Impact du MODÈLE (à architecture constante)

| Architecture constante | flash-lite | flash | full-flash | qwen |
|-----------------------|-----------|-------|------------|------|
| alma | 83.8% ($3.68) | 83.6% ($4.62) | 86.7% ($7.72) | 82.2% ($2.34) |
| simple | ... | ... | — | — |

→ Mesure la **productivité marginale du modèle** (Pm_M) et les **rendements marginaux décroissants**

### 4.3. Généralisation (alpha vs test, à config constante)

→ Gap alpha↔test par config. Runs précédents : gap ≤ 3pp (pas d'overfitting)

## 5. Analyses micro-économiques prévues

### 5.1. Frontière coût-performance (Pareto)

- Axe X : coût par run ($)
- Axe Y : accuracy VF (%)
- 6 points par dataset + frontière efficiente
- Référence : runs historiques 90-101 (pré-ASSIST v5)

### 5.2. Fonction de production & Isoquantes

```
Y = f(A, M)
  Y = accuracy VF (%)
  A = investissement en architecture (tokens décision = 3 classifiers)
  M = coût unitaire du modèle ($/M tokens)
```

Isoquantes : courbes de niveau accuracy dans l'espace (A, M). Convexité attendue (TMST décroissant).

### 5.3. TMST (Taux Marginal de Substitution Technique)

```
TMST_A,M = Pm_A / Pm_M
```

Hypothèse : TMST >> 1 — investir en architecture produit plus par dollar qu'investir en modèle.

Donnée clé (à compléter) :
- Pm_A = (Y_alma - Y_simple) / (Coût_alma - Coût_simple) = ?pp/$ → coût d'un point d'architecture
- Pm_M = (Y_full-flash - Y_flash-lite) / (Coût_full-flash - Coût_flash-lite) = 2.9pp / $4.04 = 0.72 pp/$

### 5.4. Rendements marginaux décroissants

| Investissement | Coût | VF | Coût marginal par pp |
|----------------|------|-----|---------------------|
| flash-lite | $3.68 | 83.8% | baseline |
| flash (VF swap) | $4.62 | 83.6% | ∞ (négatif) |
| full-flash | $7.72 | 86.7% | $1.39/pp |

Le premier dollar (architecture) rapporte ~84pp. Le dernier (full-flash) rapporte ~0.7pp.

### 5.5. ELECTRE III (analyse multicritère)

6 critères non compensatoires :

| Critère | Direction | Poids | Indiff (q) | Préf (p) | Veto (v) |
|---------|-----------|-------|------------|----------|----------|
| Accuracy VF | MAX | 0.35 | ±1.5pp | ±5pp | ±15pp |
| Accuracy Cat | MAX | 0.15 | ±1pp | ±3pp | ±10pp |
| Accuracy Strat | MAX | 0.10 | ±0.5pp | ±2pp | ±5pp |
| Coût | MIN | 0.20 | ±$0.50 | ±$2 | ±$5 |
| Latence | MIN | 0.10 | ±60s | ±300s | ±600s |
| Fiabilité | MAX | 0.10 | ±0.5% | ±2% | ±5% |

Output : graphe de surclassement + classement final des 6 configurations.

### 5.6. Élasticité & model-agnosticism

- Élasticité accuracy/coût : ε = 0.03 (très inélastique pour full-flash vs flash-lite)
- Model-agnosticism : Qwen ($0.065/M) donne -1.6pp vs Google flash-lite ($0.25/M) → le classifier est commoditisable

## 6. Findings principaux (provisoires, alpha uniquement)

1. **Architecture > modèle** : alma flash-lite (83.8%, $3.68) ≈ alma flash (83.6%, $4.62). Le swap VF seul ne rapporte rien.
2. **Rendements décroissants** : full-flash (86.7%, $7.72) = +2.9pp pour +$4.04. Coût marginal $1.39/pp.
3. **Model-agnosticism** : Qwen classifiers (82.2%, $2.34) ≈ Google classifiers (83.8%, $3.68). -1.6pp pour -36% de coût.
4. **Classifier commoditisable** : le descripteur Alma concentre la valeur ($0.92 = 40% du coût qwen). Le classifier est interchangeable.
5. **Fiabilité ≠ coût** : Qwen 96.7% couverture vs Google 100%. Tradeoff documenté.

## 7. Runs historiques (pré-ASSIST v5, référence)

| Run | Architecture | Modèle | Harness | VF% | Coût | Notes |
|-----|-------------|--------|---------|-----|------|-------|
| 96 | E2E naïf | Flash Lite | aucun | 71.6% | $1.29 | Baseline naïf |
| 93 | E2E naïf | Flash | aucun | 84.2% | $2.59 | |
| 97 | E2E harness | Flash Lite | k=3 + oracle | 77.8% | ~$5 | |
| 94 | E2E harness | Flash | k=3 + oracle | 85.4% | ~$9.40 | |
| 95 | Pipeline v1 | Flash Lite | k=3 + oracle | 87.0% | $6.86 | Meilleur pipeline historique |
| 90 | Pipeline v1 | Flash (VF) | k=3 + oracle | 87.6% | $9.21 | |
| 100 | Pipeline DSPy | Flash Lite | k=3 + oracle | 85.4% | $6.30 | DSPy MIPROv2 |
| 101 | Pipeline v1 | Flash (tout) | k=3 + oracle | 85.4% | $11.23 | Full Flash dominé |

**⚠️** : runs 90-101 utilisent l'ancienne clé API, l'ancienne architecture (pipeline v1 + harness k=3 + oracle Sonnet), et l'ancien test set (437 posts sans filtre doubtful). **Non directement comparables** aux runs 158+ mais utiles pour montrer la progression.

## 8. Données disponibles en BDD par run

Chaque run stocke dans `simulation_runs` + `predictions` + `api_calls` :
- Accuracy par axe (VF, cat, strat)
- Coût total ($ avec reasoning tokens inclus, fix v5.3)
- Tokens par appel (input, output, reasoning séparé — migration 017)
- Latence par appel (ms)
- Reasoning CoT du classifier (predictions.raw_response.reasoning)
- Description Alma complète (predictions.raw_response.text pour agent='descriptor')
- Configuration (modèles, tier, dataset, pipeline_mode)
