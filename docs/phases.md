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
- B0 baseline : pipeline batch async sur le split test (437 posts)
- **Statut** : ⚠️ à relancer. Le B0 d'origine (run id=2, 87.3% / 64.3% / 93.5%, $1.14) utilisait les prompts v0 avant le commit `d2e84e9` (passage au JSON schema strict). Le run 2 a été supprimé de la BDD le 2026-04-06 et les prompts v0 ont été verrouillés en BDD via la migration [`006_seed_prompts_v0.sql`](../apps/backend/migrations/006_seed_prompts_v0.sql). Backup SQL conservé dans `data/backups/run_2_2026-04-06_11-32.sql`. Nouveau B0 à lancer avec les prompts v0 courants (ids 7-12 en BDD).

## Phase 3 — Rewriter agentique + simulation
- Agent rewriter qui propose de nouvelles versions des instructions I_t
- Prompt versionné en BDD avec CRUD + promotion/rollback
- Batching d'erreurs (B=30) avant déclenchement du rewriter
- **Simulation post-annotation** : l'humain annote d'abord, puis un script rejoue les annotations dans l'ordre et simule la boucle HILPO (équivalent au live sous les hypothèses du protocole)
- Évaluation passive sur les `eval_window` posts suivants (bloc consommé pour l'évaluation, non réinjecté dans le buffer) → promotion si `accuracy(candidate) >= accuracy(incumbent) + delta`
- Critère d'arrêt : `patience=3` rewrites consécutifs sans promotion (compteur global, pas par cible)
- Ablations triviales : rejouer avec B=1, 10, 30, 50 sans ré-annoter
- Contribution principale du mémoire
- Robustesse : promotion atomique (`promote_prompt`), tracking versions par run (`simulation_run_id`), contexte rewriter complet pour le descripteur
- Prompts v0 comme état initial : `run_simulation.py` charge les 6 prompts uniquement depuis la BDD via `load_prompt_state_from_db(conn)` (plus de hardcoding côté Python)
- **Statut** : implémenté et durci — rewriter.py + run_simulation.py fonctionnels, migrations 005 et 006 appliquées. En attente des annotations dev pour le run complet.
