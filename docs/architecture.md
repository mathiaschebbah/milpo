# Architecture

## Pipeline multi-agents

Chaque post passe par un pipeline d'agents ultra-spécialisés pour éviter le context rot :

```
Post → Router → détecte le type (FEED/REELS/STORY)
                 ↓
         ┌───────┼───────┐
         ↓       ↓       ↓
    Agent       Agent    Agent
   catégorie  visual_f  stratégie
   (scopé)    (scopé)   (scopé)
```

### Agents

1. **Router** : détecte le type de post et dispatch vers les agents scopés
2. **Agent catégorie** : classifie parmi les 15 catégories éditoriales
3. **Agent visual_format** : classifie parmi les 44 formats visuels
4. **Agent stratégie** : détermine Organic vs Brand Content

### Prompts scopés

Chaque agent a un prompt par type de post. Ex : `agent_categorie × REELS` a son propre prompt, optimisé indépendamment de `agent_categorie × FEED`. Cela permet :
- D'adapter les instructions au média (vidéo vs image)
- D'optimiser chaque prompt sur son sous-ensemble de données
- D'utiliser Qwen 3.5 en mode vidéo pour les Reels

### Flux d'annotation (Phase 1-2)

1. L'humain ouvre l'interface de swipe
2. Un post s'affiche avec les labels v0 (heuristique) pré-remplis
3. L'humain confirme ou corrige → annotation stockée
4. En parallèle (Phase 2+), les agents prédisent → prédictions stockées
5. Comparaison annotation vs prédictions → match calculé

### Boucle HILPO (Phase 3)

1. Tous les B=30 erreurs d'un agent, le rewriter se déclenche
2. Le rewriter reçoit le prompt actif + le batch d'erreurs
3. Il propose un nouveau prompt → stocké en draft
4. Évaluation passive sur les posts suivants
5. Si accuracy ≥ ancienne → promotion en actif, sinon → rejeté

## Formalisation mathématique

### Notation

- **D** = {(x_i, m_i)} pour i=1..N : ensemble de posts, où x_i = (image_i, caption_i) est l'entrée multimodale et m_i ∈ {FEED, REELS, STORY} le type
- **Y_k** : espace des labels pour l'axe k ∈ {catégorie, visual_format, stratégie}
- **Δ** : descriptions taxonomiques (rédigées par l'humain, fixes). Définitions métier des labels injectées telles quelles dans le prompt.
- **I_t^(k,m)** : instructions actives à l'itération t pour l'agent k scopé au type m. C'est la partie optimisée par HILPO.
- **p_t = (I_t, Δ)** : prompt complet = instructions + descriptions. Seul I_t change au fil des itérations.
- **f_θ(x, p)** : modèle de vision-langage (paramètres θ fixés), prompt p
- **h(x_i) ∈ Y_k** : annotation humaine pour le post x_i

### Algorithme

```
Entrée : D, B (batch size = 30), f_θ, I_0 (instructions initiales), Δ (descriptions fixes)
Sortie : I_T (instructions optimisées), annotations {h(x_i)}

t ← 0
E_t ← ∅                                  // buffer d'erreurs

Pour chaque post x_i présenté à l'humain :
    1. Collecter h(x_i)                   // annotation humaine
    2. ŷ_i ← f_θ(x_i, (I_t, Δ))         // prédiction avec prompt complet
    3. Si h(x_i) ≠ ŷ_i :
         E_t ← E_t ∪ {(x_i, h(x_i), ŷ_i)}
    4. Si |E_t| ≥ B :
         I_{t+1} ← R(I_t, E_t, Δ)       // rewriter : voit Δ, ne modifie que I
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
