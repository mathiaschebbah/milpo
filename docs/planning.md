# Planning — 5 au 18 avril 2026

> Deadline : **vendredi 18 avril 2026**

## Semaine 1 — Infrastructure + annotation + classificateur

### Sam 5 avril — Phase A (infrastructure) ✅
- ~~Splits dev/test assignés~~ ✅
- ~~Ordre de présentation déterministe~~ ✅
- ~~Backend + frontend opérationnels~~ ✅
- Test end-to-end : annoter quelques posts, vérifier en BDD

### Dim 6 — Annotation sprint 1
- Objectif : **400 posts** annotés
- Sessions de 45min avec pauses

### Lun 7 — Annotation sprint 2 + début Phase 2
- Matin : **400 posts** (cumulé : 800)
- Après-midi : intégration API Qwen 3.5, prompt v0 statique, logging api_calls

### Mar 8 — Phase 2 live + début rewriter
- Classificateur actif en parallèle de l'annotation
- **400 posts** (cumulé : 1200)
- Après-midi : commencer l'agent rewriter

### Mer 9 — Phase 3 : boucle HILPO
- Matin : finir rewriter + batching (B=30) + rollback
- Après-midi : activer la boucle HILPO live
- **400 posts** (cumulé : 1600)

### Jeu 10 — Finir l'annotation
- **400 posts** (cumulé : 2000)
- Re-swipe 50 posts à l'aveugle (kappa intra-annotateur)
- Collaborateur Views : lancer ses 500 posts (si dispo)
- Vérifier intégrité des données

### Ven 11 — Évaluation finale live
- 400 posts test × prompt v0 (baseline) + prompt vN (optimisé)
- Logger tous les appels API (800 appels éval)
- Première lecture des résultats

## Semaine 2 — Simulations + baselines + rédaction

### Sam 12 — Script de simulation
- Script de rejeu automatique (annotations fixées, seed variable)
- Tester sur 1 split

### Dim 13 — Simulations + A6
- 5 splits × 6 ablations = **30 runs** automatiques
- A0 : prompt statique, A1-A4 : batch 1/10/30/50, A5 : sans rollback
- A6 (rewrite humain) : ~2-3h de réécriture manuelle sur 1 split

### Lun 14 — Baselines
- B0 : zero-shot prompt v0 (déjà fait, extraire résultats)
- B1 : zero-shot CLIP
- B2-B3 : few-shot in-context (5 et 10 exemples/classe)
- B4 : CLIP embeddings + Logistic Regression (5 splits)
- B5 : CLIP embeddings + SVM (5 splits)
- Kappa inter-annotateur (si collaborateur Views a terminé)

### Mar 15 — Métriques et figures
- Métriques sur 5 splits (moyenne ± std)
- Tests de McNemar + Bonferroni
- Figures : convergence, courbes d'apprentissage, ablations, matrices confusion, coûts
- Tableaux : comparaison méthodes, ablations, p-values, coûts, kappa

### Mer 16 — Rédaction partie 1
- Introduction, problématique, positionnement
- Méthode (formalisation, algorithme, architecture)
- Protocole expérimental

### Jeu 17 — Rédaction partie 2
- Résultats (figures + tableaux)
- Discussion, analyse qualitative du prompt, limites
- Perspectives

### Ven 18 — Finalisation + rendu
- Relecture, abstract, bibliographie
- **Rendu**

## Annotation par jour

| Jour | Posts | Cumulé | Phase |
|------|-------|--------|-------|
| Dim 6 | 400 | 400 | Phase 1 |
| Lun 7 | 400 | 800 | Phase 1 → 2 |
| Mar 8 | 400 | 1200 | Phase 2 |
| Mer 9 | 400 | 1600 | Phase 2 → 3 |
| Jeu 10 | 400 | 2000 | Phase 3 |

## Appels API estimés

| Poste | Appels |
|-------|--------|
| Classification live | ~2000 |
| Rewriter | ~65 |
| Éval finale (test × v0 + vN) | ~800 |
| Simulations (30 runs × ~65) | ~1950 |
| Baselines few-shot | ~800 |
| **Total** | **~5615** |
