# Classification multimodale de posts Instagram par orchestration de LLM : étude d'ablation architecture × modèle × harness

Dépôt associé au mémoire de Mathias CHEBBAH, Master 1 MIAGE, Université Paris Dauphine.

La note sur l'utilisation de l'IA est disponible dans [ce fichier](docs/note_intelligence_artificielle.md).

## Contexte

Dans le cadre de mon alternance chez Views (@viewsfrance), en tant que Data & AI Scientist, ce projet répond au besoin de classifier automatiquement des publications Instagram (images, vidéos + légende) selon trois axes : le format visuel (42 classes), la catégorie éditoriale (15 classes) et la stratégie (organique vs sponsorisé).

**Problématique** : Comment concevoir et évaluer une pipeline de classification multimodale par LLM pour catégoriser des publications sur les réseaux sociaux, et quels composants apportent réellement de la valeur ?

## Méthode

Nous proposons une pipeline multi-étapes (descripteur multimodal → classifieurs text-only spécialisés) avec harness engineering (self-consistency k=3, oracle cascade) et prompt engineering domaine-spécifique (VETO triggers, exemples canoniques). Une ablation factorielle croise 2 modèles (Gemini 3.1 Flash Lite $0.25/M vs Gemini 3 Flash $0.50/M) × 3 modes (E2E naïf, E2E harness, pipeline complète) pour isoler l'effet de chaque composant.

**Résultat principal** : l'architecture et le harness engineering sont des multiplicateurs de capacité qui absorbent le gap de performance entre les modèles. Un petit modèle bien orchestré (87.0% vf, $6.86) bat un gros modèle en appel direct (85.4% vf, $9.40) pour moins cher. Le delta modèle passe de +12.6pp (E2E naïf) à +0.6pp (pipeline complète).

## Reproduction

Voir [`REPRODUCE.md`](REPRODUCE.md) pour le guide de reproduction de l'état actuel des résultats et du protocole expérimental visé.