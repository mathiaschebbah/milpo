# MILPO - Multimodal Iterative Loop Prompt Optimization

Dépôt associé au mémoire de Mathias CHEBBAH, Master 1 MIAGE, Université Paris Dauphine.

Pour prendre connaissance de la méthodologie de ce travail consulter [ce fichier](docs/human_perspective.md).

## Contexte

Dans le cadre de mon alternance chez Views, en tant que Data & AI Scientist ce projet répond au besoin de classifier automatiquement des publications Instagram (images, vidéo + légende) selon trois axes : le template visuel, la catégorie éditoriale et le type de contenu (sponsorisé ou éditorial).

**Nous répondons à la problématique suivante** : Comment concevoir et évaluer une méthode de classification multimodale pour catégoriser des publications sur les réseaux sociaux ?

## Méthode

Nous adaptons MILPO, une méthode d'optimisation itérative de prompts par gradient textuel inspirée de [ProTeGi (Pryzant et al. 2023)](https://arxiv.org/abs/2305.03495), à un cas industriel multimodal. Un annotateur humain (Mathias) classe d'abord les publications via une interface de swipe, puis un script rejoue les annotations dans l'ordre de présentation et simule la boucle d'optimisation (protocole prequential). Lorsque le modèle se trompe, un agent rewriter analyse les erreurs accumulées en mini-batch (B=30) et propose une nouvelle version du prompt, qui est promue ou rejetée par double évaluation sur un bloc d'évaluation. Les prompts sont stockés et versionnés en base de données.

L'hypothèse est que cette adaptation de ProTeGi à un cas multimodal permet d'atteindre une performance de classification satisfaisante sans recourir au fine-tuning, avec un volume d'annotations réduit et un artefact interprétable : le prompt optimisé.

## Collaboration Agent-Humain

Ce projet est également une expérimentation de collaboration entre un agent IA (Claude Code) et un humain pour un travail de recherche. L'intégralité du développement, de la conception architecturale à l'implémentation, est réalisée en binôme agent-humain, avec des **mécanismes d'interaction structurés**. La progression est traçable dans l'historique git. Les mécanismes d'interaction sont définis dans [`.claude/hooks/`](.claude/hooks/) et documentés dans [`docs/conventions.md`](docs/conventions.md).

**Tous les fichiers sont issus de cette collaboration, à l'exception de [`docs/human_perspective.md`](docs/human_perspective.md)**, où sont explicités toute ma méthode, ma démarche et mes retours d'expérience sur la collaboration agent-humain.

## Reproduction

Voir [`REPRODUCE.md`](REPRODUCE.md) pour le guide de reproduction de l'état actuel des résultats et du protocole expérimental visé.