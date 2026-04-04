# Phases de développement

## Phase 1 — MVP annotation manuelle
- Interface de swipe (React) — à créer
- Backend FastAPI — **squelette en place** (routers posts, annotations)
- PostgreSQL — **opérationnel** (Docker, schéma appliqué)
- Annotation humaine seule, pas d'IA
- Produit la vérité terrain
- **Statut** : en cours

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
