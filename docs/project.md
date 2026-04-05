# Projet

Mémoire de fin d'études de Mathias Chebbah (Master 1 MIAGE, Université Paris Dauphine), en alternance chez Views (média gen-z).

Système d'annotation agentique pour classifier des posts Instagram via une boucle humain-dans-la-boucle qui optimise itérativement le prompt du classificateur. Le système remplace une heuristique de classification v0 (imprécise) par une pipeline performante, applicable en production chez Views.

## Problématique

Comment optimiser itérativement un prompt de classification multimodale en exploitant le feedback d'un annotateur humain, de manière à surpasser un zero-shot tout en limitant le volume d'annotations nécessaire ?

## Hypothèses

> **H1** : L'optimisation itérative d'un prompt par confrontation avec un annotateur humain (boucle HILPO, batch B=30) permet d'atteindre une accuracy de classification multimodale significativement supérieure au zero-shot (p < 0.05), avec un volume d'annotations ≤ 200 par axe de classification.

> **H2** : Le prompt optimisé par HILPO constitue un artefact interprétable et transférable : appliqué à un split test non vu pendant l'optimisation, il conserve ≥ 90% de sa performance par rapport au split dev.

## Positionnement

HILPO se distingue des travaux existants sur **quatre axes** :

1. **L'humain annote les données, pas le prompt.** Contrairement à iPrOp (Li & Klinger, 2025) où l'humain choisit entre des prompts candidats, dans HILPO l'humain corrige les classifications. Le signal d'erreur est plus fin : correction instance-par-instance, pas choix global entre instructions.

2. **Domaine multimodal à taxonomie subjective.** Les 44 formats visuels et 15 catégories éditoriales de Views sont des classes définies par un média, pas par un benchmark académique. La taxonomie est instable, culturellement située — un terrain où l'oracle humain est plus précieux que les métriques automatiques.

3. **Le prompt est l'artefact final, avec séparation explicite.** Le prompt HILPO est composé de deux blocs : les descriptions taxonomiques (rédigées par l'expert métier, fixes) et les instructions de classification (optimisées par la boucle). Contrairement au fine-tuning, l'artefact est lisible, auditable et transférable. On peut analyser précisément ce que la boucle a appris (instructions) vs ce que l'humain savait déjà (descriptions).

4. **Transfert zero-shot via les descriptions.** Contrairement aux approches supervisées qui nécessitent des exemples d'entraînement pour chaque classe, HILPO peut classifier des formats jamais rencontrés pendant l'optimisation — il suffit qu'une description textuelle existe dans le prompt. L'optimisation des instructions généralise au-delà des classes vues : un format rare absent du dev peut être correctement classifié dans le test grâce à sa description. C'est un avantage structurel par rapport aux baselines supervisées (CLIP + LogReg, few-shot) qui échouent nécessairement sur les classes sans exemples.

## Claim visé

> Nous proposons HILPO, une méthode d'optimisation itérative de prompts guidée par un annotateur humain pour la classification multimodale de contenus sur les réseaux sociaux. Sur un corpus de 2 000 publications Instagram annotées selon 3 axes (44 formats visuels, 15 catégories éditoriales, 2 stratégies), nous montrons que HILPO atteint un F1 macro de [X]% avec [Y] annotations, là où le zero-shot plafonne à [Z]% et le few-shot 5-shot atteint [W]%. Le prompt optimisé, artefact interprétable et versionné, conserve [V]% de sa performance sur le split test non vu pendant l'optimisation. L'analyse qualitative révèle que les gains proviennent principalement de [insight clé].

## Contraintes

- **Deadline** : 18 avril 2026
- **Livrable** : rapport de mémoire + code fonctionnel + résultats expérimentaux
- **État au 5 avril 2026** : Phase 1 ✅ (541 annotations, test complet). Phase 2 ✅ (pipeline descripteur + classifieurs, B0 : 87.3% / 64.3% / 93.5%). Phase 3 : rewriter à implémenter.
