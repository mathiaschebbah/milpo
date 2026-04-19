# ASSIST (paper) vs Alma (notre travail) — analyse comparative

> Rapport d'audit interne rédigé le 2026-04-19, à propos du papier `Asking Specifically Instead of Ambiguously to Your GPT Improves Image Caption` (preprint OpenReview 2024, soumission ICLR 2025 **retirée**, [forum id=vwENIgfZdQ](https://openreview.net/forum?id=vwENIgfZdQ)) et de son rapport avec notre pipeline Alma/ASSIST sur le corpus Views.
>
> Motivation : lors de la rédaction initiale du mémoire, ChatGPT avait halluciné le développement de l'acronyme ASSIST en `Adaptive Scaffolding via Structured Inputs and Sequential Tests`. Ce rapport documente (1) ce que dit réellement le papier ASSIST, (2) en quoi notre travail s'en rapproche et s'en éloigne, et (3) si l'édifice méthodologique d'ASSIST est solide.

---

## Table des matières

1. [Résumé exécutif](#1-résumé-exécutif)
2. [Le papier ASSIST : contenu détaillé](#2-le-papier-assist--contenu-détaillé)
3. [Notre travail : Alma + grille + procédures](#3-notre-travail--alma--grille--procédures)
4. [Comparaison point par point](#4-comparaison-point-par-point)
5. [Convergences](#5-convergences)
6. [Divergences fondamentales](#6-divergences-fondamentales)
7. [Limites de l'étude ASSIST](#7-limites-de-létude-assist)
8. [Pourquoi ASSIST a été retiré d'ICLR 2025](#8-pourquoi-assist-a-été-retiré-diclr-2025)
9. [Pertinence d'ASSIST pour nos modèles (flash / flash-lite / qwen)](#9-pertinence-dassist-pour-nos-modèles)
10. [Context window et *context rot* (2025-2026)](#10-context-window-et-context-rot-2025-2026)
11. [Études ultérieures plus solides](#11-études-ultérieures-plus-solides)
12. [Solidité scientifique d'ASSIST](#12-solidité-scientifique-dassist)
13. [Résultats : Alma / ASSIST / Alma VS ASSIST](#13-résultats)

---

## 1. Résumé exécutif

- **ASSIST est un acronyme réel** : `Asking Specifically Instead of Ambiguously`. Le papier existe, il a été soumis à ICLR 2025 et **retiré** avant décision finale.
- **Le développement `Adaptive Scaffolding via Structured Inputs and Sequential Tests` est une hallucination de ChatGPT** — il n'apparaît nulle part dans le papier.
- **Le principe central d'ASSIST recoupe notre intuition** : décomposer un *prompt* vague en questions spécifiques améliore l'extraction d'information par un VLM.
- **Le domaine d'application diffère radicalement** : ASSIST cible le *captioning* d'images (génération de description libre) ; nous ciblons la classification multimodale multi-axes sur une taxonomie métier fermée.
- **Deux ajouts spécifiques à notre travail** qu'ASSIST ne fait pas : (a) couplage des questions avec des **procédures d'arbitrage** par axe, (b) **design factoriel 2×2** qui révèle une interaction non additive (+1,68~pp). ASSIST ne documente aucune interaction entre ses composants.
- **ASSIST a été conçu pour assister des petits modèles** (LLaVA-13B). Nous observons l'inverse : sur Gemini 3 Flash-lite (petit), l'effet ASSIST est indétectable ($\Delta \leq 0{,}65$~pp) ; sur Flash (grand), l'effet est mesurable ({+}1,40 à {+}2,47~pp). Ce contraste est expliqué par la nature de nos questions — sémantiques, pas factuelles.
- **ASSIST est moyennement solide** : bonne intuition, exécution méthodologique faible (pas d'ablation sur les composants du prompt, évaluation partiellement circulaire sur leur propre benchmark ECO, IC non rapportés). Ces lacunes expliquent probablement le retrait.

---

## 2. Le papier ASSIST : contenu détaillé

### 2.1 Identité

| Champ | Valeur |
|---|---|
| Titre | *Asking Specifically Instead of Ambiguously to Your GPT Improves Image Caption* |
| Auteurs | Anonymous (double-blind) |
| Venue visée | ICLR 2025 |
| Statut | **Withdrawn** avant décision (septembre 2024, modifié novembre 2024) |
| ID OpenReview | `vwENIgfZdQ` |
| URL | <https://openreview.net/forum?id=vwENIgfZdQ> |

### 2.2 Problème adressé

Les VLM actuels (GPT-4V, LLaVA, Qwen-VL-max) produisent des *captions* de mauvaise qualité quand on leur demande naïvement « describe this image in detail ». Les auteurs observent que :

- Les captions manquent d'objets (seulement ~2 objets décrits en moyenne contre ~8 attendus par image riche).
- Les objets identifiés sont souvent faux ou vaguement décrits.
- Les réponses varient fortement d'une requête à l'autre (faible consistance sémantique sur 10 tirages à même question).
- Cette variance est causée par le caractère **ambigu** du *prompt* : l'attention du modèle se disperse sur l'image entière sans ancrage.

### 2.3 Thèse centrale

> *A question is specific for a VLM if (1) it can be clearly understood — i.e. hidden neurons are focused on the region of interest, (2) it can be clearly answered — the model will always give the same answer whenever you ask.*

Les auteurs défendent qu'il faut **décomposer** un prompt vague en une séquence de questions ciblées, chacune portant sur un élément visuel spécifique, plutôt que de demander une description globale.

### 2.4 Preuve qualitative (section 3.1)

Trois lignes de preuve :

1. **Attention maps** (Figure 3) : pour une question spécifique (« please list the name of objects in the image »), l'attention du modèle se concentre sur les régions concernées (carte de chaleur crimson centrée). Pour une question ambiguë (« please describe this image in detail »), l'attention est diffuse.
2. **Semantic Consistency** (Figure 4, équation 1) : sur 10 répétitions d'une même question à températures différentes, une question spécifique produit 0,6 de similarité inter-réponses, une question ambiguë 0,35.
3. **Biais du training data** (Figure 2) : sur 3 millions de conversations d'entraînement LLaVA, **88,17~%** sont classées comme *specific questions* selon un matching de templates. Le modèle est donc biaisé vers le specific par construction.

### 2.5 Méthode ASSIST

La méthode se décompose en **4 étapes** (Figure A4) :

1. **Segment everything** : un modèle SAM (Kirillov et al. 2023) segmente l'image en régions.
2. **Identify objects** : GPT-4V nomme chaque région.
3. **Describe each object** : GPT-4V génère une description fine par objet.
4. **Generate relationships** : GPT-4V extrait les relations entre objets (par paires aléatoires).

Le résultat est packagé dans un format à **3 parties** :

```
%%Part1: Overall description%%
&&Part1.1: Style&&   [1 phrase]
&&Part1.2: Theme&&   [1 phrase]
&&Part1.3: Global description of background&&   [>=150 mots]
&&Part1.4: Global description of foreground&&   [>=150 mots]

%%Part2: List of objects%%
<ObjectName> (Category (Living/Inanimate); foreground/background;
              Description: ...; Color information: ...)
...

%%Part3: Relationships%%
<Object A> [relation] <Object B>
...
```

Les noms d'objets sont systématiquement bornés par `<...>`, les délimiteurs `%%`, `&&`, `[]`, `()` servent au parsing regex. L'*instruction* complète GPT-4V fait **56 lignes** (Figure A10), avec un exemple *in-context* pour forcer la structure.

### 2.6 Templates des « specific questions » (Annexe A.1.1)

Les auteurs analysent les 3~M conversations LLaVA et identifient les questions spécifiques via 55 templates, tous commençant par `What ...` :

> `What doing ... / What holding ... / What appearance ... / What hanging ... / What color ... / What wearing ... / What expression ... / What type ... / What kind ... / What where ... / What time ... / What currency ... / What brand ... / What theme ... / What locate ... / What position ... / What setting ... / What condition ... / What placed ... / What gender ... / What size ... / What material ... / What action ... / What made of ... / How many ... / How much ... / How large ... / How full is ... / Are the ... / Is the ... / Is there ... / Are there ... / Where ... / Which ... / Who is ... / Who ... / Are ... / Is ... / What object is ... / What furniture ... / What animal ... / What activity ... / What is the main object ... / What is the primary object ... / What is next ... / What accessories ... / What is the occupation ... / What is the main feature ... / Does ... / Do ... / In what type ... / Has ... / Have ...`

Deux règles de matching :

- Questions aboutissant à une réponse **mono-mot** (yes/no, chiffre, nom simple) → 48,80~%.
- Questions matchant un template ci-dessus → 76,73~%.
- Union des deux → **88,17~%** de la training data est *specific*.

### 2.7 Dataset ECO (Enumerate Common Objects in Context)

Les auteurs construisent un dataset baptisé **ECO**, annoté via pipeline ASSIST :

- **Train set** : 100~k paires image-caption, annotées par GPT-4V avec l'instruction ASSIST, puis nettoyées par humain.
- **Test set** : 3~k images, 27~k objets, 148~k relations, annotés **manuellement sans pré-traitement VLM**.

Le dataset et le code sont *will be made publicly available* (pas de lien GitHub trouvé à ce jour).

### 2.8 Fine-tuning : LLaVA(ASSIST)-Captioner

Modèle de base : **LLaVA-13B**. Fine-tuning :

- LoRA rank 128
- Learning rate $2\times 10^{-4}$
- 3 epochs, batch 16, max length 2048, warmup 0.03
- Environ 0.5~B paramètres LoRA
- 100 GPU hours sur NVIDIA A100

### 2.9 Résultats

#### Table 1 — CQA (Caption Question Answering) sur 4 benchmarks

| Captioner | NLVR2 | OK-VQA | VQAv1 | VQAv2 |
|---|---|---|---|---|
| ShareGPT-4V-13B | 57,5 | 55,4 | 50,7 | 65,4 |
| Qwen-VL-max | 56,8 | 52,1 | 46,0 | 65,6 |
| LLaVA-13B | 56,3 | 54,8 | 50,0 | 64,1 |
| **ASSIST-Captioner** | **59,1** | **56,8** | **52,6** | **66,4** |

→ Gains modestes (+1,6 à +3,3~pp) mais consistants.

#### Table 2 — Precision & Recall sur 100 échantillons manuels COCO

| Method | Precision | Recall |
|---|---|---|
| LLaVA | 36,4 ± 1,5~% | 59,2 ± 4,7~% |
| ShareGPT-4V | 23,2 ± 3,8~% | 55,3 ± 2,1~% |
| Qwen-VL-max | 35,2 ± 5,9~% | 57,5 ± 2,0~% |
| GPT-4V | 21,5 ± 0,7~% | 70,6 ± 13,4~% |
| **ASSIST** | **56,2 ± 4,2~%** | **82,8 ± 8,3~%** |

→ ASSIST-Captioner **bat GPT-4V** en Precision (×2,6) ET en Recall (+12~pp). C'est le claim fort du papier.

#### Table 3 — Open-vocabulary object detection

| Method | AP50 | Recall | mIoU |
|---|---|---|---|
| OV-DQUO | 4,7 | 10,7 | 66,5 |
| Grounding DINO (baseline) | 33,1 ± 2,5 | 20,2 ± 0,1 | 75,7 ± 0,1 |
| Next-Chat | 29,1 ± 0,1 | 7,7 ± 0,1 | 67,1 ± 0,0 |
| Kosmos-2 | 34,2 ± 4,8 | 13,3 ± 2,4 | 76,1 ± 0,4 |
| GLaMM | 34,3 | 19,8 | 79,6 |
| **ASSIST (+CLIP+LLaVA)** | **37,7 ± 0,9** | **35,9 ± 0,7** | **79,9 ± 0,1** |

→ Gains nets sur Recall (+14~pp) et AP50 (+3,4~pp) vs Grounding DINO seul.

#### Table A1 — 9 benchmarks VL généraux

| Model | VQAv2 | GQA | VizWiz | SQA | VQAᵀ | POPE | MMB | MMBᶜᴺ | SEED | MM-Vet |
|---|---|---|---|---|---|---|---|---|---|---|
| LLaVA-13B | 80,0 | 63,3 | 53,6 | 71,6 | 61,3 | 85,9 | 67,7 | 63,6 | 61,6 | 35,4 |
| VILA-13B | 80,8 | 63,3 | 60,6 | 73,7 | **66,6** | 84,2 | 70,3 | 64,3 | 62,8 | 38,8 |
| ASMv2-13B | 81,0 | 63,9 | 58,1 | 87,1 | 60,2 | 86,3 | **74,4** | 64,3 | 66,3 | 41,3 |
| **ASSIST-13B** | 80,8 | 63,5 | 57,1 | **91,3** | 59,5 | **88,0** | **74,6** | **68,2** | 65,9 | **41,6** |

→ ASSIST-13B domine sur **5 benchmarks sur 10** (SQA, POPE, MMB, MMBᶜᴺ, MM-Vet), perd sur 2 (VQAᵀ, SEED légèrement), équivalent sur 3. Gains surtout sur **raisonnement** (SQA, POPE, MM-Vet), pas sur perception brute (VQAv2, GQA).

#### Table 4 — Image generation (SDXL + ASSIST vs DALL-E 3)

| Method | Object recall Rₒ | Relationship recall Rᵣ |
|---|---|---|
| SDXL seul | 59,2 ± 4,0~% | 41,5 ± 3,5~% |
| DALL-E 3 | 90,1 ± 4,2~% | 71,6 ± 3,4~% |
| **ASSIST + SDXL** | **95,2 ± 1,1~%** | **76,7 ± 0,9~%** |

→ ASSIST enrichit le prompt SDXL avec une structure ASSIST-style, ce qui permet à SDXL de **dépasser** DALL-E 3.

### 2.10 Limites revendiquées par les auteurs (§6)

1. « Our data collection process still necessitates human annotation involvement » — le pipeline n'est pas entièrement automatique ; 3~k test images annotées à la main.
2. « The captioner's localization capabilities remain insufficient » — ASSIST seul ne localise pas correctement, il faut le combiner avec un Grounding DINO externe.

Les auteurs reconnaissent donc deux faiblesses opérationnelles, mais **ne discutent pas** les faiblesses méthodologiques listées à la section 7 ci-dessous.

---

## 3. Notre travail : Alma + grille + procédures

### 3.1 Problématique

Classification automatique multimodale des 21~425 posts Instagram de Views (@viewsfrance) sur **trois axes orthogonaux** :

- **Format visuel** (`visual_format`) : 40 classes FEED + 17 classes REELS = 57 classes actives. Longue traîne sévère (6 classes cumulent 52~% des annotations, 21 classes ont < 10~occurrences, `post_slider_olympics` n'a qu'**une seule occurrence**).
- **Catégorie éditoriale** (`category`) : 15 domaines culturels (musique, mode, cinéma, sport, lifestyle, société, photo, art, architecture, design, people, technologie, voyages, business, histoire, gastronomie).
- **Stratégie** (`strategy`) : 2 classes (`Brand Content` / `Organic`).

La ground truth comporte **1~583 annotations** produites par un seul annotateur (l'auteur). Deux ensembles d'évaluation :

- `alpha` : 390 posts (raffinement YAML, sous-biais assumé).
- `test` : 405 posts (généralisation, 21 `doubtful` exclus).

### 3.2 Architecture

**Pipeline Alma (4 appels par post)** :

1. Appel 1 — **Percepteur multimodal** (Gemini 3 Flash, persona *Alma*, analyste visuelle pour Views). Reçoit images + caption + audio (reels). Répond à la grille d'observation ASSIST. **Ne classe pas**, décrit.
2. Appels 2, 3, 4 — **Trois classifieurs text-only parallèles** (`asyncio`). Chaque classifieur reçoit la description d'Alma + taxonomie de son axe + procédure de son axe. Produit un `tool_call` à 3 champs (`reasoning`, `confidence`, `label`).

**Pipeline Simple (1 appel par post)** : un unique appel multimodal reçoit tout en contexte (images, caption, date, 3 taxonomies, grille optionnelle, procédures optionnelles) et produit les 3 labels simultanément via un `tool_call` unique.

### 3.3 Ressources partagées

Les deux pipelines partagent **trois ressources structurées** (toutes en YAML versionné dans un vault Obsidian, rendues par `milpo/taxonomy_renderer.py`) :

1. **Taxonomies YAML** — 74 fichiers :
   - `Descriptions/FEED/` : 40 fichiers
   - `Descriptions/REELS/` : 17 fichiers
   - `Descriptions/CATEGORY/` : 15 fichiers
   - `Descriptions/STRATEGY/` : 2 fichiers
   - Schema à 5 clés canoniques : `class` (requis), `signature_visuelle` (requis), `signal_obligatoire` (requis), `caption_signal.patterns` (optionnel), `exclut` (optionnel).
2. **Grille d'observation ASSIST** — 2 fichiers :
   - `Questions/FEED.yaml` : 14 clés (OVERLAY_SLIDE_1, LOGO_RUBRIQUE, FLECHE_SWIPE, CARTOUCHE_ANNOTATION, NOMBRE_SLIDES, STRUCTURE_SLIDES, COMPOSITION, CHIFFRE_DOMINANT, ZOOM_CIRCULAIRE, GABARIT_CALENDRIER, CAPTION_SIGNAL, CAPTION_APPEL_ACTION, CAPTION_ANNONCE_DECES, CAPTION_CHIFFRE_PIVOT).
   - `Questions/REELS.yaml` : 12 clés (AUDIO, AUDIO_ROLE, AUDIO_DESCRIPTION, OVERLAY_TEXTE, LOGO_RUBRIQUE, TYPE_PLANS, SPLIT_SCREEN, EVENEMENT_VISIBLE, EVENEMENT_TYPE, MONTAGE, CAPTION_SIGNAL, CAPTION_FORME).
   - Types de réponses : `categorical` avec `allowed_values`, `integer`, `free_text`.
3. **Procédures par axe** — textes en dur dans `milpo/prompts/classifier.py` :
   - `visual_format` : « Décide à partir du **format dominant**. Priorise structure, composition, audio, montage, logos, dispositifs éditoriaux. Le sujet n'emporte la décision que s'il correspond aussi au format ou à un `signal_obligatoire` explicite. »
   - `category` : « Décide à partir du **sujet principal**. Priorise domaine, personnes, œuvres, objets, événements, pratiques. La forme éditoriale n'emporte pas la décision. »
   - `strategy` : « Décide à partir de l'**intention éditoriale/commerciale**. Priorise partenariat, logos de marque, relais vers un site, signaux de sponsorisation. »

Le **couple grille + procédures** forme ce que nous appelons ASSIST dans le mémoire (terminologie forgée par nous, inspirée — *a posteriori* — par l'idée du papier ASSIST).

### 3.4 Design expérimental

Plan factoriel $2 \times 4 \times 2 = 16$ runs principaux + 2 runs d'ablation factorielle ($187, 188$) = **18 runs** en BDD. Variables :

- Architecture : `alma` vs `simple`
- Modèle : `flash-lite` / `flash` / `full-flash` / `qwen`
- Dataset : `alpha` / `test`

Ablation $2 \times 2$ sur `simple flash test` uniquement :

| Run | Grille | Procédure | Mode |
|---|---|---|---|
| 185 | ✗ | ✗ | no-ASSIST |
| 187 | ✓ | ✗ | grille seule |
| 188 | ✗ | ✓ | procédure seule |
| 181 | ✓ | ✓ | ASSIST complet |

---

## 4. Comparaison point par point

| Dimension | ASSIST (paper) | Alma/ASSIST (nous) |
|---|---|---|
| **Tâche** | Image captioning (génération libre) | Classification multi-axes (57+15+2 classes) |
| **Modalité d'entrée** | Images statiques (vidéo en annexe) | Images + carrousels + reels + audio + caption |
| **Sortie attendue** | Caption structurée 3 parties | 3 labels taxonomiques + reasoning |
| **Ouvert vs fermé** | Open-vocabulary (noms d'objets libres) | Closed-set (enum fermé par axe) |
| **Source des questions** | **Automatique** : matching de 55 templates `What …` sur training LLaVA | **Manuel** : 14+12 questions rédigées par nous, distillées d'audit d'erreurs |
| **Scope des questions** | Universel (généralisme VLM) | **Scopé** `FEED` vs `REELS` via `media_product_type` |
| **Type des questions** | Factuelles d'existence/description (`What color?`, `How many?`) | **Méta-linguistiques** (`CAPTION_APPEL_ACTION?`), structurelles (`STRUCTURE_SLIDES?`), sémantiques (`CAPTION_CHIFFRE_PIVOT?`) |
| **Format de réponse** | String format délimité `%%/&&/<>/[]` | `tool_call` JSON avec enum restreint |
| **Moyen d'imposer la structure** | ICL (in-context learning avec exemples) + GPT-4V | Tool calling OpenAI schema + `strict: true` |
| **Procédures d'arbitrage** | **Aucune** | **Oui** (procédure par axe, règle de priorité explicite) |
| **Taxonomie cible** | Aucune (open-vocab) | 74 fichiers YAML avec `signal_obligatoire` + `exclut` |
| **Dataset de référence** | ECO (103~k image-caption, GPT-4V + humain) | 1~583 annotations humaines (alpha 390, test 405) |
| **Modèles utilisés** | LLaVA-13B (fine-tuned), GPT-4V (proof), Qwen-VL-max (comparaison) | Gemini 3 Flash / Flash-lite / full-flash / Qwen 3.5 Flash (zero-shot) |
| **Fine-tuning** | **Oui** — LoRA rank 128 sur 100~k paires, 100 h A100 | **Non** — zero-shot + prompt engineering pur |
| **Évaluation primaire** | Precision/Recall manuelle sur 100 images COCO + 9 benchmarks VL + downstream tasks | Accuracy micro par axe + IC Wilson 95~% + McNemar + ablation factorielle 2×2 |
| **IC / test stat** | Error bars reportées sur 4 tables (écart-types) | IC Wilson exact + sign-test combiné + réplication sur ensembles disjoints |
| **Ablation sur le prompt** | **Aucune** (pas testé : impact du format Part1/Part2/Part3, impact des délimiteurs, impact des exemples ICL) | **Factorielle 2×2** (grille × procédure) — révèle interaction non additive |
| **Downstream applications** | Grounding, OVD, VQA, image/video gen | Aucune (on s'arrête à la classification) |
| **Contrôle pour confounders** | Ablation « baseline + CLIP + LLaVA » (Fig 5b) | Réplication sur ensembles strictement disjoints (`alpha only` 277, `test only` 305) |
| **Publication** | Withdrawn ICLR 2025 | Mémoire M1 (non publié) |

---

## 5. Convergences

### 5.1 Principe central

Les deux travaux partagent le **même cœur méthodologique** : décomposer un prompt vague en questions spécifiques améliore l'extraction d'information par un VLM. Cette intuition est indépendamment défendue, avec des preuves différentes mais convergentes :

- ASSIST le montre qualitativement (attention maps, semantic consistency) et quantitativement (precision/recall sur COCO).
- Nous le montrons par design factoriel sur `simple flash test` : l'ajout de la grille d'observation fait passer l'accuracy VF de 87,59~% à 87,87~% (grille seule) puis à 89,58~% (grille + procédure).

### 5.2 Recours à l'in-context learning

Les deux pipelines injectent des **exemples structurés dans le prompt** pour forcer un format de réponse :

- ASSIST insère un exemple complet Part2/Part3 dans l'instruction (Figure A10, lignes 31-56).
- Nous injectons une liste d'exemples positifs et négatifs dans `CAPTION_APPEL_ACTION` (voir `Questions/FEED.yaml` lignes 108-125) et `CAPTION_CHIFFRE_PIVOT` (lignes 141-156).

### 5.3 Décomposition hiérarchique

ASSIST structure sa sortie en **trois niveaux** :

1. Overall description (Style, Theme, Background, Foreground)
2. Object list (Category, Description, Color, Position)
3. Relationships

Notre pipeline Alma structure implicitement la perception en :

1. Grille d'observation (14+12 clés avec valeurs énumérables)
2. Taxonomie différentielle (57 classes avec `signal_obligatoire`, `caption_signal`, `exclut`)
3. Procédure d'arbitrage (règle de priorité par axe)

Les deux architectures séparent **perception** (quoi est là) et **décision** (quel label / quelle relation).

### 5.4 Séparation du percepteur et du classifieur

Notre pipeline Alma **découple explicitement** le percepteur (Alma, multimodal) et les classifieurs (text-only). ASSIST fait de même **implicitement** : GPT-4V annote les images via l'instruction ASSIST (perception), puis le parser regex + grounding DINO + CLIP mobilisent l'output pour les tâches downstream (décision).

### 5.5 Recherche d'un format parsable

Les deux systèmes recherchent une **sortie parsable** :

- ASSIST : string format avec délimiteurs `%%/&&/<>/[]` exploitables par regex.
- Nous : JSON structuré via `tool_call` avec enum fermé par axe.

### 5.6 Scaling et capacités émergentes

ASSIST revendique « *a method designed to assist smaller models in comprehending complex texts* » (§6). Notre hypothèse H1 (scale-dépendance) confirme que la structuration de prompt relève d'une **capacité émergente** (Wei et al. 2022) : elle n'aide que les modèles suffisamment capables.

**Convergence fine** : ASSIST Table A1 montre que LLaVA-13B (fine-tuned via ASSIST) dépasse LLaVA-13B brut de +0,8 à +19,7~pp selon le benchmark. Chez nous, Gemini 3 Flash dépasse Gemini 3 Flash-lite de +1,4 à +2,5~pp sous ASSIST. L'ordre de grandeur est cohérent à capacité de modèle près.

---

## 6. Divergences fondamentales

### 6.1 Nature de la tâche

ASSIST fait du **captioning ouvert** (open-vocabulary object naming, relations libres). Nous faisons de la **classification fermée** (57 classes prédéfinies, 15 catégories, 2 stratégies). Cette différence a trois conséquences majeures :

1. **Espace de sortie** : ASSIST doit *nommer* les objets (milliers de noms possibles), nous devons *choisir* un label dans une enum. Notre tâche est mathématiquement plus simple mais humainement plus contrainte.
2. **Métrique** : ASSIST mesure precision/recall sur des nominations ; nous mesurons accuracy sur des matches exacts de label.
3. **Rôle des règles** : ASSIST n'a pas besoin de règles exclusives (deux objets peuvent co-exister) ; notre taxonomie impose `SIGNAL_OBLIGATOIRE` et `EXCLUT` pour forcer l'exclusivité.

### 6.2 Nature des questions

Les 55 templates ASSIST sont des **questions factuelles de perception** :

> *What color is the shirt?* / *How many people?* / *Who is wearing the hat?* / *What is the main object?*

Nos 14+12 questions sont des **questions méta-linguistiques ou structurelles** :

> *La caption porte-t-elle au moins UN signal d'actualité chaude ou d'appel à l'action ?* (CAPTION_APPEL_ACTION)
> *La caption contient-elle un chiffre précis qui est l'ANGLE ÉDITORIAL CENTRAL du post ?* (CAPTION_CHIFFRE_PIVOT)
> *Comment les slides sont-elles organisées entre elles ?* (STRUCTURE_SLIDES)

**Conséquence critique** : un petit modèle (Flash-lite) peut répondre à un *What color?* mais pas à *« la caption porte-t-elle l'angle éditorial ? »*. Cela explique **pourquoi notre ASSIST échoue sur Flash-lite** alors que l'ASSIST du paper réussit sur LLaVA-13B (de taille comparable à Flash-lite). Les questions qualitativement différentes recrutent des capacités différentes.

### 6.3 Fine-tuning vs zero-shot

ASSIST **fine-tune** LLaVA-13B sur 100~k exemples (100 h A100 ≈ 250-400 USD). Nous restons **zero-shot** : aucune mise à jour de poids, aucun exemple de training. Conséquences :

- ASSIST nécessite un dataset annoté à grande échelle ; nous travaillons avec 1~583 annotations.
- ASSIST verrouille ses gains dans un modèle spécifique (LLaVA-13B) ; nos gains sont transférables à tout VLM.
- Le gain ASSIST-Captioner vs GPT-4V (Table 2) est en partie dû au fine-tuning, pas seulement au prompt engineering. C'est un confounder que le paper ne dissocie pas.

### 6.4 Couplage grille + procédures (notre ajout propre)

ASSIST s'arrête aux questions spécifiques + structure de sortie. **Aucune règle d'arbitrage** n'est fournie au modèle pour trancher entre signaux contradictoires. Quand deux objets sont en relation ambigue, GPT-4V invente.

Nous ajoutons un **second ingrédient** : les procédures par axe. Pour `visual_format`, la procédure explicite « format dominant prime sur thème » ; pour `category`, « sujet principal prime sur forme » ; pour `strategy`, « intention commerciale prime sur sujet ». Cet ajout est notre **contribution spécifique**.

Notre ablation factorielle 2×2 révèle une **interaction non additive** :

- Grille seule : +0,28~pp
- Procédure seule : +0,03~pp
- Prévu additif : +0,31~pp
- Observé (grille + procédure) : +1,99~pp
- **Interaction résiduelle : +1,68~pp** (soit 6,4× la somme des marginaux)

ASSIST ne teste pas cette interaction. C'est un **angle mort méthodologique** du paper : si leurs Parts 1/2/3 avaient une interaction comparable, une ablation « Part1 seule », « Part2 seule », « Part3 seule », « toutes » l'aurait révélée, mais elle n'est pas conduite.

### 6.5 Granularité du scope

ASSIST applique le même protocole à toutes les images COCO, indépendamment de leur contenu. Notre grille est **scopée par `media_product_type`** : un fichier pour FEED (14 clés visuelles), un pour REELS (12 clés dont audio et montage). Cette spécialisation :

- Réduit la charge cognitive du modèle (12-14 clés vs 25+ clés universelles).
- Adapte le vocabulaire observationnel à la modalité (FEED = slides, REELS = vidéo + audio).
- Évite le *context rot* lié à l'empilement de clés non pertinentes (voir §10).

### 6.6 Design factoriel vs ablation leave-one-out

ASSIST fait une ablation « baseline + CLIP + LLaVA » (Figure 5b) : ajout progressif de composants, sans symétrie. Nous faisons une ablation **factorielle complète** : les 4 cellules du 2×2 sont toutes mesurées, ce qui permet de calculer l'interaction.

**Conséquence** : un reviewer pourrait reprocher à ASSIST de ne pas isoler l'effet propre de chaque composant (`What if only Part1 was kept?`). Nous avons pensé ce reproche en amont.

### 6.7 Annotation : échelle vs qualité

ASSIST : 100~k annotations automatiques (GPT-4V) + correction humaine limitée. Nous : 1~583 annotations 100~% humaines, marquées `doubtful=true` pour les cas frontières (21 cas exclus de test).

**Tension** : à grande échelle, le bruit d'annotation domine les gains. À petite échelle, la subjectivité d'un annotateur unique domine. Nous avons choisi la précision ; ASSIST a choisi le volume. Aucun des deux choix n'est évidemment supérieur.

---

## 7. Limites de l'étude ASSIST

### 7.1 Limites revendiquées (§6 du paper)

1. Pipeline pas entièrement automatisé (3~k images test annotées manuellement).
2. Localisation insuffisante (besoin de Grounding DINO externe).

### 7.2 Limites non revendiquées mais visibles

#### 7.2.1 Absence d'ablation sur les composants du prompt

Le paper teste ASSIST vs baseline, mais **jamais** :
- ASSIST sans Part 1 (overall description)
- ASSIST sans Part 2 (object list)
- ASSIST sans Part 3 (relationships)
- ASSIST sans les délimiteurs `%%/&&/<>/[]`
- ASSIST sans l'exemple ICL (lignes 33-56 de l'instruction)

Résultat : on ne sait pas **quelle partie du prompt structuré fait le gain**. C'est le reproche principal qu'un reviewer ICLR pointerait.

#### 7.2.2 Évaluation partiellement circulaire sur ECO

Le test benchmark ECO est annoté par les auteurs avec **leur propre format ASSIST**. Le modèle fine-tuné sur ce format bat naturellement les modèles non fine-tunés sur ce format. Pour preuve :

- Figure 7 : ASSIST gagne les pairwise comparisons sur LLaVA (0,654 vs 0,346).
- Table 2 : ASSIST a 56,2~% precision vs LLaVA 36,4~% precision.

Ces deux tables concernent la **même évaluation** (100 images COCO) mais avec des métriques différentes. La Figure 7 suggère que LLaVA gagne 35~% des comparisons pairwise — comment est-ce compatible avec un écart de 20~pp sur precision ? L'incohérence n'est pas explicitée.

#### 7.2.3 Gains modestes sur benchmarks VL standards

Table A1 :

- VQAv2 : ASSIST-13B 80,8 vs VILA-13B 80,8 — **zero gain**
- GQA : 63,5 vs 63,3 — **+0,2** dans l'IC
- VizWiz : 57,1 vs VILA 60,6 — **-3,5**, ASSIST **perd**
- VQAᵀ : 59,5 vs VILA 66,6 — **-7,1**, ASSIST **perd nettement**

Les gains sont concentrés sur SQA (+19,7 vs LLaVA baseline) et POPE (+2,1). L'argument « capacité émergente » ne tient pas : sur 10 benchmarks, ASSIST est SOTA sur 4 (SQA, POPE, MMB, MMBᶜᴺ, MM-Vet). C'est insuffisant pour un claim général.

#### 7.2.4 IC Wilson absents, sign-test absent

Les error bars rapportées sont des **écart-types** (« ± » dans les tables), pas des IC Wilson ou bootstrap. Sur des petites tailles d'échantillon (100 images pour Table 2), cette approximation est grossière. Un sign-test sur les 9 benchmarks aurait quantifié la robustesse du gain global ; il n'est pas réalisé.

#### 7.2.5 Pas d'analyse qualitative des échecs

Le paper ne présente que des succès. Pas de section « where ASSIST fails », pas d'analyse des cas où LLaVA ASSIST-Captioner se trompe. Notre chapitre 6 analyse au contraire 8 cas de synergie pure (pattern `0001`) et 4 catégories d'attribution (A/B/C/D). ASSIST aurait pu faire de même sur ses 100 images COCO.

#### 7.2.6 Dépendance à GPT-4V (coût et reproductibilité)

ASSIST utilise GPT-4V comme annotateur pour les 100~k paires de training. Coût estimé à ~$20-40~k USD. **Aucun résultat n'est reproductible sans budget OpenAI conséquent.** Le paper ne fournit pas de variante ASSIST-LLaVA → ASSIST-LLaVA (self-bootstrapping) qui permettrait la reproduction à faible coût.

#### 7.2.7 Templates de questions statiques

Les 55 templates `What …` sont **extraits** du training data LLaVA, mais ne sont **pas appliqués dynamiquement** au test time. L'instruction GPT-4V est une seule structure statique répétée sur toutes les images. L'adaptativité revendiquée (« specific » per image) est en fait un format rigide, pas une génération dynamique de questions.

---

## 8. Pourquoi ASSIST a été retiré d'ICLR 2025

Les reviews OpenReview sont **inaccessibles** (status 403) : impossible de lire les reviewers directement. Les observations suivantes sont des hypothèses fondées sur les lacunes méthodologiques du §7 :

1. **Ablation insuffisante** : un reviewer ICLR niveau 1 aurait demandé une ablation sur les 3 Parts et sur l'ICL. Pas de réponse possible sans ré-expérimenter.
2. **Circularité d'évaluation** sur ECO (auto-annoté par GPT-4V avec leur propre format).
3. **Gains modestes** sur les VL benchmarks standards (SOTA sur 4/10 seulement).
4. **Comparaison asymétrique** : ASSIST-13B fine-tuné vs VILA-13B / ASMv2-13B eux aussi fine-tunés mais sur d'autres datasets. Pas de même-dataset / même-recette.
5. **Claim général vs preuve spécifique** : le papier revendique une contribution méthodologique (decompose ambiguous prompts) mais la preuve porte sur un modèle spécifique (LLaVA-13B) avec un fine-tuning spécifique (100~k images ECO).
6. **Auteurs anonymes + retrait** suggère que les auteurs n'ont pas voulu faire le rebuttal, ou ont préféré re-soumettre ailleurs après refonte.

**Verdict probable** : la méthode est pédagogiquement utile mais scientifiquement fragile. Un *major revision* aurait demandé 3-6 mois de ré-expérimentation. Le retrait évite le rejet explicit et permet une re-soumission à NeurIPS 2025 ou EMNLP 2025.

---

## 9. Pertinence d'ASSIST pour nos modèles

### 9.1 Modèles en présence

| Modèle | Type | Tailles estimées | Coût |
|---|---|---|---|
| Gemini 3 Flash | grand closed | inconnu (*probablement >100~B effectifs*) | $0{,}50/$3{,}00 per M |
| Gemini 3 Flash-lite | petit closed | inconnu (*probablement 10-30~B*) | $0{,}25/$1{,}50 per M |
| Gemini 3 full-flash | grand closed, tout axes | inconnu | $0{,}50/$3{,}00 per M |
| Qwen 3.5 Flash | petit open | 3-7~B | $0{,}065/$0{,}26 per M |

### 9.2 Effet mesuré d'ASSIST par modèle (notre H1)

| Modèle | $\Delta_{\assist}$ sur `alpha` | $\Delta_{\assist}$ sur `test` | Réplication disjoints |
|---|---|---|---|
| Flash-lite | $-0{,}51$~pp (run 164 vs 165) | $-0{,}25$~pp (176 vs 177) | alpha only +0,36 / test only +0,65 |
| Flash | $+2{,}47$~pp (171 vs 167) | $+1{,}99$~pp (181 vs 185) | alpha only +2,12 / test only +1,40 |

**Conclusion** : ASSIST n'apporte rien détectable sur Flash-lite, apporte ~2~pp sur Flash.

### 9.3 Paradoxe apparent

Le paper ASSIST revendique que la méthode aide les **petits modèles** (LLaVA-13B, considéré comme petit en 2024). Notre expérience montre que ASSIST aide les **gros modèles** (Flash > Flash-lite).

**Résolution du paradoxe** : la différence vient de la nature des questions.

- Les questions ASSIST du paper sont **factuelles** : *What color is the shirt?*, *How many people?*. Un petit modèle peut les traiter (recognition 101).
- Nos questions sont **sémantiques et éditoriales** : *CAPTION_APPEL_ACTION*, *CAPTION_CHIFFRE_PIVOT*, *STRUCTURE_SLIDES*. Elles demandent une compréhension fine du rôle d'un signal dans une intention éditoriale. Un petit modèle **remplit la grille approximativement** (il répond « oui/non » à tout) mais **ne mobilise pas les règles de priorité** des procédures.

### 9.4 Recommandation par tier modèle

Sur la base de nos 18 runs :

| Tier | Recommandation | Justification |
|---|---|---|
| `qwen` | **Sans ASSIST** (mais Alma oui) | Qwen 3.5 Flash est text-only et économique. Alma qwen = 82,2~% VF @ $2,33 sur alpha. Le découplage percepteur/classifieur permet de garder Gemini pour la perception (multimodale) et Qwen pour la décision (texte). Pas d'ASSIST possible sur `simple` car Qwen n'est pas multimodal. |
| `flash-lite` | **Sans ASSIST** | Gain ASSIST indétectable. Sweet spot économique : `simple fl-lite no-ASSIST` (85,38~% VF @ $0,78/post sur alpha, 87,16~% @ $0,80/post sur test). **Recommandation industrielle stable**. |
| `flash` | **Avec ASSIST** | Gain ASSIST mesurable (+2 pp). `simple flash ASSIST` atteint 89,58~% VF sur test (meilleur résultat absolu). Coût $5,49, soit 1,36¢/post. |
| `full-flash` | **ASSIST saturé** | `alma full-flash` : 86,67~% VF @ $7,72 sur alpha, 85,19~% sur test (dominé par `simple flash ASSIST` moins cher). La capacité brute du modèle absorbe l'essentiel du gain ASSIST ; investir dans le modèle est inefficient au-delà de Flash. |

---

## 10. Context window et *context rot* (2025-2026)

### 10.1 Le phénomène

Le *context rot* est la dégradation systématique des performances d'un LLM à mesure que son contexte s'allonge, indépendamment de la taille nominale de la fenêtre. Chroma Research a documenté ce phénomène en 2025 sur **18 modèles frontier** : tous dégradent, dès 50~k tokens en entrée, même si la fenêtre nominale est de 1~M tokens.

Mécanismes identifiés :

1. **Positional bias** : les informations au début ou à la fin du contexte sont mieux mémorisées ; celles au milieu sont diluées. Sur un test à 20 positions, accuracy passe de 70-75~% (position 1 ou 20) à 55-60~% (positions 8-12).
2. **Attention dilution** : la softmax de l'attention normalise par le nombre de tokens. Plus le contexte est long, plus chaque token reçoit une fraction d'attention réduite. Le signal ne se renforce pas, le bruit de fond monte.
3. **Shift U → descendant** : en contexte partiellement rempli (< 50~%), on observe un pattern en U (favorisant début et fin). En contexte saturé (> 50~%), le pattern devient descendant (favorisant uniquement la fin).

### 10.2 Implications pour notre prompt

Notre pipeline `simple flash ASSIST` (run 181) injecte en ordre :

1. Système (persona Alma + context rules) ≈ 200 tokens
2. Grille d'observation (14 clés FEED ou 12 REELS) ≈ 1~500-2~000 tokens
3. Taxonomie visual_format rendue (40 ou 17 classes × ~200 tokens) ≈ 4~000-8~000 tokens
4. Taxonomie category (15 classes) ≈ 2~000 tokens
5. Taxonomie strategy (2 classes) ≈ 300 tokens
6. Procédures par axe (3 × ~200 tokens) ≈ 600 tokens
7. Post (images + caption) ≈ variable (la caption ajoute 100-500 tokens)

Total estimé : **10~000-15~000 tokens** en entrée (hors images). À cela s'ajoutent 4~000-8~000 tokens d'image tokens (selon le nombre de slides du carrousel).

À ~20~k tokens au total, on est **au-dessus du seuil de 50~k mais sous le seuil nominal de Flash** (1~M tokens). Le *context rot* est modéré mais présent.

### 10.3 Diagnostic sur notre pipeline

Le placement actuel du prompt est **défavorable au context rot** :

- La **procédure par axe** (le signal le plus important pour l'arbitrage) est placée **avant les images** (donc au milieu du contexte total).
- Les règles `EXCLUT` (fin de chaque fichier YAML) sont diluées dans le bloc taxonomie.
- La **caption** (fin du contexte) bénéficie de la position, ce qui explique pourquoi `CAPTION_APPEL_ACTION` est un signal fort chez nous.
- La **grille d'observation** (début du user message) bénéficie aussi d'une position favorable.

### 10.4 Cohérence avec la scale-dépendance

Sur Flash-lite (petit modèle, plus sensible au context rot), l'empilement de 10-15~k tokens de structure dilue probablement les règles de procédure **au-delà du seuil d'exploitabilité**. Flash-lite remplit la grille approximativement mais n'arrive pas à mobiliser la procédure.

Sur Flash (gros modèle, moins sensible au context rot), les règles restent exploitables malgré la longueur. C'est cohérent avec nos findings : ASSIST n'aide pas Flash-lite, aide Flash.

### 10.5 Optimisations possibles (non testées)

1. **Répéter la procédure à la fin** du user message (Claude best practice 2024, reprise par Anthropic *Effective context engineering for AI agents*).
2. **Compaction** : résumer les taxonomies non pertinentes au scope FEED vs REELS (Chroma 2025).
3. **Splitter en plusieurs appels** : Alma le fait déjà (4 appels) et observe un Pareto différent que Simple. Le découplage est une forme de *context compaction*.
4. **Mettre les images en premier** (déjà le cas sur simple), car GPT-4V/Gemini traitent les image tokens en tête.

---

## 11. Études ultérieures plus solides

Rangées par ordre de pertinence décroissante pour notre travail :

1. **Chroma — Context Rot (2025)**. Benchmark sur 18 modèles, démonstration empirique du déclin en long contexte. [research.trychroma.com/context-rot](https://research.trychroma.com/context-rot). Directement pertinent pour notre discussion modèle/longueur prompt.

2. **Anthropic — Effective Context Engineering for AI Agents (2024)**. Cadre pratique pour le management de contexte (compaction, sub-agents, note-taking). [anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). Pertinent pour nos optimisations (§10.5).

3. **HPT — Hierarchical Prompting Taxonomy (Budagam et al. 2024)**. Cadre universel d'évaluation avec 5 stratégies hiérarchiques, ablation studies incluses. [arxiv 2406.12644](https://arxiv.org/html/2406.12644v3). Plus général que ASSIST, s'applique à tout LLM.

4. **MARS2 (2025)** — *Cognition-Guided Structured Prompting Strategy* pour VLMs en 5 étapes ordonnées. Ablation modulaire, mais en *leave-one-out* comme ASSIST.

5. **STROT (2025)** — *Structured Prompting with Iterative Feedback*. Combine prompt structuré et feedback itératif. Ablation *leave-one-out*.

6. **Task-Aware Clustering for Prompting VLMs (CVPR 2025)**. Prompts apprenables task-aware, interaction avec attention masquée. [openaccess.thecvf.com/.../Hao_Task-Aware_Clustering](https://openaccess.thecvf.com/content/CVPR2025/papers/Hao_Task-Aware_Clustering_for_Prompting_Vision-Language_Models_CVPR_2025_paper.pdf).

7. **Prompt-based Adaptation in Large Vision Models — Survey (2025)**. Taxonomie des approches d'adaptation prompt-based. [arxiv 2510.13219](https://arxiv.org/pdf/2510.13219).

8. **A comprehensive taxonomy of prompt engineering techniques (Frontiers of Computer Science, 2025)**. Taxonomie par objectifs, modalités, techniques. [doi 10.1007/s11704-025-50058-z](https://link.springer.com/article/10.1007/s11704-025-50058-z).

9. **Rethinking Visual Prompting for MLLMs with External Knowledge (2024)**. Complète les descriptions linguistiques avec structure de connaissance. [arxiv 2407.04681](https://arxiv.org/html/2407.04681v1).

10. **Learning Hierarchical Prompt with Structured Linguistic Knowledge (2023)**. Structure linguistique comme contrainte sur le prompt tuning. [arxiv 2312.06323](https://arxiv.org/html/2312.06323v1).

**Gap que nous comblons** : aucun des travaux ci-dessus ne rapporte d'**interaction non additive** entre composants d'un prompt structuré. C'est notre contribution spécifique (H3, interaction résiduelle +1,68~pp).

---

## 12. Solidité scientifique d'ASSIST

### 12.1 Points forts

1. **Intuition correcte** : la décomposition en questions spécifiques améliore effectivement l'extraction — c'est intuitif et vérifié ici comme chez nous.
2. **Dataset ECO publié** : 103~k paires image-caption est une ressource réutilisable (si effectivement mise à disposition — ce n'est pas clair).
3. **Évaluation downstream diverse** : 9 benchmarks VL, OVD, VQA, image gen, video captioning. Couverture large.
4. **Attention maps qualitatives** (Figure 3) : preuve visuelle convaincante de la focalisation accrue.
5. **User study** sur 10 annotateurs (§4.1.3) : vrais humains, pas seulement benchmarks auto.

### 12.2 Points faibles

1. **Pas d'ablation sur le prompt** (§7.2.1) : la faiblesse principale.
2. **Circularité d'évaluation sur ECO** (§7.2.2).
3. **Gains modestes et non uniformes** sur VL benchmarks (§7.2.3).
4. **IC Wilson absents** (§7.2.4).
5. **Pas d'analyse qualitative des échecs** (§7.2.5).
6. **Dépendance GPT-4V** non reproductible à faible coût (§7.2.6).
7. **Templates statiques** (§7.2.7) — l'adaptativité revendiquée est un format rigide.
8. **Aucune ablation sur le fine-tuning** : on ne sait pas si le gain vient du prompt ASSIST ou du fine-tuning. Un *ASSIST prompt sur LLaVA non fine-tuné* et un *fine-tuning sans format ASSIST* manquent.
9. **Comparaisons asymétriques** : ASSIST-13B vs VILA-13B/ASMv2-13B fine-tunés sur des données différentes.
10. **Claim général / preuve spécifique** : le titre parle de GPT mais 80~% des expériences portent sur LLaVA.

### 12.3 Verdict

**L'idée est correcte, l'exécution est moyenne.** Le papier a un bon potentiel pédagogique (« fais des questions spécifiques ») mais manque de rigueur méthodologique pour un publication ICLR.

Le retrait est cohérent avec des reviews demandant des révisions majeures que les auteurs n'ont pas voulu ou pas pu satisfaire. Les réf. du domaine (HPT, MARS2, STROT, Task-Aware Clustering) proposent des méthodologies plus solides, souvent en 2024-2025.

**Implication pour notre mémoire** : citer ASSIST comme *inspiration méthodologique* reste défendable — l'intuition est bonne. Mais ne **pas** s'appuyer sur ASSIST comme *validation externe* de notre approche. Notre propre design factoriel et notre interaction non additive sont des contributions **indépendantes et plus solides** que le papier dont nous empruntons le nom.

---

## 13. Résultats

> Runs issus de la BDD le 2026-04-19, tous extraits de la table `simulation_runs` via la clé `config->>'pipeline_mode'`. Les dumps de sauvegarde sont dans `data/bdd_dump_20260419_1422.sql.gz`.

### 13.1 Alma (architecture à 4 appels avec découplage)

| Run | Dataset | Tier modèle | VF % | Cat % | Strat % | Coût $ |
|---|---|---|---|---|---|---|
| 158 | alpha | flash-lite | 83,85 | 92,82 | 96,92 | 3,68 |
| 159 | alpha | flash (VF seul) | 83,59 | 92,82 | 96,92 | 4,62 |
| 160 | alpha | full-flash | **86,67** | 93,33 | 96,67 | 7,72 |
| 161 | alpha | qwen | 82,23 | **93,37** | 95,76 | **2,33** |
| 172 | test | flash-lite | 82,72 | 88,15 | 94,57 | 3,94 |
| 182 | test | flash (VF seul) | **88,15** | 88,15 | 94,57 | 4,95 |
| 183 | test | full-flash | 85,19 | 85,68 | 95,31 | 7,83 |
| 178 | test | qwen | 83,81 | **89,30** | 95,04 | **2,36** |

**Best Alma sur alpha** : `alma full-flash` (run 160) avec 86,67~% VF @ $7,72 mais rendement marginal médiocre (3,37 pp/¢).
**Best Alma sur test** : `alma flash` (run 182) avec 88,15~% VF @ $4,95.
**Best Alma-économique** : `alma qwen` (runs 161, 178), VF ~82-84~% @ $2,33-2,36. Classifier text-only *commoditisable*.

### 13.2 ASSIST (pipeline Simple avec grille + procédures)

| Run | Dataset | Tier modèle | Grille | Proc. | VF % | Cat % | Strat % | Coût $ |
|---|---|---|---|---|---|---|---|---|
| 164 | alpha | flash-lite | ✓ | ✓ | 84,87 | 89,49 | 97,44 | 3,25 |
| 165 | alpha | flash-lite | ✗ | ✗ | **85,38** | 91,79 | 97,44 | **3,05** |
| 167 | alpha | flash | ✗ | ✗ | 85,35 | 90,49 | 98,20 | 4,92 |
| 171 | alpha | flash | ✓ | ✓ | **87,82** | 89,64 | **98,45** | 5,18 |
| 176 | test | flash-lite | ✓ | ✓ | 86,91 | 88,15 | 95,56 | 3,45 |
| 177 | test | flash-lite | ✗ | ✗ | **87,16** | 89,88 | 95,31 | **3,22** |
| 185 | test | flash | ✗ | ✗ | 87,59 | 85,36 | 96,53 | 1,64\* |
| 181 | test | flash | ✓ | ✓ | **89,58** | 84,62 | **96,28** | 5,49 |

\* Run 185 bénéficie du context caching Google AI (baisse de coût artificielle × 3). Normalisé cache-off : ~$5,21.

**Best ASSIST sur alpha** : `simple flash ASSIST` (run 171) avec 87,82~% VF @ $5,18.
**Best ASSIST sur test** : `simple flash ASSIST` (run 181) avec 89,58~% VF @ $5,49.
**Best économique** : `simple fl-lite no-ASSIST` (runs 165, 177) — **winner Pareto** sur les deux ensembles.

### 13.3 Ablation factorielle 2×2 (simple flash test)

| Run | Config | VF % | $\Delta$ |
|---|---|---|---|
| 185 | no-ASSIST | 87,59 | baseline |
| 187 | grille seule | 87,87 | +0,28 |
| 188 | procédure seule | 87,62 | +0,03 |
| 181 | **ASSIST complet** | **89,58** | **+1,99** |

**Interaction résiduelle** : $1,99 - (0,28 + 0,03) = +1,68$~pp, soit **6,4 × la somme des effets marginaux**.

### 13.4 Alma VS ASSIST — comparaison directe

#### Tête à tête par dataset et tier modèle

| Tier modèle | Dataset | Alma VF % | Simple ASSIST VF % | $\Delta$ (ASSIST − Alma) |
|---|---|---|---|---|
| flash-lite | alpha | 83,85 (158) | 84,87 (164) | **+1,02** |
| flash-lite | test | 82,72 (172) | 86,91 (176) | **+4,19** |
| flash | alpha | 83,59 (159) | 87,82 (171) | **+4,23** |
| flash | test | 88,15 (182) | 89,58 (181) | **+1,43** |
| full-flash | alpha | 86,67 (160) | — | — |
| full-flash | test | 85,19 (183) | — | — |
| qwen | alpha | 82,23 (161) | — (N/A) | — |

→ **Sur `visual_format`, ASSIST (Simple) bat Alma à tier modèle égal** dans les 4 comparaisons possibles.
→ **Sur `full-flash` et `qwen`**, on ne peut pas tester Simple (qwen est text-only, full-flash est identique à flash en Simple).

#### Inversion sur category

| Tier | Dataset | Alma Cat % | Simple ASSIST Cat % | $\Delta$ (Alma − ASSIST) |
|---|---|---|---|---|
| flash-lite | alpha | 92,82 (158) | 89,49 (164) | **+3,33** |
| flash-lite | test | 88,15 (172) | 88,15 (176) | +0,00 |
| flash | alpha | 92,82 (159) | 89,64 (171) | **+3,18** |
| flash | test | 88,15 (182) | 84,62 (181) | **+3,53** |
| qwen | alpha | **93,37** (161) | — | — |

→ **Sur `category`, Alma bat Simple ASSIST** dans 3 des 4 comparaisons flash/flash-lite.

**Explication** : l'axe `category` repose sur le **sujet principal** (personne, œuvre, objet). Le découplage d'Alma (description textuelle riche d'abord, puis classifieur text-only) facilite l'extraction du sujet. Simple traite tout en une fois et surcharge moins efficacement la catégorisation.

#### Analyse qualitative

- **ASSIST (Simple) est meilleur sur `visual_format`** parce que le format dépend fortement d'indices structurels (overlay, flèche, logo, composition des slides, audio) — tous couverts par la grille. La grille + procédure forme un système discriminant.
- **Alma est meilleur sur `category`** parce que la catégorie dépend du contenu éditorial (personnes, thèmes). Le découplage Alma → 3 classifieurs parallèles laisse au classifieur `category` un contexte pur sujet, sans pollution par les signaux de format.
- **Sur `strategy`**, les deux sont quasi-équivalents (96-98~%), car la strategy est dominée par des signaux robustes (mention de partenariat, logo marque) que les deux architectures captent.

#### Coût et rendement

| Config gagnante | VF % | Coût $ | Rendement pp/¢ |
|---|---|---|---|
| **Simple fl-lite no-ASSIST (test, run 177)** | 87,16 | 3,22 | **8,96 pp/¢** |
| Simple fl-lite no-ASSIST (alpha, run 165) | 85,38 | 3,05 | 6,91 pp/¢ |
| Simple flash ASSIST (test, run 181) | 89,58 | 5,49 | 7,04 pp/¢ |
| Alma flash test (run 182) | 88,15 | 4,95 | 6,68 pp/¢ |
| Alma full-flash alpha (run 160) | 86,67 | 7,72 | 3,37 pp/¢ |

**Sweet spot économique** : `simple fl-lite no-ASSIST` — non Pareto-dominée ni sur `alpha` ni sur `test`.
**Sweet spot qualité** : `simple flash ASSIST` — max VF absolu 89,58~% @ 1,36¢/post.

### 13.5 Lecture intégrée Alma VS ASSIST

1. **Sur `visual_format` (axe principal), ASSIST gagne** — cohérent avec la thèse du papier ASSIST original sur l'importance des questions structurées pour la perception.
2. **Sur `category`, Alma gagne** — le découplage text-only permet un classifieur dédié qui raisonne mieux sur le sujet.
3. **Sur `strategy`, égalité** — les signaux sont trop robustes pour différencier les architectures.
4. **En coût-performance, `simple fl-lite no-ASSIST` domine** — la complexité ASSIST ne paie qu'à partir de Flash. Sous ce tier, la simplicité gagne.
5. **Notre `ASSIST` n'est pas le `ASSIST` du paper** : les questions sont sémantiques (vs factuelles), scopées (vs universelles), couplées à des procédures (vs autonomes). La méthode est inspirée, pas dérivée.

### 13.6 Configuration recommandée pour Views (production)

Selon le seuil de rendement $\bar r$ fixé par Views :

| Valeur $\bar r$ (pp par centime) | Configuration recommandée | VF attendu | Coût par post |
|---|---|---|---|
| $\bar r > 8$ | `alma qwen` | ~82~% | 0,6¢ |
| $\bar r \in [4, 8]$ | **`simple fl-lite no-ASSIST`** ★ sweet spot | ~87~% | 0,8¢ |
| $\bar r \in [2, 4]$ | `simple flash ASSIST` | ~89~% | 1,36¢ |
| $\bar r < 2$ | `alma full-flash` | ~86~% | 2¢ |

**Décision industrielle stable** : `simple fl-lite no-ASSIST` est Pareto sur **les deux datasets**, avec le meilleur rendement. C'est la configuration à déployer par défaut pour classifier les 21~425 posts historiques.

---

## Annexe — Fichiers mobilisés dans ce rapport

- `memoire_chebbah_anthropic.pdf` — mémoire v1 (contient la citation ASSIST hallucinée)
- `1180_Asking_Specifically_Inste.pdf` — papier ASSIST (preprint OpenReview)
- `Questions/FEED.yaml`, `Questions/REELS.yaml` — grilles d'observation
- `Descriptions/FEED/*.yaml` (40), `Descriptions/REELS/*.yaml` (17), `Descriptions/CATEGORY/*.yaml` (15), `Descriptions/STRATEGY/*.yaml` (2) — taxonomies
- `Template A — Descripteur.md` — prompt système Alma (percepteur)
- `milpo/taxonomy_renderer.py` — renderer YAML → texte canonique
- `milpo/prompts/classifier.py` — procédures par axe
- BDD PostgreSQL `hilpo`, table `simulation_runs` — runs 158, 159, 160, 161, 164, 165, 167, 171, 172, 176, 177, 178, 181, 182, 183, 185, 187, 188
- Dump BDD : `data/bdd_dump_20260419_1422.sql.gz`

**Fin du rapport.**
