# État de l'art

## 1. ProTeGi — voisin méthodologique principal

> *Le projet MILPO a été conçu comme une solution pragmatique au problème de classification multimodale chez Views, sans connaissance préalable de la littérature sur l'optimisation de prompts. La parenté méthodologique avec ProTeGi (Pryzant et al. 2023) a été identifiée a posteriori, lors de la rédaction du mémoire. Cette section explicite cette filiation et compare les deux méthodes point par point.*

### 1.1 Présentation de ProTeGi

ProTeGi (*Prompt Optimization with Textual Gradients*) propose une méthode d'optimisation automatique de prompts inspirée de la descente de gradient numérique, mais opérant dans l'espace textuel. L'algorithme utilise des **mini-batches** d'exemples d'erreurs pour produire des "gradients" en langage naturel — des descriptions textuelles des défauts du prompt actuel — qui sont ensuite "propagés" dans le prompt par édition dans la direction sémantique opposée. La recherche est guidée par un **beam search** sur l'espace des prompts, et la sélection des candidats utilise des algorithmes de **best arm identification** (UCB Bandits, Successive Rejects). Les auteurs rapportent une amélioration jusqu'à +31% sur le prompt initial et +4-8% par rapport aux baselines Monte Carlo et Reinforcement Learning, sur 4 tâches de classification binaire (Ethos hate speech, Liar fake news, ArSarcasm, jailbreak detection) avec gpt-3.5-turbo comme modèle base.

### 1.2 Architecture interne de ProTeGi

ProTeGi décompose la boucle d'optimisation en **3 LLMs distincts** :

- **Critic** ($LLM_\nabla$) : reçoit le prompt courant + un batch d'erreurs, produit le "gradient textuel" (description des défauts)
- **Editor** ($LLM_\delta$) : reçoit le prompt courant + le gradient + les erreurs, produit plusieurs prompts candidats améliorés
- **Paraphraser** ($LLM_{mc}$) : génère des variantes monte-carlo des candidats pour explorer l'espace local

Hyperparamètres utilisés dans le papier : minibatch de 64 exemples, beam width $b=4$, search depth $r=6$ steps, 4 gradients par groupe d'erreurs, 8 successors samplés avant bandit selection, 3 trials par tâche.

### 1.3 Comparaison MILPO ↔ ProTeGi

| Composant | ProTeGi | MILPO |
|---|---|---|
| **Optimiseur** | Mini-batch d'erreurs + gradient textuel | Mini-batch d'erreurs (B=30) + gradient textuel séparé (LLM_∇) |
| **Nombre de LLMs dans la boucle** | 3 (critic + editor + paraphraser) | 3 (critic + editor + paraphraser) |
| **Sélection des candidats** | Beam search ($b=4$) + bandits (UCB / Successive Rejects) | Successive Rejects (Audibert & Bubeck 2010) sur $c \cdot p$ candidats post-édition, puis promotion si $\Delta$accuracy ≥ 2%, sinon rollback |
| **Search depth** | 6 steps fixes | Variable (jusqu'à `patience=3` rewrites consécutifs sans promotion) |
| **Modalité** | Texte uniquement | Multimodal (image + vidéo + audio + texte) |
| **Architecture pipeline** | 1 LLM (prompt → classification) | 2 étapes : descripteur multimodal Gemini 3 Flash Preview + 3 classifieurs Qwen 3.5 Flash en parallèle |
| **Type de tâche** | Classification binaire (4 datasets) | Classification multi-classe (60 formats + 15 catégories + 2 stratégies) |
| **Données** | Datasets publics labellés (50 dev + 150 test par tâche) | Dataset construit par annotation humaine (1 563 dev + 437 test) |
| **Métrique** | F1 binaire | Accuracy + F1 macro multi-classe |
| **Modèle base** | gpt-3.5-turbo (jan 2023) | Gemini 3 Flash Preview + Qwen 3.5 Flash + GPT-5.4 (critic/editor/paraphraser) |
| **Hyperparamètres** | $m=4, c=8, p=2, b=4, r=6$ | $m=3, c=4, p=1$ par défaut (pragmatique, cost-driven) ; ablation paper $m=4, c=8, p=2$ via `--protegi-paper-defaults` |
| **Trials** | 3 par tâche | 1 run principal + ablations sur B (1, 10, 30, 50) |
| **Domaine** | Benchmarks académiques (safety / NLP) | Cas industriel réel (Views, taxonomie métier subjective) |
| **Implémentation** | Script de recherche | Pipeline production-ready (BDD versionnée, frontend, async, traçabilité) |

### 1.4 Ce que MILPO emprunte ET adapte

**Primitives ProTeGi reprises telles quelles** (cf. `milpo/rewriter.py` et `milpo/bandits.py`) :

- **Gradient textuel séparé** : un LLM_∇ (critic) dédié produit $m$ critiques en langage naturel à partir d'un batch d'erreurs, sans jamais éditer le prompt. Le gradient est matérialisé en BDD (`rewrite_gradients`, migration 008) et citable verbatim dans l'analyse qualitative.
- **Édition à partir du gradient** : un LLM_δ (editor) reçoit le prompt + le gradient + les erreurs et génère $c$ candidats édités dans la direction sémantique opposée des critiques. Température 0.7 pour encourager la diversité entre candidats.
- **Paraphrase monte-carlo** : un LLM_mc (paraphraser) prend chaque candidat editor et produit $p$ paraphrases sémantiquement équivalentes pour augmenter la diversité du pool. Skippé si $p = 1$.
- **Best arm identification par Successive Rejects** : sélection parameter-free du meilleur candidat parmi les $c$ (ou $c \cdot p$) bras, sur le même eval window de 30 posts forward. Référence : Audibert & Bubeck 2010.
- **Mini-batch + édition itérative** : accumuler $B = 30$ erreurs avant de déclencher un step ProTeGi, dans le paradigme prequential (cf. §6).
- **Rollback sur double évaluation** : ne pas promouvoir le winner Successive Rejects s'il n'améliore pas l'incumbent d'au moins $\Delta \geq 2\%$.

**Adaptations spécifiques au cas industriel multimodal** :

- **Pipeline en deux étapes** : descripteur multimodal (Gemini 3 Flash Preview) + 3 classifieurs text-only (Qwen 3.5 Flash) en parallèle, pour économiser le coût des tokens visuels (payés une seule fois par post) et améliorer la traçabilité des features extraites. ProTeGi est text-only pur.
- **Multi-classe vs binaire** : extension à 60 classes (formats visuels) avec longue traîne, vs 2 classes équilibrées chez ProTeGi. L'ambiguïté entre classes proches devient un enjeu central qualitativement absent du papier.
- **Cas industriel réel** : taxonomie métier subjective construite par un média (Views), vs benchmarks académiques équilibrés.
- **Beam local par cible** : MILPO a 6 prompts (descripteur×2, category, vf×2, strategy). À chaque trigger, `pick_rewrite_target()` choisit la cible la plus erronée et le step ProTeGi opère sur ce seul prompt. La « profondeur de recherche $r$ » du papier est implicite : c'est le nombre total de triggers sur la passe prequential. Cette adaptation préserve l'invariant « un seul prompt actif par (agent, scope, source) » de MILPO.
- **Hyperparamètres pragmatiques** : $m = 3, c = 4, p = 1$ par défaut (vs $m = 4, c = 8, p = 2$ pour le paper). Coût d'évaluation multimodal ≈ 4 LLM par post × ~5 bras × 30 posts par trigger, ce qui justifie de réduire le pool initial. Ablation paper-faithful disponible via `--protegi-paper-defaults`.
- **Pipeline production-ready** : BDD versionnée, frontend d'annotation, GCS V4 Signed URLs, async pipeline, traçabilité des coûts API par run, ablations rejouables sans réannotation. ProTeGi est un script de recherche.

**Limite cost-driven** : MILPO n'effectue qu'**un seul run principal** par configuration d'hyperparamètres, là où ProTeGi moyenne sur 3 trials par tâche. La contrainte est le coût API multimodal (~$21 par run dev complet en hyperparams pragmatiques, ~$50–70 en paper-faithful).

---

## 2. Optimisation automatique de prompts (autres travaux)

Approches d'optimisation automatique de prompts qui ne sont pas notre voisin direct (ProTeGi), mais qui définissent le champ.

| Travail | Année | Venue | Méthode | Différence avec MILPO |
|---------|-------|-------|---------|----------------------|
| **APE** (Zhou et al.) | 2023 | ICLR | Génération + sélection automatique d'instructions par Monte Carlo | Pas de structure de gradient, recherche non directionnelle |
| **DSPy / MIPROv2** (Khattab et al.) | 2024 | ICLR | Bootstrapping de few-shot + recherche bayésienne sur instructions | Framework programmatique de pipelines, pas centré sur le gradient textuel |
| **PO2G** | 2025 | AI Journal | Deux gradients séparés pour faux positifs et faux négatifs | Variante de ProTeGi pour classification déséquilibrée |
| **PromptWizard** (Agarwal et al.) | 2025 | ACL Findings | Self-evolving + critique-synthèse récursive | Approche évolutionnaire avec auto-critique |
| **EvoPrompt** | 2024 | — | Algorithme évolutionnaire (croisement, mutation) sur les prompts | Sans signal de gradient, exploration purement génétique |

**Point commun avec ProTeGi (et MILPO)** : ces méthodes optimisent un prompt à partir d'un signal d'erreur, sur un dataset labellé. **Différence avec MILPO** : aucune n'est multimodale, et toutes sont évaluées sur des benchmarks académiques équilibrés (pas sur une taxonomie métier subjective à longue traîne).

### 2.1 Comparaison empirique : DSPy MIPROv2 sur le pipeline MILPO

**Pourquoi DSPy est le voisin le plus proche.** DSPy/MIPROv2 (Khattab et al., ICLR 2024) couvre nativement la majorité des besoins de MILPO : pipelines multi-stage, optimisation conjointe de plusieurs prompts, petits datasets labellés, support multimodal récent (`dspy.Image`). Sur le plan méthodologique, MIPROv2 utilise une recherche bayésienne sur des candidats d'instructions générés par un LLM proposer, ce qui n'est pas un gradient textuel à la ProTeGi/MILPO mais qui poursuit le même objectif (trouver la meilleure instruction étant donné un signal d'erreur sur un trainset).

**Protocole empirique.** On applique DSPy MIPROv2 aux 4 classifieurs text-only de MILPO (`category`, `visual_format` FEED, `visual_format` REELS, `strategy`), en gelant le descripteur multimodal (qui utilise des features déjà cachées en BDD pour le test split). On produit deux ensembles de prompts optimisés :

| Mode | Surface optimisée | Comparable à MILPO ? |
|---|---|---|
| **constrained** | Instructions seulement, descriptions taxonomiques fixes (`dspy.InputField`) | ✅ apples-to-apples — MILPO ne touche pas non plus les descriptions (cf. `milpo/rewriter.py:46`) |
| **free** | Tout — descriptions injectées dans le docstring de la signature, MIPROv2 peut tout réécrire | ❌ asymétrique — borne supérieure / mesure du « coût de l'invariant humain » |

**Architecture cruciale : DSPy = générateur, MILPO = runtime d'évaluation.** Pour que les chiffres soient comparables à B0, on n'évalue pas les prompts optimisés dans le runtime DSPy (qui utilise un parsing texte avec marqueurs `[[ ## field ## ]]`), mais dans le runtime MILPO existant (`scripts/run_baseline.py`, qui fait du tool calling Qwen forcé avec enum fermé). On insère les instructions DSPy dans la table `prompt_versions` avec `source='dspy_constrained'` ou `'dspy_free'` (migration 007), et on lance `run_baseline.py --prompts dspy_*`. Cette stratégie garantit que la **seule variable qui change entre B0 et B_dspy_in_milpo est la string d'instructions** — le runtime, le tool calling, l'async, le parsing, les posts test, tout est identique.

En bonus, on lance aussi une évaluation native DSPy sur les mêmes programmes compilés. La différence `B_dspy_native_{mode} − B_dspy_in_milpo_{mode}` mesure empiriquement la contribution du runtime à la performance et alimente la discussion méthodologique : « voilà combien de points le runtime a coûté ou gagné, indépendamment de la qualité des instructions ».

**Statut** : protocole et code en place (cf. [`related_work/dspy_baseline/`](../related_work/dspy_baseline/)), runs en attente d'un dev split annoté plus complet. Voir `docs/evaluation.md` pour le tableau comparatif des chiffres.

---

## 3. Optimisation de prompts avec humain dans la boucle

Approches où un humain intervient explicitement dans le processus d'optimisation. Ces travaux sont méthodologiquement éloignés de MILPO (qui n'a pas d'humain dans la boucle d'optimisation après l'annotation initiale), mais sont mentionnés pour clarifier le positionnement.

| Travail | Année | Venue | Méthode | Différence avec MILPO |
|---------|-------|-------|---------|----------------------|
| **iPrOp** (Li & Klinger) | 2025 | ACL SRW | Interface interactive : l'humain choisit entre des prompts candidats générés automatiquement | Dans iPrOp, l'humain est *dans la boucle d'optimisation* (sélection en temps réel). Dans MILPO, l'humain est *hors boucle* (annote les données en amont, puis la boucle est entièrement automatique). |
| **PROMST** (MIT REALM) | 2024 | EMNLP Oral | Human feedback rules pour tâches multi-étapes agents | Tâches agentiques (pas de classification fixe). Pas de taxonomie. |

**Note importante sur le positionnement de MILPO** : malgré le "Loop" dans son nom (Multimodal **Iterative Loop** Prompt Optimization), MILPO n'est **pas** un système human-in-the-loop au sens strict de la littérature (iPrOp, PROMST). L'humain intervient en amont (annotation des 2 000 posts du sample) et en aval (analyse des résultats), mais pas pendant la boucle d'optimisation elle-même, qui est entièrement automatique (rewriter LLM + métriques calculées + rollback). Le "Loop" fait référence à la boucle d'optimisation par mini-batch, pas à une interaction humain-machine en temps réel.

---

## 4. Classification multimodale sur réseaux sociaux

Travaux sur la classification de contenus social media combinant image et texte. Ces travaux sont pertinents comme **comparaison de domaine d'application** (multimodal social media), pas comme voisins méthodologiques.

| Travail | Année | Venue | Pertinence |
|---------|-------|-------|------------|
| Sanchez Villegas et al. | 2024 | EACL Findings | Classification multimodale de posts sociaux (méthodes supervisées classiques) |
| **SoMeLVLM** (Zhang et al.) | 2024 | ACL Findings | LLM vision pour traitement de contenus social media (modèle dédié) |
| Nguyen et al. (memes multimodal) | 2025 | JMIR | Classification multimodale de memes (santé) |
| **CLIP** (Radford et al.) | 2021 | ICML | Vision-langage zero-shot, baseline pour comparaison empirique |

---

## 5. Tableau de positionnement

| Dimension | ProTeGi | iPrOp | MILPO |
|---|---|---|---|
| **Méthode d'optimisation** | Gradient textuel + beam search + bandit | Sélection humaine entre prompts candidats | Gradient textuel séparé + édition + paraphrase + Successive Rejects + rollback |
| **Nombre de LLMs dans la boucle** | 3 (critic + editor + paraphraser) | 1 + humain | 3 (critic + editor + paraphraser) |
| **Granularité du signal** | Mini-batch d'erreurs | Choix global de prompt | Mini-batch d'erreurs |
| **Modalité** | Texte | Texte | Multimodal (image + vidéo + audio + texte) |
| **Type de tâche** | Classification binaire (4 tâches) | Classification binaire | Classification multi-classe (60 formats + 15 catégories + 2 stratégies) |
| **Type de dataset** | Benchmarks académiques (50 dev + 150 test par tâche) | Benchmarks académiques | Cas industriel réel (1 563 dev + 437 test, taxonomie métier subjective à longue traîne) |
| **Humain dans la boucle d'optimisation** | Non | Oui (sélection en temps réel) | Non (annotations en amont) |
| **Implémentation** | Script de recherche | Interface interactive | Pipeline production-ready (BDD, frontend, async, traçabilité) |

---

## 6. Protocole d'évaluation séquentielle

Le protocole d'évaluation utilisé par MILPO s'appuie sur le **paradigme prequential** (predictive sequential), introduit par Dawid (1984) et formalisé comme standard pour les modèles adaptatifs en streaming par Gama et al. (2014).

| Travail | Année | Venue | Pertinence |
|---|---|---|---|
| **Dawid** | 1984 | JRSS-A | Introduit l'évaluation prequential : chaque observation est d'abord prédite (test) puis utilisée pour mettre à jour le modèle (train). Justifie le protocole MILPO. |
| **Gama et al.** | 2014 | ACM CS | Survey sur l'apprentissage en flux de données. Formalise le prequential comme standard d'évaluation pour les modèles adaptatifs. |

MILPO adopte le protocole prequential : chaque post dev est d'abord classifié avec le prompt courant (évaluation), puis l'annotation humaine est révélée et nourrit le buffer d'erreurs (apprentissage). Cela évite le besoin d'un validation set séparé dans le split dev, tout en garantissant qu'aucune donnée n'est utilisée pour optimiser avant d'avoir servi à évaluer.

---

## Références

1. Pryzant, R., Iter, D., Li, J., Lee, Y. T., Zhu, C., & Zeng, M. (2023). *Automatic Prompt Optimization with "Gradient Descent" and Beam Search.* EMNLP 2023. arXiv:2305.03495.
2. Zhou, Y., Muresanu, A. I., Han, Z., Paster, K., Pitis, S., Chan, H., & Ba, J. (2023). *Large Language Models Are Human-Level Prompt Engineers.* ICLR 2023.
3. Khattab, O., Singhvi, A., Maheshwari, P., Zhang, Z., Santhanam, K., Vardhamanan, S., et al. (2024). *DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines.* ICLR 2024.
4. Li, J., & Klinger, R. (2025). *iPrOp: Interactive Prompt Optimization for LLMs with a Human in the Loop.* ACL SRW 2025. arXiv:2412.12644.
5. Chen, Y., et al. (2024). *PROMST: Integrating Human Feedback and Heuristic-based Sampling.* EMNLP 2024.
6. Agarwal, E., et al. (2025). *PromptWizard: Task-Aware, Feedback-Driven Self-Evolving Prompts.* ACL Findings 2025.
7. PO2G (2025). *Prompt Optimization with Two Gradients for Classification.* AI Journal 2025.
8. Sanchez Villegas, D., et al. (2024). *Improving Multimodal Classification of Social Media Posts.* EACL Findings 2024.
9. Zhang, X., et al. (2024). *SoMeLVLM: A Large Vision Language Model for Social Media Processing.* ACL Findings 2024.
10. Radford, A., et al. (2021). *Learning Transferable Visual Models From Natural Language Supervision.* ICML 2021.
11. Dawid, A. P. (1984). *Present Position and Potential Developments: Some Personal Views — Statistical Theory — The Prequential Approach.* Journal of the Royal Statistical Society, Series A, 147(2), 278–292.
12. Gama, J., Žliobaitė, I., Bifet, A., Pechenizkiy, M., & Bouchachia, A. (2014). *A Survey on Concept Drift Adaptation.* ACM Computing Surveys, 46(4), 1–37.
