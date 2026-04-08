# Architecture

## Pipeline multi-agents

Chaque post passe par un pipeline en deux étapes : un **descripteur** multimodal extrait les features visuelles, puis 3 **classifieurs** text-only prédisent en parallèle.

```
Post → Router → détecte le type (FEED/REELS)
                 ↓
         Descripteur (multimodal)![1775632736886](image/architecture/1775632736886.png)![1775632738518](image/architecture/1775632738518.png)
         Reçoit : médias + caption + critères discriminants Δ^m
         Retourne : JSON structuré (features + résumé visuel libre)
                 ↓ features JSON + caption brute
         ┌───────┼───────┐
         ↓       ↓       ↓
    Agent       Agent    Agent
   catégorie  visual_f  stratégie
   (text-only, scopé, enum fermé)
```

### Pourquoi deux étapes ?

1. **Coût** : les tokens image/vidéo sont payés 1 seule fois (descripteur), pas 3× (un par axe)
2. **Traçabilité** : le JSON intermédiaire est loggable — on sait ce que le modèle "voit"
3. **Spécialisation** : le descripteur fait de la perception, les classifieurs font du jugement
4. **Feature extraction guidée** : le descripteur connaît les critères discriminants (Δ^m) et extrait ce qui compte

### Agents

1. **Router** : routage **déterministe** basé sur `media_product_type` (métadonnée structurée Instagram, pas de LLM). Dispatche vers le scope FEED ou REELS. Les STORY sont ignorés pour l'instant (0 dans le test).

2. **Descripteur** (multimodal) : reçoit les médias (toutes les slides carousel, vidéo, audio pour les reels) + la caption + les critères discriminants du scope. Retourne un JSON structuré de features visuelles + un résumé libre insightful. **Son prompt est optimisable par MILPO.**

3. **Agent catégorie** (text-only) : classifie parmi les 15 catégories éditoriales. Reçoit le JSON de features + la caption brute + les descriptions des 15 catégories.

4. **Agent visual_format** (text-only) : classifie parmi le sous-ensemble de formats visuels **scopé par type** :
   - FEED → `post_*` (44 formats)
   - REELS → `reel_*` (16 formats)

5. **Agent stratégie** (text-only) : détermine Organic vs Brand Content. Reçoit le JSON de features + la caption brute.

### Modèles via OpenRouter

| Rôle | Scope | Modèle | Modalités | Prix input/1M | Prix output/1M |
|------|-------|--------|-----------|---------------|----------------|
| Descripteur | FEED | Gemini 3 Flash Preview | image + vidéo + texte | \$0.50 | \$3.00 |
| Descripteur | REELS | Gemini 3 Flash Preview | image + vidéo + audio + texte | \$0.50 | \$3.00 |
| Classifieurs (×3) | tous | Qwen 3.5 Flash | texte seul | \$0.065 | \$0.065 |

**Choix du descripteur** : Gemini 3 Flash Preview pour les deux scopes (commit `7e352ab`, 2026-04-06). Validation empirique :
- Carousels jusqu'à 20 slides (max Instagram actuel) : ✓
- Vidéos REELS via URL GCS signée : ✓
- Détection audio (voix off, interview, musique) : ✓
- Stabilité sous concurrence (10 parallèles, 2 vagues) : 18/18 ✓

Alternatives écartées : **Qwen 3.5 Flash** (limite carousel à ~8 images, raw vide à 10+), **Gemini 2.5 Flash via Google AI Studio** (réponses vides + 503 *high demand* sous concurrence). Coût ~27× plus élevé que Qwen mais ~\$50-130 sur tout le projet, acceptable pour la fiabilité.

#### Mécanisme d'output structuré

Le descripteur et les classifieurs n'utilisent **pas** la même feature OpenRouter pour contraindre leur sortie :

- **Descripteur** (Gemini 3 Flash Preview) : `response_format=json_schema` (strict). L'output est un objet complexe avec ~25 champs (booléens, strings, listes), aucun enum binaire — Gemini honore correctement le schema dans ce cas.
- **Classifieurs (×3)** (Qwen 3.5 Flash text-only) : **tool calling** via `tools=[tool] + tool_choice="auto"`. L'output est forcé à un objet `{label, confidence}` où `label` est un enum fermé scopé. Tool calling est utilisé plutôt que `response_format=json_schema` parce que les providers Qwen 3.5 Flash sur OpenRouter n'honorent pas réellement json_schema sur les enums binaires (ils renvoient un float `-1.5` au lieu d'un objet). Tool calling est universellement supporté par tous les providers OpenRouter, c'est l'approche éprouvée pour les classifications à enum fermé.

### Schema du descripteur

Le descripteur retourne un JSON structuré avec deux niveaux :
- **`resume_visuel`** : description libre et insightful de tous les médias
- **Features structurées** : champs typés pour réduire le champ de décision des classifieurs

```json
{
  "resume_visuel": "Texte libre décrivant ce qu'on voit, les patterns, les indices subtils",

  "texte_overlay": {
    "present": false,
    "type": null,
    "contenu_resume": null
  },
  "logos": {
    "views": false,
    "specifique": null,
    "marque_partenaire": null
  },
  "mise_en_page": {
    "fond": null,
    "nombre_slides": 1,
    "structure": null
  },
  "contenu_principal": {
    "personnes_visibles": false,
    "type_personne": null,
    "screenshots_film": false,
    "pochettes_album": false,
    "zoom_objet": false,
    "photos_evenement": false
  },
  "audio_video": {
    "voix_off_narrative": false,
    "interview_face_camera": false,
    "musique_dominante": false,
    "type_montage": null
  },
  "analyse_caption": {
    "longueur": 0,
    "mentions_marques": [],
    "hashtags_format": null,
    "mention_partenariat": false,
    "sujet_resume": null
  }
}
```

#### Valeurs possibles (enums)

| Champ | Valeurs |
|-------|---------|
| `texte_overlay.type` | `actualite`, `citation`, `chiffre`, `titre_editorial`, `liste_numerotee`, `annotation`, `description_produit` |
| `logos.specifique` | `BLUEPRINT`, `MOODY_MONDAY`, `MOODY_SUNDAY`, `REWIND`, `9_PIECES`, `THROWBACK`, `VIEWS_ESSENTIALS`, `VIEWS_RESEARCH`, `VIEWS_TV` |
| `mise_en_page.fond` | `photo_plein_cadre`, `couleur_unie`, `texture`, `collage`, `split_screen` |
| `mise_en_page.structure` | `slide_unique`, `gabarit_repete`, `opener_contenu_closer`, `collage_grille` |
| `contenu_principal.type_personne` | `artiste`, `athlete`, `personnalite`, `anonyme` |
| `audio_video.type_montage` | `captation_live`, `montage_edite`, `face_camera`, `b_roll_narration` |

### Routage et réduction de l'espace de labels

Le routage déterministe réduit l'espace de classification pour `visual_format` :

| Scope | Formats possibles | Réduction |
|-------|------------------|-----------|
| FEED | 44 formats `post_*` | — |
| REELS | 16 formats `reel_*` | ÷3 |

Chaque classifieur ne voit que les labels de son scope via un **tool use avec enum fermé**. Le modèle est contraint structurellement — il ne peut pas retourner un label hors taxonomie.

### Prompts scopés et optimisables

Chaque agent a un prompt composé de deux blocs :

```
┌─────────────────────────────────────────┐
│ Descriptions taxonomiques Δ^m (FIXES)   │
│ Rédigées par l'humain, scopées par type │
│ Cache-friendly (ne changent jamais)     │
├─────────────────────────────────────────┤
│ Instructions I_t (OPTIMISÉES par MILPO) │
│ Modifiées par le rewriter à chaque      │
│ itération de la boucle                  │
└─────────────────────────────────────────┘
```

6 prompts optimisables au total :

| Prompt | Agent | Scope |
|--------|-------|-------|
| `I_t^(desc, FEED)` | Descripteur | FEED |
| `I_t^(desc, REELS)` | Descripteur | REELS |
| `I_t^(cat)` | Classifieur catégorie | tous |
| `I_t^(vf, FEED)` | Classifieur visual_format | FEED |
| `I_t^(vf, REELS)` | Classifieur visual_format | REELS |
| `I_t^(str)` | Classifieur stratégie | tous |

### Flux d'annotation et simulation (Phase 3)

L'annotation et l'optimisation sont **découplées** :

1. **Annotation** : l'humain annote tous les posts dev via l'interface de swipe (rapide, pas d'attente modèle)
2. **Simulation** : un script rejoue les annotations dans l'ordre de présentation (seed=42) et simule la boucle MILPO

Sous les hypothèses du protocole, ce découplage est opérationnellement équivalent au live car :
- Les annotations sont déterministes (déjà faites)
- L'ordre de présentation est fixé (seed=42)
- Le modèle est suffisamment stable pour que les variations stochastiques restent limitées (temperature=0.1)
- Le prompt évolue de la même façon

**Avantage** : les ablations sont triviales — on rejoue la simulation avec B=1, 10, 30, 50 sans ré-annoter.

### Boucle MILPO (simulation prequential)

Le script de simulation parcourt les posts dev dans l'ordre de présentation. Le protocole est du type **prequential / progressive validation** : chaque bloc sert à évaluer avant de servir à optimiser.

#### Paramètres (fixés à l'avance)

| Paramètre | Valeur | Description |
|-----------|--------|-------------|
| `B` | 30 | Nombre d'erreurs avant trigger rewriter |
| `delta` | 2% | Gain minimum pour promotion |
| `patience` | 3 | Nombre de rewrites sans amélioration avant arrêt |
| `eval_window` | 30 | Taille du bloc d'évaluation post-rewrite |

#### Flux

1. Classer les posts un par un avec le prompt **incumbent** (actif)
2. Comparer chaque prédiction à l'annotation humaine
3. Si erreur : ajoutée au buffer
4. Si |buffer| >= B : le rewriter se déclenche
   - Il reçoit l'incumbent + le batch d'erreurs (features, descriptions, attendu vs observé)
   - Il propose un **candidate**
5. **Double évaluation** sur le bloc suivant (30 posts) :
   - Classer les 30 posts avec l'**incumbent**
   - Classer les 30 posts avec le **candidate**
   - Comparer les match rates sur les **mêmes posts**
6. Si accuracy(candidate) >= accuracy(incumbent) + delta : **promotion**
   Sinon : **rollback**
7. Reset du buffer d'erreurs, le cycle recommence
8. **Arrêt** si `patience` rewrites consécutifs sans promotion, ou fin des posts dev

#### Diagramme de flux

```mermaid
flowchart TD
    A["Post dev x_i (presentation_order)"] --> B["Pipeline incumbent\nDescripteur -> 3 classifieurs"]
    B --> C["Comparer aux annotations humaines"]
    C --> D{"Erreur sur >= 1 axe ?"}
    D -- "Non" --> E["Post suivant"]
    D -- "Oui" --> F["Ajouter au buffer E_t"]
    F --> G{"|E_t| >= B ?"}
    G -- "Non" --> E
    G -- "Oui" --> H["Sélectionner la cible du rewrite\n(agent/scope)"]
    H --> I["Rewriter -> prompt candidate"]
    I --> J["Double évaluation sur le bloc futur commun\nincumbent vs candidate"]
    J --> K{"acc(candidate) >= acc(incumbent) + delta ?"}
    K -- "Oui" --> L["Promotion du candidate"]
    K -- "Non" --> M["Rollback"]
    L --> N["Reset du buffer"]
    M --> N
    N --> O{"patience épuisée ?"}
    O -- "Non" --> E
    O -- "Oui" --> P["Poursuite sans rewrite"]
    P --> E
```

#### Nombre de rewrites estimé (basé sur B0)

| Axe | Taux d'erreur B0 | Rewrites estimés (1563 posts) |
|-----|-------------------|-------------------------------|
| visual_format | ~36% | ~19 |
| catégorie | ~13% | ~6 |
| stratégie | ~6.5% | ~3 |

Note : le rewriter peut optimiser le prompt du descripteur ET des classifieurs (2 niveaux d'optimisation).

#### Arbitrages du protocole

- **Fenêtre d'évaluation consommée** : les `eval_window` posts qui suivent un rewrite servent uniquement à comparer incumbent et candidate. Ils contribuent aux métriques de simulation, mais ne réalimentent pas le buffer d'erreurs. Avec `eval_window=30`, une quinzaine de rewrites consomme une part substantielle du split dev en évaluation passive plutôt qu'en apprentissage.
- **Patience globale** : le compteur de `patience` est global à la simulation, pas par cible. Trois rewrites consécutifs sans promotion, même sur des cibles différentes, arrêtent toute nouvelle tentative de rewrite.
- **Sélection de cible biaisée vers les axes dominants** : `pick_rewrite_target` favorise mécaniquement l'agent avec le plus d'erreurs observées. En pratique, `visual_format` sera plus souvent ciblé que `strategy`. Le descripteur n'est ciblé que lorsqu'un même post produit plusieurs erreurs downstream, ce qui sert de proxy pour un problème amont mais ne garantit pas qu'un prompt descripteur sera réécrit sur tous les runs.
- **Contexte rewriter asymétrique** : quand la cible du rewrite est un classifieur, le rewriter reçoit les descriptions taxonomiques de cet axe uniquement. Quand la cible est le **descripteur**, il reçoit les 3 jeux de descriptions (formats visuels + catégories + stratégies), car le descripteur extrait des features consommées par les 3 classifieurs en aval.
- **Promotion atomique** : le changement de prompt actif (`retire` ancien + `activate` nouveau) se fait dans une seule transaction (`promote_prompt` avec `conn.transaction()`), ce qui évite un état transitoire sans prompt actif en cas de crash.

### Évaluation

**Pendant la simulation (dev)** : chaque post est classifié avec le prompt actif à ce moment de la simulation. Le match est calculé automatiquement. La courbe de convergence se dessine en rolling window (fenêtre de 50 posts). Les moments de rewrite (v0 -> v1 -> v2...) sont annotés sur la courbe.

**Évaluation finale (test)** : le prompt vN (dernier prompt actif après convergence) est évalué une seule fois sur les 437 posts test via le même script que le B0. Comparé au B0 (prompt v0 sur le même test set).

### Limites à documenter dans le mémoire

- **Dépendance au chemin** : l'ordre de présentation (seed=42) influence quels posts tombent dans quel batch. Un autre seed donnerait une trajectoire différente.
- **Variance** : un seul run, pas de moyenne sur 5 splits (contrainte de coût API). À compenser par les ablations.
- **Pas de validation fixe** : pas de dev_val séparé. La séparation temporelle (prequential) joue ce rôle. Le test reste strictement non utilisé avant l'évaluation finale.
- **Prequential, pas iid** : le protocole assume un ordre séquentiel, pas un échantillonnage iid. À présenter comme tel.

## Séparation backend / engine

```
milpo/              ← package Python : moteur MILPO
├── config.py       ← OpenRouter API key, model IDs
├── client.py       ← client OpenRouter (compatible OpenAI SDK)
├── router.py       ← routage déterministe FEED/REELS
├── schemas.py      ← DescriptorFeatures (Pydantic), PostPrediction
├── agent.py        ← descripteur multimodal + classifieurs tool use
├── inference.py    ← pipeline sync : router → descripteur → 3 classifieurs → stockage
├── async_inference.py ← pipeline async batch (semaphore, retry, concurrence)
├── db.py           ← accès BDD (taxonomie, posts, prompts, prédictions, api_calls)
├── gcs.py          ← signature URLs GCS (V4 Signed URLs, IAM Sign Blob)
├── errors.py       ← exceptions métier (LLMCallError)
├── rewriter.py     ← agent rewriter (ErrorCase, RewriteResult, appel LLM)
└── eval.py         ← métriques (accuracy, rolling, F1 macro, confusion)

apps/backend/       ← FastAPI : couche HTTP pour l'interface d'annotation
```

- Le **backend** gère les annotations humaines, le CRUD taxonomie, le serving des posts.
- Le **package `milpo/`** contient toute la logique IA : descripteur, classifieurs, rewriter, boucle d'optimisation, évaluation.
- Le backend peut importer `milpo` pour exposer des endpoints, mais la logique métier vit dans le package.
- Le package `milpo/` est utilisable indépendamment (scripts, simulations, éval CLI).
- **Prompts v0** : il n'y a plus de module Python pour les prompts v0. Les 6 prompts initiaux sont seedés en BDD via la migration SQL [`006_seed_prompts_v0.sql`](../apps/backend/migrations/006_seed_prompts_v0.sql) et chargés dynamiquement par `run_simulation.py` via `get_active_prompt(conn, agent, scope)`. La BDD est la source de vérité unique, lockée via git (toute modification nécessite une nouvelle migration). Référence humaine miroir : [`docs/prompts_v0.md`](./prompts_v0.md).

### Contraintes de séparation des données

| Split | Modèle prédit ? | Prompt optimisé dessus ? |
|-------|-----------------|--------------------------|
| **dev** (1 563) | ✅ oui | ✅ oui — les erreurs nourrissent le rewriter |
| **test** (437) | ❌ pas pendant l'optimisation | ❌ jamais — évaluation finale uniquement |

L'humain annote **en aveugle** (sans voir la prédiction du modèle) pour éviter le biais.

## Formalisation mathématique

### Notation

Soient :

- $`\mathcal{D} = \{(x_i, m_i)\}_{i=1}^{N}`$ l'ensemble des posts, où $`x_i = (\text{image}_i, \text{vidéo}_i, \text{audio}_i, \text{caption}_i)`$ est l'entrée multimodale et $`m_i \in \{\text{FEED}, \text{REELS}\}`$ le type de post.
- $`\mathcal{Y}_k^m`$ l'espace des labels pour l'axe $`k \in \{\text{cat}, \text{vf}, \text{str}\}`$, scopé par le type $`m`$. Pour `visual_format` : $`\mathcal{Y}_{\text{vf}}^{\text{FEED}} = \{\text{post\_*}\}`$ (44 labels), $`\mathcal{Y}_{\text{vf}}^{\text{REELS}} = \{\text{reel\_*}\}`$ (16 labels). Pour `cat` et `str`, l'espace est identique quel que soit $`m`$.
- $`\Delta^m`$ les descriptions taxonomiques scopées par type $`m`$ (rédigées par l'humain, fixes).
- $`I_t^{(k,m)}`$ les instructions actives à l'itération $`t`$ pour l'agent $`k`$ scopé au type $`m`$. **C'est la partie optimisée par MILPO.**
- $`p_t^{(k,m)} = \bigl(I_t^{(k,m)}, \Delta^m\bigr)`$ le prompt complet pour l'agent $`(k,m)`$ à l'itération $`t`$. Seul $`I_t`$ change au fil des itérations.
- $`f_\theta(x, p)`$ le modèle de vision-langage (paramètres $`\theta`$ fixés, prompt $`p`$ injecté).
- $`h(x_i)^k \in \mathcal{Y}_k^{m_i}`$ l'annotation humaine pour le post $`x_i`$ sur l'axe $`k`$.
- $`\mathcal{F}(x_i, p_{\text{desc}})`$ la sortie du descripteur — features JSON extraites du post $`x_i`$ avec le prompt $`p_{\text{desc}}`$.
- $`\mathcal{R}(I_t, E_t, \Delta)`$ le **rewriter** — fonction qui prend les instructions courantes, le buffer d'erreurs $`E_t`$ et les descriptions taxonomiques, et propose de nouvelles instructions candidates $`I_{t+1}^{\text{cand}}`$.
- $`\mathrm{m}(\mathcal{D}_{\text{eval}}, p)`$ la métrique d'accuracy sur un ensemble d'évaluation $`\mathcal{D}_{\text{eval}}`$ avec le prompt $`p`$.

Hyperparamètres fixés :

- $`B = 30`$ : taille du mini-batch d'erreurs avant trigger du rewriter
- $`\delta = 0{,}02`$ : seuil de gain minimum pour promotion d'un candidat
- $`\text{patience} = 3`$ : nombre de rewrites consécutifs sans promotion avant arrêt
- $`w_{\text{eval}} = 30`$ : taille du bloc d'évaluation post-rewrite

### Pipeline de classification d'un post

Pour un post $`x_i`$ de type $`m_i`$ :

```math
\text{features}_i = \mathcal{F}\bigl(x_i, p_t^{(\text{desc},\, m_i)}\bigr)
```

```math
\hat{y}_i^k = f_\theta\bigl( \text{features}_i,\, \text{caption}_i,\, p_t^{(k,\, m_i)} \bigr)
\quad \forall\, k \in \{\text{cat}, \text{vf}, \text{str}\}
```

Le pipeline appelle **1 fois le descripteur** (multimodal, coûteux) puis **3 fois les classifieurs** en parallèle (text-only, peu coûteux) — d'où l'économie de tokens visuels.

### Algorithme MILPO (simulation prequential)

L'humain annote d'abord tous les posts dev. La simulation rejoue ensuite les annotations dans l'ordre de présentation déterministe (`presentation_order`, `seed=42`) et optimise les instructions.

**Algorithme MILPO_Prequential**

- **Entrée** : $`\mathcal{D}_{\text{dev}} = \{(x_i, h(x_i))\}_{i=1}^{N_{\text{dev}}}`$, hyperparamètres $`B, \delta, \text{patience}, w_{\text{eval}}`$, modèle $`f_\theta`$, prompt initial $`I_0`$, descriptions $`\Delta`$
- **Sortie** : prompt final $`I_T`$

```text
 1.  t ← 0,  E_t ← ∅,  fails ← 0,  cursor ← 0
 2.  tant que cursor < N_dev faire
 3.      x_i ← D_dev[cursor]
 4.      features_i ← F( x_i, ( I_t^(desc, m_i), Δ^(m_i) ) )
 5.      pour chaque k ∈ {cat, vf, str} en parallèle faire
 6.          ŷ_i^k ← f_θ( features_i, caption_i, ( I_t^(k, m_i), Δ^(m_i) ) )
 7.      pour chaque k faire
 8.          si h(x_i)^k ≠ ŷ_i^k alors
 9.              E_t ← E_t ∪ { (x_i, features_i, h(x_i)^k, ŷ_i^k, k, m_i) }
10.      cursor ← cursor + 1
11.      si |E_t| ≥ B alors
12.          (k*, m*) ← pick_target(E_t)
13.          I_{t+1}^cand ← R( I_t^(k*, m*), E_t, Δ )
14.          S_eval ← D_dev[cursor : cursor + w_eval]
15.          acc_inc  ← m( S_eval, ( I_t^(k*, m*),   Δ ) )
16.          acc_cand ← m( S_eval, ( I_{t+1}^cand,   Δ ) )
17.          si acc_cand ≥ acc_inc + δ alors
18.              I_{t+1}^(k*, m*) ← I_{t+1}^cand
19.              t ← t + 1,  fails ← 0
20.          sinon
21.              fails ← fails + 1
22.          E_t ← ∅
23.          cursor ← cursor + w_eval
24.          si fails ≥ patience alors sortir
25.  retourner I_t
```

**Note** : les annotations $`h(x_i)`$ sont pré-existantes (annotation offline), la simulation les rejoue de façon déterministe. L'humain annote en aveugle (sans voir la prédiction du modèle) pour éviter le biais.

### Comparaison avec l'algorithme ProTeGi

Pour situer MILPO dans la filiation directe de ProTeGi (Pryzant et al. 2023), voici l'algorithme principal de ProTeGi (Algorithm 1 du papier, traduit) :

**Algorithme ProTeGi** (Pryzant et al., 2023)

- **Entrée** : prompt initial $`p_0`$, beam width $`b = 4`$, profondeur $`r = 6`$, métrique $`\mathrm{m}`$
- **Sortie** : meilleur prompt $`\hat{p}`$

```text
1.  B_0 ← { p_0 }
2.  pour i ← 1 à r-1 faire
3.      C ← ∅
4.      pour tout p ∈ B_i faire
5.          C ← C ∪ Expand(p)
6.      B_{i+1} ← Select_b(C, m)
7.  p̂ ← argmax_{p ∈ B_r} m(p)
8.  retourner p̂

Expand(p) :
  E1.  D_mini ⊂ D_train,  |D_mini| = 64
  E2.  évaluer p sur D_mini,  collecter les erreurs e
  E3.  g_1, ..., g_m ← LLM_∇(p, e)
  E4.  pour chaque g_i faire
  E5.      p'_{i1}, ..., p'_{iq} ← LLM_δ(p, g_i, e)
  E6.      pour chaque p'_{ij} faire
  E7.          p''_{ij1}, ..., p''_{ijp} ← LLM_mc(p'_{ij})
  E8.          retourner { p' } ∪ { p'' }
```

**Différences structurelles MILPO ↔ ProTeGi** :

| Aspect | ProTeGi | MILPO |
|---|---|---|
| Beam search | Oui ($`b=4`$) | Non (1 incumbent à la fois) |
| Sélection | Bandit (UCB / Successive Rejects) | Promotion si $`\text{acc}_{\text{cand}} \geq \text{acc}_{\text{inc}} + \delta`$ |
| LLMs dans la boucle | 3 (critic + editor + paraphraser) | 1 (rewriter unifié $`\mathcal{R}`$) |
| Cible de l'optimisation | 1 prompt $`p_0`$ | 6 prompts ($`\text{desc}`$ FEED/REELS + cat + vf FEED/REELS + str), sélection par `pick_target` |
| Search depth | 6 étapes fixes | Jusqu'à `patience` rewrites consécutifs sans promotion |
| Mini-batch | 64 exemples | 30 erreurs (pas exemples) |
| Modalité | Texte | Multimodal (image + vidéo + audio + texte) |

### Propriétés à analyser

- **Convergence** : le prompt se stabilise-t-il ? Mesurable via la courbe accuracy en rolling window (fenêtre 50) vs nombre d'annotations — on s'attend à un plateau.
- **Monotonicité** : le mécanisme de rollback garantit que la performance ne décroît pas (en théorie). À vérifier empiriquement via l'ablation A5 (sans rollback).
- **Efficacité en annotations** : combien d'annotations pour atteindre le plateau ? C'est le chiffre clé pour comprendre la dynamique de convergence et le coût d'annotation effectif.
- **Sensibilité à la taille de batch** : comment $`B`$ affecte-t-il la fréquence et la qualité des rewrites ? Ablations sur $`B \in \{1, 10, 30, 50\}`$ rejouables sur les mêmes annotations sans réannoter.
