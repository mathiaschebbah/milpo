# MILPO - Multimodal Iterative Loop Prompt Optimization

Dépôt associé au mémoire de Mathias CHEBBAH, Master 1 MIAGE, Université Paris Dauphine.

La note de sur l'utilisation de l'IA est disponible dans [ce fichier](docs/note_intelligence_artificielle.md).

## Contexte

Dans le cadre de mon alternance chez Views, en tant que Data & AI Scientist ce projet répond au besoin de classifier automatiquement des publications Instagram (images, vidéo + légende) selon trois axes : le template visuel, la catégorie éditoriale et le type de contenu (sponsorisé ou éditorial).

**Nous répondons à la problématique suivante** : Comment concevoir et évaluer une méthode de classification multimodale pour catégoriser des publications sur les réseaux sociaux ?

## Méthode

Nous proposons MILPO, une méthode d'optimisation itérative de prompts par gradient textuel inspirée de [ProTeGi (Pryzant et al. 2023)](https://arxiv.org/abs/2305.03495), adaptée un cas industriel multimodal. Un annotateur humain classe d'abord les publications via une interface de swipe, puis un script rejoue les annotations dans l'ordre de présentation et simule la boucle d'optimisation (protocole prequential). Lorsque le modèle se trompe, un agent rewriter analyse les erreurs accumulées en mini-batch (B=30) et propose une nouvelle version du prompt, qui est promue ou rejetée par double évaluation sur un bloc d'évaluation. Les prompts sont stockés et versionnés en base de données.

L'hypothèse est que cette adaptation de ProTeGi à un cas multimodal permet d'atteindre une performance de classification satisfaisante sans recourir au fine-tuning, avec un volume d'annotations réduit et un artefact interprétable : le prompt optimisé.

## Reproduction

Voir [`REPRODUCE.md`](REPRODUCE.md) pour le guide de reproduction de l'état actuel des résultats et du protocole expérimental visé.