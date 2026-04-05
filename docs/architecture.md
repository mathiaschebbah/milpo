# Architecture

## Pipeline multi-agents

Chaque post passe par un pipeline en deux étapes : un **descripteur** multimodal extrait les features visuelles, puis 3 **classifieurs** text-only prédisent en parallèle.

```
Post → Router → détecte le type (FEED/REELS)
                 ↓
         Descripteur (multimodal)
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

2. **Descripteur** (multimodal) : reçoit les médias (toutes les slides carousel, vidéo, audio pour les reels) + la caption + les critères discriminants du scope. Retourne un JSON structuré de features visuelles + un résumé libre insightful. **Son prompt est optimisable par HILPO.**

3. **Agent catégorie** (text-only) : classifie parmi les 15 catégories éditoriales. Reçoit le JSON de features + la caption brute + les descriptions des 15 catégories.

4. **Agent visual_format** (text-only) : classifie parmi le sous-ensemble de formats visuels **scopé par type** :
   - FEED → `post_*` (44 formats)
   - REELS → `reel_*` (16 formats)

5. **Agent stratégie** (text-only) : détermine Organic vs Brand Content. Reçoit le JSON de features + la caption brute.

### Modèles via OpenRouter

| Rôle | Scope | Modèle | Modalités | Prix input/1M |
|------|-------|--------|-----------|---------------|
| Descripteur | FEED | Qwen 3.5 Flash | image + vidéo + texte | $0.065 |
| Descripteur | REELS | Gemini 2.5 Flash | image + vidéo + audio + texte | $0.30 |
| Classifieurs (×3) | tous | Qwen 3.5 Flash | texte seul | $0.065 |

Choix du modèle REELS : Gemini 2.5 Flash est le seul modèle pas cher qui gère l'audio — nécessaire pour `reel_voix_off` et les formats avec narration.

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
│ Instructions I_t (OPTIMISÉES par HILPO) │
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

### Flux d'annotation (Phase 1-2)

1. L'humain ouvre l'interface de swipe
2. Un post s'affiche avec les labels v0 (heuristique) pré-remplis
3. L'humain confirme ou corrige → annotation stockée
4. En parallèle (Phase 2+), le descripteur analyse le post → 3 classifieurs prédisent
5. Comparaison annotation vs prédictions → match calculé

### Boucle HILPO (Phase 3)

1. Tous les B=30 erreurs d'un agent, le rewriter se déclenche
2. Le rewriter reçoit le prompt actif + le batch d'erreurs
3. Il propose un nouveau prompt → stocké en draft
4. Évaluation passive sur les posts suivants
5. Si accuracy ≥ ancienne → promotion en actif, sinon → rejeté

Note : le rewriter peut optimiser le prompt du descripteur ET des classifieurs (2 niveaux d'optimisation).

## Séparation backend / engine

```
hilpo/              ← package Python : moteur HILPO
├── config.py       ← OpenRouter API key, model IDs
├── client.py       ← client OpenRouter (compatible OpenAI SDK)
├── router.py       ← routage déterministe FEED/REELS
├── schemas.py      ← DescriptorFeatures (Pydantic), PostPrediction
├── agent.py        ← descripteur multimodal + classifieurs tool use
├── inference.py    ← pipeline : router → descripteur → 3 classifieurs → stockage
├── db.py           ← accès BDD (taxonomie, posts, prompts, prédictions, api_calls)
├── gcs.py          ← signature URLs GCS (V4 Signed URLs, IAM Sign Blob)
├── prompts_v0.py   ← prompts initiaux (6 instructions v0)
└── eval.py         ← métriques (F1, kappa, confusion) — à implémenter

apps/backend/       ← FastAPI : couche HTTP pour l'interface d'annotation
```

- Le **backend** gère les annotations humaines, le CRUD taxonomie, le serving des posts.
- Le **package `hilpo/`** contient toute la logique IA : descripteur, classifieurs, rewriter, boucle d'optimisation, évaluation.
- Le backend peut importer `hilpo` pour exposer des endpoints, mais la logique métier vit dans le package.
- Le package `hilpo/` est utilisable indépendamment (scripts, simulations, éval CLI).

### Contraintes de séparation des données

| Split | Modèle prédit ? | Prompt optimisé dessus ? |
|-------|-----------------|--------------------------|
| **dev** (1 563) | ✅ oui | ✅ oui — les erreurs nourrissent le rewriter |
| **test** (437) | ❌ pas pendant l'optimisation | ❌ jamais — évaluation finale uniquement |

L'humain annote **en aveugle** (sans voir la prédiction du modèle) pour éviter le biais.

## Formalisation mathématique

### Notation

- **D** = {(x_i, m_i)} pour i=1..N : ensemble de posts, où x_i = (image_i, caption_i) est l'entrée multimodale et m_i ∈ {FEED, REELS} le type
- **Y_k^m** : espace des labels pour l'axe k ∈ {catégorie, visual_format, stratégie}, scopé par le type m. Pour visual_format : Y_vf^FEED = {post_*}, Y_vf^REELS = {reel_*}. Pour catégorie et stratégie : identique quel que soit m.
- **Δ^m** : descriptions taxonomiques scopées par type m (rédigées par l'humain, fixes). Pour visual_format, seules les descriptions des formats du scope m sont injectées dans le prompt.
- **I_t^(k,m)** : instructions actives à l'itération t pour l'agent k scopé au type m. C'est la partie optimisée par HILPO.
- **p_t = (I_t, Δ^m)** : prompt complet = instructions + descriptions scopées. Seul I_t change au fil des itérations.
- **f_θ(x, p)** : modèle de vision-langage (paramètres θ fixés), prompt p
- **h(x_i) ∈ Y_k** : annotation humaine pour le post x_i
- **D(x_i, p_desc)** : sortie du descripteur — features JSON extraites du post x_i avec le prompt p_desc

### Algorithme (avec descripteur)

```
Entrée : D, B (batch size = 30), f_θ, I_0 (instructions initiales), Δ (descriptions fixes)
Sortie : I_T (instructions optimisées), annotations {h(x_i)}

t ← 0
E_t ← ∅                                  // buffer d'erreurs

Pour chaque post x_i présenté à l'humain :
    1. Collecter h(x_i)                   // annotation humaine
    2. features_i ← D(x_i, (I_t^desc, Δ^m))  // descripteur multimodal
    3. Pour chaque axe k en parallèle :
         ŷ_i^k ← f_θ(features_i, caption_i, (I_t^k, Δ^m))  // classifieur text-only
    4. Si h(x_i) ≠ ŷ_i pour un axe k :
         E_t ��� E_t ∪ {(x_i, features_i, h(x_i), ŷ_i)}
    5. Si |E_t| ≥ B :
         I_{t+1} ← R(I_t, E_t, Δ)       // rewriter : peut modifier desc + classifieurs
         Si acc((I_{t+1}, Δ)) ≥ acc((I_t, Δ)) sur fenêtre de validation :
             t ← t + 1                   // promotion
         Sinon :
             rejeter I_{t+1}             // rollback
         E_t ← ∅                         // reset buffer

Retourner I_t
```

### Propriétés à analyser

- **Convergence** : le prompt se stabilise-t-il ? Mesurable via la courbe accuracy vs nombre d'annotations — on s'attend à un plateau
- **Monotonicité** : le mécanisme de rollback garantit que la performance ne décroît pas (en théorie). À vérifier empiriquement via l'ablation A5 (sans rollback)
- **Efficacité en annotations** : combien d'annotations pour atteindre le plateau ? C'est le chiffre clé pour valider H1 (≤ 200 par axe)
