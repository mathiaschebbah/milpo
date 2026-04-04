# Données

## Source

21 425 posts Instagram dont 21 065 @viewsfrance et 360 @miramagazine. L'échantillon de 2 000 posts est filtré sur **@viewsfrance uniquement** (ig_user_id = 17841403755827826).

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

- **Format visuel** : 59 classes, scopées par `media_product_type` :
  - `post_*` : 42 formats (FEED)
  - `reel_*` : 10 formats (REELS)
  - `story_*` : 7 formats (STORY)
- **Catégorie éditoriale** : 15 classes (mode, musique, sport, cinéma, société, art_culture, photographie, people, architecture_design, technologie, voyages, lifestyle, business, histoire, gastronomie)
- **Stratégie** : 2 classes (Organic, Brand Content)

## Splits

- 5 splits aléatoires stratifiés (seeds 1-5)
- 1 600 dev / 400 test (80/20)
- Stratification sur visual_format × strategy
