# Protocole expérimental

## Métriques de classification

Par axe (visual_format, catégorie, stratégie) et global (3 axes corrects simultanément) :
- Accuracy
- F1 macro (insensible au déséquilibre des classes)
- F1 micro
- Matrice de confusion
- Cohen's kappa (accord modèle/humain)

Tous rapportés en moyenne ± écart-type sur 5 splits.

## Significativité statistique

- Test de McNemar (paire par paire) entre chaque méthode sur chaque split
- p-values rapportées, seuil alpha = 0.05 avec correction de Bonferroni

## Convergence

- Courbe accuracy vs nombre d'annotations (dev et test séparément)
- Plateau défini comme : variation < 2% sur les 3 dernières itérations

## Fiabilité de l'annotation

- Kappa intra-annotateur (test-retest à l'aveugle, 50+ posts)
- Kappa inter-annotateur (collaborateur Views, 500+ posts) — si disponible

## Tiers de priorité

### Tier 1 — Indispensable (jours 5-9)

| Action | Résultat attendu |
|--------|------------------|
| Annoter 2 000 posts (400/jour × 5 jours) | Ground truth complète |
| Baseline B0 : zero-shot prompt v0 sur 400 test | Accuracy, F1 macro baseline |
| Baseline B2 : few-shot 5 exemples/classe | F1 macro few-shot |
| Kappa intra-annotateur (re-swipe 50 posts) | Fiabilité ≥ 0.7 |

### Tier 2 — Nécessaire pour le claim (jours 7-10)

| Action | Résultat attendu |
|--------|------------------|
| Phase 2 : classificateur parallèle live | Prédictions stockées en BDD |
| Phase 3 : rewriter batch=30 + rollback | Prompts v1, v2, ... vN générés |
| Courbe accuracy vs annotations | **LA figure centrale du mémoire** |
| Éval prompt vN vs v0 sur split test | **LE chiffre central du mémoire** |

### Tier 3 — Renforce le claim (jours 11-13)

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

1. **Courbe de convergence** : F1 macro en Y, nombre d'annotations en X. Montrer dev ET test. Annoter les moments de rewrite (v0 → v1 → v2...).
2. **Tableau de comparaison des méthodes** : B0, B2, HILPO vN, avec F1 macro ± std sur 5 splits, p-values McNemar.
3. **Ablation batch size** : Barplot ou courbe montrant l'effet de B=1, 10, 30, 50 sur la performance finale.
4. **Matrice de confusion** : Pour l'axe le plus difficile (probablement visual_format, 44 classes), avant (v0) vs après (vN).

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
| B4 | CLIP embeddings + Logistic Regression | Supervisé | 1600 |
| B5 | CLIP embeddings + SVM | Supervisé | 1600 |
| B6 | Fine-tuning LoRA (si faisable) | Supervisé | 1600 |

## Checklist de recevabilité

### Cadrage théorique
- [ ] Problématique = hypothèses falsifiables (H1, H2)
- [ ] État de l'art ≥ 15 références (APE, DSPy, iPrOp, ProTeGi, PromptWizard)
- [ ] Positionnement explicite (3 axes)
- [ ] Formalisation mathématique de la boucle

### Protocole
- [ ] Ground truth ≥ 1600 dev + 400 test
- [ ] Kappa intra-annotateur ≥ 0.7
- [ ] 5 splits pour moyennes ± écart-type
- [ ] McNemar + Bonferroni

### Résultats
- [ ] B0 (zero-shot v0) sur 5 splits
- [ ] B2 (few-shot) sur 5 splits
- [ ] HILPO final sur 5 splits
- [ ] Courbe de convergence
- [ ] ≥ 1 ablation (batch size ou rollback)
- [ ] Matrice de confusion avant/après

### Discussion
- [ ] Classes qui bénéficient le plus
- [ ] Évolution qualitative du prompt (v0 → vN)
- [ ] Transfert zero-shot : accuracy formats vus vs jamais vus pendant l'optimisation
- [ ] Limites honnêtes
- [ ] Coût comparé (annotations, appels API, $)

### Forme
- [ ] Abstract ≤ 250 mots avec claim + résultat clé
- [ ] Bibliographie ≥ 15 références académiques
- [ ] Code reproductible (repo public, seeds fixées)
