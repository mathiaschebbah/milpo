# Données

## Source

21 425 posts Instagram en BDD (21 065 @viewsfrance + 360 @miramagazine). L'échantillon de 2 000 posts est filtré sur **@viewsfrance uniquement** (ig_user_id = 17841403755827826).

## Fichiers (dans data/, gitignored)

| Fichier | Lignes | Description |
|---------|--------|-------------|
| `core_posts_rows.csv` | 21 425 | Posts (ig_media_id, shortcode, caption, timestamp, media_type, media_product_type, ...) |
| `core_post_categories_rows.csv` | 19 353 | Catégorisation heuristique v0 (category, subcategory, strategy, visual_format) |
| `core_post_media_rows.csv` | 84 019 | Médias individuels (URLs GCS, dimensions, durée, position dans le carousel) |

## Relations

```
core_posts.ig_media_id  ←1:1→  core_post_categories.ig_media_id
core_posts.ig_media_id  ←1:N→  core_post_media.parent_ig_media_id
```

- 2 072 posts sans catégorisation, 2 posts sans média
- En moyenne ~4 médias par post (carousels)

## Heuristique v0

Les catégories du CSV proviennent d'une pipeline de classification précédente construite par Mathias chez Views. Cette heuristique est **imprécise et incomplète**. HILPO vise à la remplacer par une pipeline performante et applicable en production.

L'interface d'annotation pré-remplira les catégories v0 — l'humain confirme ou corrige.

## Axes de classification

- **Format visuel** : 68 classes en BDD, scopées par `media_product_type` :
  - `post_*` : 45 formats (FEED)
  - `reel_*` : 15 formats (REELS)
  - `story_*` : 8 formats (STORY)
  - Note : le CSV d'origine contenait 45 formats (38 post + 7 reel). Les formats supplémentaires ont été ajoutés manuellement pendant l'annotation (ex: reel_throwback, post_views_magazine).
- **Catégorie éditoriale** : 15 classes (mode, musique, sport, cinéma, société, art_culture, photographie, people, architecture_design, technologie, voyages, lifestyle, business, histoire, gastronomie)
- **Stratégie** : 2 classes (Organic, Brand Content)

## Splits

- Échantillon actif : 2 000 posts (seed=42), split 1 563 dev / 437 test (~78/22)
- Stratification sur `media_product_type`

## Distribution du dataset

La distribution des formats visuels suit une **loi de puissance** : 8 formats couvrent 82% du dataset, 19 formats ont ≤ 1 occurrence dans le test.

| Tranche | Formats | % du test |
|---------|---------|-----------|
| > 10 posts | 8 formats | 81.7% |
| 2-10 posts | 16 formats | 13.3% |
| 1 seul post | 19 formats | 4.3% |

Le split test **préserve fidèlement** la distribution du dataset complet (20K posts) — les écarts de proportion sont < 4% pour tous les formats.

### Points notables

- **post_news domine** : 34% du test (37.8% du dataset complet)
- **Brand Content** : 9.4% du test — déséquilibré mais reflète la réalité du feed Views
- **0 stories** dans le test — trop rares (3% du dataset total, non échantillonnées)
- **16 formats uniquement dans test** (absents du dev) — tous à 1-2 occurrences. Sert de test de transfert zero-shot via descriptions.
- **2 catégories absentes** du test : nourriture, humour (trop rares)

### Implications méthodologiques

Le F1 macro sera reporté **avec et sans les classes rares** (< 5 occurrences) pour isoler l'effet de la longue traîne. Ce n'est pas un biais d'échantillonnage — c'est la distribution réelle du dataset. C'est un argument pour HILPO : les méthodes supervisées échouent sur la longue traîne (pas d'exemples), HILPO peut classifier via les descriptions taxonomiques.
