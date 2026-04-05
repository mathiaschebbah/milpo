# État de l'art

## 1. Optimisation automatique de prompts

Approches entièrement automatiques, sans signal humain dans la boucle d'optimisation.

| Travail | Année | Venue | Méthode | Différence avec HILPO |
|---------|-------|-------|---------|----------------------|
| **APE** (Zhou et al.) | 2023 | ICLR | Génération + sélection automatique d'instructions | Pas de human feedback |
| **DSPy / MIPROv2** (Khattab et al.) | 2024 | ICLR | Bootstrapping + recherche bayésienne | Pipeline programmatique, pas d'humain |
| **ProTeGi** (Pryzant et al.) | 2023 | EMNLP | Gradient textuel pour raffiner les prompts | Feedback automatique, pas humain |
| **PO2G** | 2025 | AI Journal | Deux gradients (FP/FN) pour classification | Signaux d'erreur séparés, pas d'humain |
| **PromptWizard** (Agarwal et al.) | 2025 | ACL Findings | Self-evolving + critique-synthèse | Entièrement automatique |
| **EvoPrompt** | 2024 | — | Algorithme évolutionnaire sur les prompts | Pas de signal humain |

**Point commun** : ces méthodes optimisent le prompt en utilisant un dataset labellé existant ou un signal automatique (métriques, LLM-as-judge). HILPO se différencie en construisant le dataset labellé *pendant* l'optimisation, via l'annotateur humain.

## 2. Optimisation de prompts avec humain dans la boucle

Approches où un humain intervient dans le processus d'optimisation — concurrents directs.

| Travail | Année | Venue | Méthode | Différence avec HILPO |
|---------|-------|-------|---------|----------------------|
| **iPrOp** (Li & Klinger) | 2025 | ACL SRW | Interface interactive, l'humain choisit parmi des prompts candidats | L'humain intervient sur le *prompt* (choix global), pas sur les *annotations* (correction instance-par-instance). Texte seul. |
| **PROMST** (MIT REALM) | 2024 | EMNLP Oral | Human feedback rules pour tâches multi-étapes agents | Pas de classification. Tâches agentiques, pas de taxonomie fixe. |

**iPrOp est le concurrent le plus proche.** La distinction clé : dans iPrOp, l'humain est un sélectionneur de prompts. Dans HILPO, l'humain est un annotateur de données. Le signal d'erreur HILPO est plus granulaire (correction par instance vs choix entre prompts candidats).

## 3. Classification multimodale sur réseaux sociaux

Travaux sur la classification de contenus social media combinant image et texte.

| Travail | Année | Venue | Pertinence |
|---------|-------|-------|------------|
| Sanchez Villegas et al. | 2024 | EACL Findings | Classification multimodale de posts sociaux |
| **SoMeLVLM** (Zhang et al.) | 2024 | ACL Findings | LLM vision pour traitement de contenus social media |
| Nguyen et al. (memes multimodal) | 2025 | JMIR | Classification multimodale de memes |
| **CLIP** (Radford et al.) | 2021 | ICML | Vision-langage zero-shot, baseline pour comparaison |

## Tableau de positionnement

| Dimension | APE / DSPy / ProTeGi | iPrOp | HILPO (nous) |
|-----------|---------------------|-------|-------------|
| Signal d'optimisation | Automatique (métriques) | Humain (choix de prompt) | Humain (annotations) |
| Granularité du feedback | Agrégée (accuracy globale) | Globale (prompt entier) | Instance-par-instance |
| Modalité | Texte | Texte | Multimodal (image + texte) |
| Type de taxonomie | Benchmarks académiques | Benchmarks académiques | Taxonomie métier subjective |
| Artefact produit | Prompt optimisé | Prompt sélectionné | Prompt optimisé + données annotées |
| Nécessite un dataset labellé | Oui (existant) | Non | Non (construit pendant l'optimisation) |

## 4. Protocole d'évaluation séquentielle

| Travail | Année | Venue | Pertinence |
|---------|-------|-------|------------|
| **Dawid** | 1984 | JRSS-A | Introduit l'évaluation **prequential** (predictive sequential) : chaque observation est d'abord prédite puis utilisée pour mettre à jour le modèle. Justifie notre protocole de simulation. |
| Gama et al. | 2013 | ACM CS | Survey sur l'apprentissage en flux de données. Formalise le prequential comme standard d'évaluation pour les modèles adaptatifs. |

HILPO adopte le protocole prequential : chaque post dev est d'abord classifié avec le prompt courant (évaluation), puis l'annotation humaine est révélée et nourrit le buffer d'erreurs (apprentissage). Cela évite le besoin d'un validation set séparé dans le split dev, tout en garantissant qu'aucune donnée n'est utilisée pour optimiser avant d'avoir servi à évaluer.

## Références

1. Zhou et al. (2023). *Large Language Models Are Human-Level Prompt Engineers.* ICLR 2023.
2. Khattab et al. (2024). *DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines.* ICLR 2024.
3. Pryzant et al. (2023). *Automatic Prompt Optimization with "Gradient Descent" and Beam Search.* EMNLP 2023.
4. Li & Klinger (2025). *iPrOp: Interactive Prompt Optimization for LLMs with a Human in the Loop.* ACL SRW 2025.
5. Chen et al. (2024). *PROMST: Integrating Human Feedback and Heuristic-based Sampling.* EMNLP 2024.
6. Agarwal et al. (2025). *PromptWizard: Task-Aware, Feedback-Driven Self-Evolving Prompts.* ACL Findings 2025.
7. PO2G (2025). *Prompt Optimization with Two Gradients for Classification.* AI Journal 2025.
8. Sanchez Villegas et al. (2024). *Improving Multimodal Classification of Social Media Posts.* EACL Findings 2024.
9. Zhang et al. (2024). *SoMeLVLM: A Large Vision Language Model for Social Media Processing.* ACL Findings 2024.
10. Radford et al. (2021). *Learning Transferable Visual Models From Natural Language Supervision.* ICML 2021.
11. Dawid, A. P. (1984). *Present Position and Potential Developments: Some Personal Views — Statistical Theory — The Prequential Approach.* Journal of the Royal Statistical Society, Series A, 147(2), 278–292.
12. Gama, J., Žliobaitė, I., Bifet, A., Pechenizkiy, M., & Bouchachia, A. (2014). *A Survey on Concept Drift Adaptation.* ACM Computing Surveys, 46(4), 1–37.
