# Projet

Mémoire de fin d'études de Mathias Chebbah (Master 1 MIAGE, Université Paris Dauphine), en alternance chez Views (média gen-z).

MILPO est une boucle d'optimisation s'inspirant de ProTeGi (Pryzant et al. 2023), utilisant les capacités multimodales de Gemini 3 Flash Preview (descripteur), Qwen 3.5 Flash (classifieurs) et GPT-5.4 (rewriter). L'idée est simple : on utilise l'apport de ProTeGi pour régler le problème de classification multimodale de Views, sur un corpus Instagram dont seule une petite fraction (~10%) peut être annotée manuellement. On a beaucoup de comparaisons : 60 formats visuels, 15 catégories éditoriales et 2 stratégies (Organic / Brand Content). On veut régler ce problème car l'annotation est coûteuse, donc on ne peut pas tout annoter ; on veut une généralisation sur un petit dataset.

> Les volumes exacts (nombre total de posts, taille des splits dev/test, nombre d'annotations) sont accessibles en BDD via `/setup` — ils évoluent au fil des imports et des sessions d'annotation, et ne sont volontairement pas figés ici.

## Problématique

Comment construire et optimiser un pipeline de classification multimodale pour catégoriser le corpus Instagram de Views selon une taxonomie métier subjective (60 formats visuels, 15 catégories éditoriales, 2 stratégies), en maximisant la performance sur un budget d'annotations limité (≈10% du dataset) ?

## Hypothèses

> **H1 — Convergence empirique** : la boucle MILPO (gradient textuel par mini-batch B=30 + rollback sur double évaluation) améliore significativement (p < 0.05, test de McNemar) le baseline B0 (prompts v0 zero-shot) sur le split test, après optimisation sur le split dev annoté.

> **H2 — Robustesse au transfert** : le prompt vN (final après optimisation sur le dev) conserve ≥ 90% des gains observés sur le dev quand il est appliqué au split test non vu pendant l'optimisation.

> **H3 — Efficacité multimodale** : l'architecture en deux étapes (descripteur multimodal + 3 classifieurs text-only en parallèle) permet de réduire le coût d'inférence (tokens images/vidéos payés une seule fois) tout en préservant la qualité de classification par rapport à une approche directe avec un seul LLM multimodal.

## Positionnement

MILPO se positionne comme une **adaptation méthodologique** de ProTeGi (Pryzant et al. 2023) à un cas industriel multimodal. Trois éléments le distinguent des travaux existants :

1. **Adaptation multimodale d'un optimiseur de prompt par gradient textuel.** ProTeGi opère sur du texte pur, sur 4 datasets de classification binaire (Ethos hate speech, Liar fake news, ArSarcasm, jailbreak detection). MILPO adapte le paradigme à un pipeline multimodal (image + vidéo + audio + caption) via un découpage **descripteur multimodal + 3 classifieurs text-only en parallèle**, qui économise le coût des tokens visuels (payés une seule fois par post) et améliore la traçabilité des features extraites. Voir [related_work.md](related_work.md) pour la comparaison méthodologique détaillée avec ProTeGi.

2. **Étude empirique sur taxonomie métier subjective à longue traîne.** Les benchmarks ProTeGi sont des classifications binaires sur des datasets publics équilibrés. MILPO évalue sur une taxonomie multi-classe (60 formats visuels en scope FEED/REELS + 15 catégories éditoriales + 2 stratégies) construite par un média réel (Views), avec une distribution en loi de puissance : 8 formats couvrent 82% du dataset, 19 formats à ≤ 1 occurrence dans le test. Cette différence de structure de tâche est qualitativement plus difficile et plus représentative des cas d'usage industriels.

3. **Pipeline production-ready et reproductible.** MILPO est implémenté de bout en bout : annotation par interface swipe (frontend React), backend FastAPI, BDD PostgreSQL versionnée par migrations, signature GCS V4 pour les médias privés, prompts versionnés et tracés par run de simulation, ablations rejouables sans réannotation. L'ensemble est open-source et documenté pour reproduction (voir [REPRODUCE.md](../REPRODUCE.md)).

## Claim visé

> Nous adaptons l'optimiseur de prompt par gradient textuel (ProTeGi, Pryzant et al. 2023) à un pipeline de classification multimodale industriel chez le média Views. Sur le corpus Instagram de Views, avec un budget d'annotation manuelle limité (≈10% du dataset, réparti en splits dev/test figés), nous évaluons MILPO sur 3 axes de classification (60 formats visuels en scope FEED/REELS, 15 catégories éditoriales, 2 stratégies Organic/Brand Content). Le baseline B0 (prompts v0 zero-shot, run id=7 en BDD) atteint **86,7% / 65,4% / 94,5%** (catégorie / format visuel / stratégie) sur le split test. Nous étudions empiriquement (i) l'effet de l'optimisation MILPO sur ces accuracies, (ii) l'efficacité en annotations (combien d'annotations pour atteindre un plateau de performance ?), (iii) la robustesse au transfert (conservation des gains sur le split test non vu pendant l'optimisation), et (iv) la sensibilité à la taille de batch (ablations B=1, 10, 30, 50). L'analyse qualitative documente quels types d'erreurs sont corrigés par la boucle d'optimisation et lesquels résistent — en particulier sur les formats à faible support (longue traîne).

## Contraintes

- **Deadline mémoire** : 18 avril 2026
- **Livrable** : rapport de mémoire + code fonctionnel + résultats expérimentaux reproductibles
- **État des phases** : Phase 1 ✅ (infra annotation + split test annoté intégralement, annotation dev en cours — volumes à jour accessibles en BDD via `/setup`). Phase 2 ✅ — pipeline descripteur (Gemini 3 Flash Preview) + 3 classifieurs (Qwen 3.5 Flash + tool calling), **B0 stabilisé : 86,7% / 65,4% / 94,5% (run id=7, $2.68, 25,4 min)**, prompts v0 lockés en BDD via la migration [`006_seed_prompts_v0.sql`](../apps/backend/migrations/006_seed_prompts_v0.sql). Phase 3 ✅ implémentée côté code (rewriter GPT-5.4 + simulation prequential, `load_prompt_state_from_db` — plus de hardcoding), run complet sur le dev en attente de la fin des annotations.
