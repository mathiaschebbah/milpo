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
- **Statut** : ✅ terminée — test E2E validé. Split test annoté (437/437). Split dev : 104 annotés en Phase 1, le reste s'annote pendant la boucle HILPO (Phases 2-3).

## Phase 2 — Classificateur baseline
- Pipeline 2 étapes : descripteur multimodal → 3 classifieurs text-only en parallèle
- Descripteur FEED : Qwen 3.5 Flash via OpenRouter (image + vidéo)
- Descripteur REELS : Gemini 2.5 Flash via OpenRouter (vidéo + audio)
- Classifieurs : Qwen 3.5 Flash text-only, tool use avec enum fermé
- Schema features JSON (résumé visuel libre + champs structurés)
- 6 prompts v0 écrits à la main (2 descripteur + 3 classifieurs + 1 stratégie)
- Le modèle prédit en parallèle de l'humain **sur le split dev**
- L'humain annote les posts dev au fil de l'eau — chaque annotation est comparée à la prédiction du modèle
- Mesure du taux d'accord → baseline
- **Statut** : architecture validée, implémentation pas commencée

## Phase 3 — Rewriter agentique
- Agent rewriter qui propose de nouvelles versions du prompt
- Prompt versionné en BDD avec CRUD
- Batching d'erreurs (B=30) avant déclenchement
- Évaluation passive sur les posts suivants
- Contribution principale du mémoire
- **Statut** : pas commencé
