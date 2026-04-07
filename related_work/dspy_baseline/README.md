# DSPy MIPROv2 baseline

Implémentation de DSPy MIPROv2 (Stanford) appliquée au pipeline de
classification multimodale MILPO, dans le but de produire un baseline
empirique comparable au B0 humain et aux runs MILPO Phase 3.

## Motivation

MILPO adapte une boucle d'optimisation de prompt par gradient textuel (style
ProTeGi, Pryzant et al. 2023) à un cas industriel multimodal de
classification de posts Instagram pour Views. Après le reframing du 7 avril
(cf. `CLAUDE.md` v3.0), le mémoire bascule sur un positionnement
« ingénieur-chercheur » : MILPO ne prétend plus être une méthode novatrice,
c'est une étude empirique sur taxonomie subjective à longue traîne.

Pour défendre ce positionnement face à un jury, il faut mesurer empiriquement
ce que ferait l'**état de l'art générique** sur le même problème. DSPy
MIPROv2 est le candidat naturel : framework SOTA, supporte multi-stage et
petits datasets, optimise instructions + few-shot examples conjointement.

## Question expérimentale

> Si on optimise les 4 prompts classifieurs (category, visual_format FEED,
> visual_format REELS, strategy) avec MIPROv2 sur le dev split de Views,
> quels chiffres obtient-on sur le test split, par rapport au B0 humain
> (86,7% / 65,4% / 94,5%) et au futur MILPO Phase 3 ?

## Architecture : DSPy = générateur, MILPO = runtime d'évaluation

C'est la décision structurante de ce baseline.

DSPy reste un **outil hors-ligne** dont la seule sortie utile est une string
d'instructions optimisées par axe. Cette string est ensuite **insérée dans
la table `prompt_versions`** (avec `source='dspy_constrained'` ou `'dspy_free'`)
et **évaluée via le runtime MILPO existant** (`scripts/run_baseline.py`,
qui fait le tool calling Qwen forcé, l'async batching, le parsing strict,
le stockage en BDD).

Cela garantit que la comparaison avec B0 est strictement apples-to-apples :
**la seule variable qui change entre B0 et B_dspy est la string
d'instructions**. Le modèle, le runtime, le tool calling, l'async, les
posts test, le parsing : tout est identique.

En bonus, on lance aussi une **évaluation native DSPy** des mêmes
programmes compilés (via `evaluate_native.py`) pour mesurer la contribution
empirique du runtime à la performance. La différence
`B_dspy_native_{mode} − B_dspy_in_milpo_{mode}` est un résultat exploitable
en discussion : « voilà combien de points d'accuracy le runtime a coûté ou
gagné, indépendamment de la qualité des instructions optimisées ».

## Deux modes d'optimisation

| Mode                | Surface optimisée par MIPROv2          | Comparable à MILPO ? |
|---------------------|-----------------------------------------|-----------------------|
| **constrained**     | Instructions seulement, descriptions taxonomiques fixes (`dspy.InputField`) | ✅ strict apples-to-apples — MILPO ne touche pas non plus les descriptions (cf. `milpo/rewriter.py:46`) |
| **free**            | Tout — descriptions injectées dans le docstring de la signature, MIPROv2 peut tout réécrire | ❌ asymétrique — borne supérieure / mesure du « coût de l'invariant humain » |

## Périmètre : 4 classifieurs, descripteur gelé

DSPy n'optimise que les **4 classifieurs text-only** :

- `category` (15 classes)
- `visual_format` FEED (44 classes, 192 examples dev annotés)
- `visual_format` REELS (16 classes, 45 examples dev annotés)
- `strategy` (2 classes)

Les **2 prompts du descripteur** restent en `human_v0` dans tous les runs DSPy,
parce que :

1. DSPy gère mal la vidéo nativement (`dspy.Image` ne couvre pas les
   `video_url` Gemini 3) — wrapper custom requis = 2-3 jours de plomberie
   sans contribution intellectuelle
2. Les features descripteur sont **déjà cachées en BDD pour les 437 posts
   test** (run id=7, B0). On n'a pas à les régénérer, et l'évaluation est
   purement déterministe au niveau des features
3. Geler le descripteur isole proprement la variable d'intérêt : « les
   instructions de classification produites par MIPROv2 sont-elles
   meilleures que celles écrites par l'humain v0, étant donné des features
   identiques ? »

## État du dataset à la date d'écriture (2026-04-08)

- **Test split** : 437 posts annotés, **features descripteur déjà cachées**
  (run B0 id=7). Apples-to-apples assuré sur l'évaluation finale.
- **Dev split** : 237 posts annotés (192 FEED + 45 REELS), 25 visual_formats
  FEED distincts, 9 visual_formats REELS distincts. **Aucune feature
  cachée** → `scripts/extract_features_dev.py` doit être lancé en premier.

Le run REELS visual_format est le plus tendu : 45 posts × 9 classes ≈ 5
exemples par classe. C'est borderline pour MIPROv2. Si les annotations dev
augmentent (idéalement à 400-500+ posts), la robustesse statistique de
l'optim s'améliorera mécaniquement.

## Structure du dossier

```
related_work/dspy_baseline/
├── README.md            # ce fichier
├── __init__.py
├── data.py              # load_examples, load_descriptions, split_train_val
├── metrics.py           # accuracy_metric (utilisée par MIPROv2)
├── pipeline.py          # signatures DSPy + modules constrained/free
├── optimize.py          # script principal MIPROv2
├── evaluate_native.py   # éval bonus en runtime DSPy
├── import_to_db.py      # extrait les instructions et insère en prompt_versions
└── compiled/            # programmes compilés sortis de optimize.py (gitignored hors .gitkeep)
    └── .gitkeep
```

## Caveats documentés

1. **Runtime DSPy ≠ runtime MILPO**. Le runtime DSPy utilise un
   `JSONAdapter` ou `ChatAdapter` qui parse la sortie texte avec des marqueurs
   `[[ ## field ## ]]`. Le runtime MILPO utilise du **tool calling Qwen
   forcé** (`tool_choice="auto"`) avec un enum fermé sur les labels valides.
   Ce sont deux mécanismes différents qui peuvent donner des chiffres
   différents pour les mêmes instructions. C'est précisément la raison
   pour laquelle on évalue les prompts optimisés par DSPy **dans le
   runtime MILPO** (cf. flux ci-dessous), tout en gardant les chiffres
   natifs DSPy en bonus.

2. **Petit dev split**. Avec 237 annotations dev (45 pour REELS), MIPROv2
   tourne sur la borne basse de ce qui est statistiquement raisonnable.
   Les chiffres produits sont une *borne basse* de ce que DSPy peut faire.
   Re-lancer après plus d'annotations donnera de meilleurs résultats.

3. **Descripteur gelé**. On ne mesure pas la capacité de DSPy à optimiser
   un pipeline multi-stage end-to-end avec multimodal. On mesure seulement
   la capacité à optimiser 3 prompts text-only avec features fixes. C'est
   une simplification consciente.

4. **Cardinalité élevée et output free-form**. DSPy ne contraint pas les
   sorties à un enum fermé comme le tool calling MILPO. Le LM peut générer
   un label hors-enum, ce qui est compté comme une erreur stricte par
   `metrics.py`. Pas de fuzzy matching — on veut que les prompts optimisés
   produisent des labels exactement valides.

5. **Zero-shot only**. On utilise `max_bootstrapped_demos=0` et
   `max_labeled_demos=0` dans MIPROv2. Pas de few-shot demos. Raisons : la
   cardinalité élevée du visual_format rend le bootstrap peu fiable, et on
   compare à MILPO qui n'utilise pas non plus de demos. Si on lève cette
   contrainte, la comparaison à MILPO devient asymétrique.

## Flux de reproduction

**Préalable** : migration `007_prompt_source.sql` appliquée en BDD.
```bash
PGPASSWORD=hilpo psql -h localhost -p 5433 -U hilpo -d hilpo \
    -f apps/backend/migrations/007_prompt_source.sql
```

**Étape 1 — Extraction des features dev** (one-shot, ~$1, ~5 min) :
```bash
.venv/bin/python scripts/extract_features_dev.py
```

**Étape 2 — Optimisation MIPROv2** (8 runs au total — 4 axes × 2 modes,
~$15-25, ~3-6h) :
```bash
# Mode constrained (apples-to-apples avec MILPO)
.venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis category --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis visual_format --scope FEED --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis visual_format --scope REELS --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode constrained --axis strategy --auto medium

# Mode free (MIPROv2 peut tout réécrire)
.venv/bin/python -m related_work.dspy_baseline.optimize --mode free --axis category --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode free --axis visual_format --scope FEED --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode free --axis visual_format --scope REELS --auto medium
.venv/bin/python -m related_work.dspy_baseline.optimize --mode free --axis strategy --auto medium
```

> Conseil : commencer par un run pilote `--mode constrained --axis category --auto light` (~10 min, ~$1) pour valider le pipeline d'optim avant de lancer les 8 runs complets.

**Étape 3 — Évaluation native DSPy** (bonus, ~$2, ~10 min) :
```bash
.venv/bin/python -m related_work.dspy_baseline.evaluate_native --mode constrained
.venv/bin/python -m related_work.dspy_baseline.evaluate_native --mode free
```

**Étape 4 — Import en BDD** (pas d'appel LLM) :
```bash
.venv/bin/python -m related_work.dspy_baseline.import_to_db --mode constrained
.venv/bin/python -m related_work.dspy_baseline.import_to_db --mode free
```

**Étape 5 — Évaluation apples-to-apples via runtime MILPO** (~$5, ~50 min) :
```bash
uv run python scripts/run_baseline.py --prompts dspy_constrained
uv run python scripts/run_baseline.py --prompts dspy_free
```

**Étape 6 — Lecture des chiffres** :
```sql
SELECT
    config->>'name' AS run,
    final_accuracy_category,
    final_accuracy_visual_format,
    final_accuracy_strategy,
    total_cost_usd
FROM simulation_runs
WHERE config->>'name' LIKE 'B%'
ORDER BY id;
```

## Décisions par défaut

| Paramètre              | Valeur                                            |
|------------------------|---------------------------------------------------|
| Task LM                | `openrouter/qwen/qwen3.5-flash-02-23` (= MILPO)   |
| Proposer LM            | `openrouter/anthropic/claude-opus-4-6`            |
| Temperature task       | `0.1` (= MILPO)                                   |
| Temperature proposer   | `1.0` (exploration de candidats d'instructions)   |
| MIPROv2 auto level     | `medium` (run pilote en `light`)                  |
| `max_bootstrapped_demos` | `0` (zero-shot only)                            |
| `max_labeled_demos`    | `0` (zero-shot only)                              |
| Train/val split        | 80/20 déterministe, seed=42                       |
| Métrique               | accuracy strict (1.0/0.0), pas de fuzzy           |

## Coût total estimé

| Étape                  | Coût      | Durée    |
|------------------------|-----------|----------|
| extract_features_dev   | ~$1       | ~5 min   |
| optimize (8 runs)      | ~$15-25   | ~3-6h    |
| evaluate_native (× 2)  | ~$2       | ~10 min  |
| run_baseline (× 2)     | ~$5       | ~50 min  |
| **Total**              | **~$25-35** | **~5-8h** |

## Hors scope (intentionnel)

- Optimisation du descripteur par DSPy
- Comparaison à d'autres frameworks (APE, PromptWizard) — peuvent faire
  l'objet d'autres dossiers `related_work/foo_baseline/`
- Adapter DSPy custom qui ferait du tool calling Qwen au runtime DSPy
  (gain marginal pour beaucoup d'effort)
