# Phases de développement

## Phase 1 — MVP annotation manuelle
- Interface de swipe (React) — **en place** (MediaViewer, AnnotationForm, selects pré-remplis v0)
- Backend FastAPI — **architecture en couches** (routers → services → repositories)
- PostgreSQL — **opérationnel** (Docker, schéma appliqué, données importées)
- Annotation humaine seule, pas d'IA
- Produit la vérité terrain
- Page taxonomie : CRUD descriptions pour les 3 axes (formats visuels, catégories, stratégies)
- Flag "pas sûr" (touche d) + re-annotation depuis la grille
- Badges dev/test, filtre split, ordre test-first
- **Statut** : ✅ terminée — test E2E validé. Annotation en cours : 257/2000 (153 test, 35 doubtful)

## Phase 2 — Classificateur baseline
- Intégration API modèle vision
- Prompt statique v0 écrit à la main
- Le modèle prédit en parallèle de l'humain
- Mesure du taux d'accord → baseline
- **Statut** : pas commencé

## Phase 3 — Rewriter agentique
- Agent rewriter qui propose de nouvelles versions du prompt
- Prompt versionné en BDD avec CRUD
- Batching d'erreurs (B=30) avant déclenchement
- Évaluation passive sur les posts suivants
- Contribution principale du mémoire
- **Statut** : pas commencé
