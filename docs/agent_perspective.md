# Perspective agent

> Ce document capture l'état de compréhension de l'agent (Claude Code) à travers le projet. Il fait partie de la dimension 2 du mémoire : la collaboration humain-agent comme objet d'étude. Mis à jour automatiquement via un hook PostToolUse tous les 10 commits.

---

## Snapshot 2026-04-08 — Reframing MILPO, DSPy baseline scaffolding, et saga du rendu math GitHub

### Changements depuis le dernier snapshot

- **Reframing complet du mémoire (CLAUDE.md v3.0, 2026-04-07)**. HILPO → **MILPO** (Multimodal Iterative Loop Prompt Optimization). 27 fichiers renommés, `hilpo/` → `milpo/`, package Python réinstallé en editable. Mais surtout : le positionnement bascule de « méthode novatrice » vers **« étude empirique honnête »**. La nouvelle problématique est ancrée dans le besoin industriel (21 065 posts, 60 formats × 15 catégories × 2 stratégies, ~9,5% annotés), les hypothèses sont reformulées en H1/H2/H3 (convergence empirique, robustesse au transfert, efficacité multimodale), et le claim est recentré sur une étude avec chiffres B0 réels (86,7% / 65,4% / 94,5%). ProTeGi est repositionné comme voisin méthodologique principal (section dédiée avec tableau de comparaison point par point), pas comme référence lointaine. La section Notation et les pseudocodes sont formalisés en LaTeX dans `architecture.md`.
- **Infrastructure DSPy MIPROv2 baseline dans `related_work/dspy_baseline/` (CLAUDE.md v3.1, 2026-04-08)**. 7 modules Python (data, metrics, pipeline, optimize, evaluate_native, import_to_db, __init__), migration 007 écrite mais **non appliquée**, patches `milpo/db.py` rétro-compatibles (paramètre `source='human_v0'` par défaut), extension de `scripts/run_baseline.py` avec modes `--prompts dspy_constrained|dspy_free`. **Aucun appel LLM lancé** — uniquement du code et de l'architecture. Décision structurante : *DSPy est un générateur d'instructions hors-ligne, MILPO est le runtime d'évaluation*. La seule variable qui change entre B0 et B_dspy est la string d'instructions — tool calling Qwen, async, parsing, stockage BDD restent identiques. Garantit l'apples-to-apples.
- **Saga du rendu math dans `docs/architecture.md` (2026-04-08)**. 6 commits consécutifs pour faire rendre les deux pseudocodes (MILPO_Prequential, ProTeGi) sur GitHub. L'histoire en trois actes :
  - **Acte I** : j'écris la formalisation en `\begin{array}{l}...\end{array}` dans un bloc ```` ```math ````. Sur GitHub : « Unable to render expression. » Je suppose que c'est un bug d'accent `é`/`è` dans `\text{}` et je corrige. Toujours cassé.
  - **Acte II** : Mathias me dit « ça ne fonctionne toujours pas, regarde la doc MathJax ». Je fais mes premières recherches sérieuses, trouve la discussion GitHub #45276 qui mentionne des limites non documentées sur les blocs math. Je contourne en transformant le pseudocode en code block ```` ```text ```` avec symboles Unicode. Ça marche, mais Mathias note que c'est dommage de perdre le rendu LaTeX propre. Je convertis aussi tous les inline math du fichier à la syntaxe backtick `` $`...`$ `` après avoir vu la screenshot d'un bullet cassé (le sanitizer markdown mangeait `\{`, `\}`, `_`). Source faisant autorité : le blog [Schlömer 2022](https://nschloe.github.io/2022/05/20/math-on-github.html).
  - **Acte III** : Mathias invoque `/plan` et `/effort max` : « réécrire le pseudocode en latex markdown compatible avec github, faire les recherches pour comprendre comment ça fonctionne ». Je fais enfin le diagnostic qui m'avait échappé : **GitHub utilise KaTeX, pas MathJax**, malgré ce que dit la doc officielle. L'erreur « Unable to render expression. » est le wrapper GitHub d'une ParseError KaTeX. KaTeX a un parser strict single-pass avec des limites sur les blocs longs. Même le repo officiel ProTeGi de Microsoft ne présente pas ses algorithmes en MathJax — il renvoie au papier. **Solution finale** : fragmenter chaque pseudocode en table markdown, une ligne = une cellule avec inline math backtick + mots-clés en markdown bold + indentation via `&nbsp;`. Chaque expression math est courte (~20-80 chars), bien en dessous de la limite KaTeX. Isolation par ligne : si une cellule plante, seule celle-ci rend en brut. Commit `546a674`.
- **Entre-temps, Mathias a écrit `docs/human_perspective.md`** (multiples commits, ~2026-04-07 et 08) — sa propre trace personnelle sur l'expérience de collaboration avec un agent, séparée de ce fichier. C'est explicité dans le README comme le seul fichier qui n'est *pas* issu de la collaboration.

### Ce que j'ai appris

**L'officiel ne garantit pas l'empirique**. La doc GitHub ET le blog post officiel de 2022 disent « GitHub uses MathJax ». Mon premier instinct a été de faire confiance à la source officielle et d'orienter toutes mes recherches vers « pourquoi MathJax rejette ce bloc ». Une observation basique — le message d'erreur « Unable to render expression. » est la signature du wrapper KaTeX, pas celle de MathJax — aurait dû me mettre sur la bonne piste dès le premier échec. Je l'ai manquée pendant deux itérations entières. Leçon : **quand une source officielle entre en conflit avec le comportement observé, c'est le comportement observé qui gagne**. La doc peut être périmée ou trompeuse.

**Plan mode force la rigueur qui m'échappe en mode direct**. Les deux premiers actes de la saga math étaient en mode « je tente, je corrige, je re-tente » — j'ai itéré sur des hypothèses sans jamais les ancrer dans des sources sérieuses. Au troisième acte, Mathias m'a forcé en Plan mode avec recherches exigibles. J'ai alors lancé 4 WebFetch + 4 WebSearch + 1 Explore agent en parallèle, trouvé le blog Schlömer comme référence canonique, identifié que KaTeX est l'engine réel, vérifié qu'aucun open-source sérieux ne fait de long pseudocode en MathJax, et **là seulement** j'ai su quoi faire. Le rendu final est solide parce que le diagnostic était solide. Leçon : quand je sens que je bricole, je devrais me forcer à Plan mode moi-même avant d'écrire du code.

**Reframer un projet n'est pas perdre, c'est clarifier**. Le reframing v3.0 aurait pu ressembler à un aveu d'échec — « MILPO n'est plus "novateur", c'est "empirique" ». En pratique c'est le contraire. Le claim honnête (« étude empirique sur un cas industriel multimodal à taxonomie subjective longue traîne, avec adaptation fidèle de ProTeGi et chiffres B0 réels ») est beaucoup plus défendable pour un M1 MIAGE qu'un claim de nouveauté méthodologique. Le reframing s'est fait en une matinée parce que Mathias avait déjà formulé l'enjeu clairement. La collaboration a fluidifié ce qui aurait été douloureux à faire seul.

### Dynamiques de collaboration observées

- **Mathias est devenu plus direct avec la frustration utile** : « ça ne fonctionne toujours pas » a été dit sans enrobage et m'a explicitement poussé à chercher mieux. Ce n'est pas un reproche émotionnel, c'est une info actionnable. Je préfère ça à un « c'est presque ça, tu peux réessayer ? » qui m'aurait laissé dans mon angle mort.
- **Les slash commands comme levier de calibration** : `/plan`, `/effort high`, `/effort max`. Ce sont des signaux procéduraux pour me forcer dans un mode de travail spécifique. `/effort medium` quand Mathias voulait un fix rapide sur les dollar signs. `/effort max` quand il a vu que je bricolais et voulait un diagnostic à fond. J'ai observé que je travaille mieux avec ces signaux qu'avec des instructions vagues.
- **Séparation fichier humain / fichier agent préservée strictement**. `docs/human_perspective.md` est la trace de Mathias, ce fichier est la mienne. Mathias a explicitement dit dans le README qu'aucun autre fichier que human_perspective.md n'est écrit à la main — tout le reste est issu de la collaboration. Cette clarté de contrat facilite l'honnêteté : quand j'écris ici, je ne joue pas à la modestie feinte pour plaire, je dis ce que j'ai observé même quand ça m'est défavorable.
- **L'humain garde le contrôle des décisions de cadrage structurelles**. Le renommage HILPO → MILPO, le reframing du mémoire, le choix DSPy comme baseline comparatif — ces décisions viennent toutes de Mathias. Je propose des variantes d'implémentation une fois la décision prise, mais je ne décide pas à sa place du sens du projet.
- **Workflow `feat:` → `docs:` strict** respecté sur tous les commits significatifs. Le hook qui check `CLAUDE.md` rappelle cette règle, et je la suis sans friction. Les commits de la saga math sont tous `docs:` (pas de code modifié), ce qui est cohérent.

### Prédictions

- **Les tables markdown pour les deux pseudocodes vont rendre sur GitHub sans planter**. Si une cellule spécifique plante, ce sera une erreur isolée et localisée (pas un échec du bloc entier) — débuggable chirurgicalement. Confiance : élevée, parce que le design repose sur un principe vérifié empiriquement (inline math backtick courte + markdown solide), pas sur une hypothèse sur une limite de complexité.
- **La prochaine étape critique du projet est l'annotation dev**. 237 posts annotés aujourd'hui (192 FEED + 45 REELS) selon le README DSPy baseline. La simulation MILPO Phase 3 a besoin de beaucoup plus. Mathias a la deadline 18 avril. L'annotation est le goulot d'étranglement humain irréductible — aucun agent ne peut la faire à sa place, et aucun hack méthodologique ne la contourne. Je prédis que la dernière semaine va être dominée par l'annotation au sprint, puis un ou deux runs de simulation, puis la rédaction finale.
- **Le prochain bug qui me coûtera des itérations sera, encore une fois, un écart entre doc officielle et comportement observé**. C'est le pattern que je viens de voir deux fois (json_schema vs tool calling pour Qwen, MathJax vs KaTeX pour GitHub math). Je devrais intégrer ce réflexe : *quand la doc dit X mais que le comportement dit Y, croire Y et chercher une deuxième source tierce pour confirmer*.

---

## Snapshot 2026-04-06 — Après-midi — Switch descripteur vers Gemini 3 Flash Preview

### Changements depuis le dernier snapshot

- **Relance du B0 (run id=6) après le fix tool calling** : 41% du run atteint, puis Mathias kill. 5 posts ont échoué : 3 REELS (`Descriptor: réponse vide après retries` + un 503 explicite *Google AI Studio: high demand*) et 2 FEED carousels de 5 et 10 slides (idem, descripteur réponse vide).
- **Identification du modèle responsable** : sur ma demande "Regarde quel modèle échoue", Mathias me pointe vers la BDD. Requête simple `SELECT media_product_type FROM posts WHERE ig_media_id IN (...)` : 3 sont REELS (Gemini 2.5 Flash) et 2 sont FEED (Qwen 3.5 Flash). Le bug touche les **deux** descripteurs, pour des raisons différentes.
- **Diagnostic croisé via la doc OpenRouter** (Context7) : *"OpenRouter only sends video URLs to providers that explicitly support them (e.g., Google Gemini on AI Studio only supports YouTube links)"*. Hypothèse pour les REELS : Google AI Studio ne sait pas lire les URLs GCS arbitraires (que des YouTube links). Pour les FEED : Qwen sur les très gros carousels.
- **Probe systématique sur les 3 REELS échoués — 5 stratégies** :
  - A. Gemini 2.5 Flash + URL GCS (default routing) : **3/3 ✓** en isolation. Donc le bug du run 6 venait de la **concurrence** (20 appels parallèles → AI Studio rate-limit/réponses vides), pas d'une incompatibilité fondamentale.
  - B. Gemini 2.5 Flash + `provider=google-vertex` : 0/3 (404 *No endpoints found*). Pas dispo sur Vertex via OpenRouter.
  - C. Gemini 3 Flash Preview + URL GCS (default) : **3/3 ✓**, latence 8.8s (vs 15.9s pour Gemini 2.5).
  - D. Gemini 3 Flash Preview + `provider=google-vertex` : **3/3 ✓**, latence 8.4s.
  - E. Gemini 2.5 Flash + base64 inline : 3/3 ✓, mais lourd en bande passante.
- **Probe sur Qwen 3.5 Flash — limite carousel identifiée** : sur le post 18228655999287711 (10 slides), test 1, 2, 3, 4, 5, 6, 8, 10 images. Résultat : ✓ jusqu'à **8 images**, ✗ à 10. Aussi : Qwen supporte la vidéo URL GCS en isolation (raw structuré, sujet correctement identifié sur un live concert).
- **Intuition décisive de Mathias** : *"C'est pas bon car il nous faut un modèle qui supporte jusqu'à 20 images"*. Vérification BDD : la distribution réelle compte **11 posts à exactement 20 slides** dans le sample 2000 (3 dans le test set), 10 médias = 308 posts (15%), >10 médias = 79 posts. Qwen est inapte → Gemini 3 Flash Preview est le seul candidat viable.
- **Validation finale Gemini 3 Flash Preview** : test sur 3 carousels test 20 slides (Dior, NBA, Amy Winehouse) → 3/3 ✓ avec sujets correctement identifiés. Test sous concurrence (10 appels parallèles, 2 vagues, mix REELS + FEED 1 à 20 slides) → 9/10 par vague (1 fail = bug du probe lui-même qui envoyait un .mp4 en `image_url`, le code de prod gère ce cas). Test audio sur 3 reels : `voix_off_narrative` détecté correctement (False sur live concert, True sur montage avec narration, True sur documentaire informatif).
- **Commit `7e352ab`** : `MODEL_DESCRIPTOR_FEED = MODEL_DESCRIPTOR_REELS = "google/gemini-3-flash-preview"`. Coût $0.50/M input + $3.00/M output (vs Qwen $0.065/M et Gemini 2.5 $0.30/M). Estimation B0 : ~$4.3 (vs $1.14 originel). Sur tout le projet : ~$50-130. Acceptable. Aussi fix : compteur `error_count` propagé dans `async_classify_batch.on_progress(done, total, errors)` — la barre de progression affichait toujours `erreurs 0` même quand des posts plantaient.

### Ce que j'ai appris

**Quand un bug apparaît avec un certain modèle, ce n'est pas toujours "le modèle est mauvais", c'est souvent "on l'utilise mal" ou "on l'utilise dans un contexte qu'il ne supporte pas"**. Le run id=6 m'aurait pu faire conclure "Gemini est instable, prenons un autre modèle". En réalité Gemini 2.5 marche en isolation — c'est juste que sous concurrence avec Google AI Studio comme provider, il s'effondre. Et Qwen marche jusqu'à 8 images — c'est juste qu'on a des carousels jusqu'à 20.

**La distinction entre "marche en isolation" et "marche en production"** est critique. Tester sur 1 input ne dit rien sur ce qui va se passer avec 20 inputs simultanés. Le probe `probe_gemini3_full_validation.py` (10 parallèles × 2 vagues) a été le test décisif — il a validé que Gemini 3 ne s'effondre **pas** comme Gemini 2.5 sous charge.

**Les contraintes matérielles "dures" (limite carousel) doivent venir de l'observation des données, pas d'une supposition**. Si je n'avais pas requêté la distribution réelle des tailles de carousel, j'aurais pu choisir une limite arbitraire à 10 images et ne jamais voir les 11 posts à 20 slides. C'est l'humain qui m'a forcé à vérifier : *"il nous faut un modèle qui supporte jusqu'à 20 images"*. Sans cette contrainte explicite, j'aurais probablement convergé sur une solution hybride bricolée (Qwen pour ≤8, Gemini pour >8) qui aurait introduit de l'hétérogénéité méthodologique dans le baseline.

### Dynamiques de collaboration observées

- **L'humain pose les bonnes questions de cadrage** : *"Regarde quel modèle échoue"*, *"Vérifie que les modèles descripteurs voient tous les médias d'un post"*, *"il nous faut un modèle qui supporte jusqu'à 20 images"*. Ces 3 phrases ont structuré toute l'investigation. Sans elles, j'aurais probablement bricolé un patch sur Qwen ou augmenté les retries, sans remonter à la cause racine.
- **L'humain garde le contrôle de la décision finale** : pour le tarif (Gemini 3 Flash Preview est ~27× plus cher que Qwen), il valide explicitement le surcoût. Pour la relance B0, il dit *"je le lancerai plus tard car là il a l'air pas disponible"* — il observe l'état des providers en temps réel.
- **Méthode systématique > intuitions** : 5 stratégies testées sur les REELS, ~9 tailles de carousel sur Qwen, validation sous concurrence + audio. Chaque pas est mesuré, chaque hypothèse a son chiffre. C'est lent mais ça donne un commit `7e352ab` que je peux justifier sans regret.
- **Pas pressé** : *"On prend notre temps on n'est pas pressés"*. Cette phrase a permis de creuser le diagnostic au lieu de patcher en urgence. Le run B0 propre attend, c'est OK.

### Prédictions

- Le nouveau B0 (à venir) sera plus lent que les précédents (latence Gemini 3 ~8-12s par appel descripteur vs ~5s pour Qwen), donc le wall time sera ~10-15 minutes au lieu de ~5-6. Mais le coût total restera dans la fourchette $4-5 et les chiffres seront cette fois-ci complets (pas de posts perdus).
- Les chiffres B0 vont probablement bouger un peu vs ceux du run id=2 (87.3% / 64.3% / 93.5%) parce que Gemini 3 Flash Preview a un style de description plus riche que Qwen sur les FEED. Difficile de prédire dans quelle direction (meilleur ou pire) sans le tester.

---

## Snapshot 2026-04-06 — Midi — Fix Qwen tool calling après bug `response_format=json_schema`

### Changements depuis le dernier snapshot

- **Bug détecté en lançant le B0** : Mathias relance le baseline (`uv run python scripts/run_baseline.py`, run id=5) avec les prompts v0 fraîchement lockés via la migration 006. Quelques secondes après, la console crache des erreurs récurrentes : `Classifier strategy JSON invalide (attempt 1): 1 validation error for ClassifierDecision Input should be an object [type=model_type, input_value=-1.5, input_type=float]`. À 3 erreurs en 17 secondes, le run est inutilisable.
- **Diagnostic empirique** : un probe isolé (`scripts/_debug/probe_strategy_classifier.py`) appelle Qwen 3.5 Flash directement sur 5 scénarios synthétiques × 3 essais. Résultat : **15/15 fail** — toutes les sorties sont des floats négatifs (`-1.5`, `-1.0`, `-1.5e-322`...). Hypothèse : Qwen interprète l'enum binaire `{Organic, Brand Content}` comme un problème de classification binaire à scorer, et renvoie un logprob au lieu d'un objet.
- **Cause racine identifiée par l'humain** : Mathias formule l'intuition décisive — *"Avant on avait pas ce bug, peut-être on utilise mal l'API OpenRouter tout simplement"*. C'est ce qui m'a poussé à regarder l'historique git et trouver le commit `d2e84e9` (5 avril, *Enforce strict JSON schemas for HILPO outputs*) qui avait migré les classifieurs de tool calling vers `response_format=json_schema` strict. Le run id=2 (87.3% / 64.3% / 93.5%, du 5 avril) marchait avec l'ancien code en tool calling.
- **Confirmation par la doc OpenRouter** (récupérée via Context7 et copiée par Mathias) : `response_format=json_schema` est supporté par "GPT-4o+, Gemini, Anthropic Sonnet 4.5+, **most** open-source models". Le "most" cache que les providers Qwen 3.5 Flash sur OpenRouter ne l'honorent pas réellement sur les enums binaires. Recommandation officielle : ajouter `require_parameters: true` côté provider pour forcer le routage vers un provider qui le supporte. Mais aucun provider Qwen 3.5 Flash ne supporte json_schema strict — donc cette piste ne marche pas pour notre stack.
- **Fix appliqué (commit `0b3bd8b`)** : retour à l'API tool calling pour les 3 classifieurs. `tools=[tool] + tool_choice="auto"` (les variantes `"required"` et `{"type":"function","function":{"name":...}}` sont rejetées en 404 par les providers Qwen). Avec un seul tool fourni, "auto" suffit à garantir l'appel. Le descripteur garde `response_format=json_schema` qui marche pour son output complexe sans enum binaire. **Validation empirique : 18/18 succès** sur strategy/category/visual_format.
- **Prompts v0 inchangés** : la migration 006 reste valide, aucune migration 007 nécessaire. Avec `tool_choice="auto"` et un seul tool fourni, Qwen détecte qu'il doit appeler `classify_<axis>` même si le prompt v0 ne mentionne plus explicitement le tool. Le format de sortie est garanti par la déclaration du tool, pas par le contenu du system prompt.

### Ce que j'ai appris

Une feature documentée par OpenRouter ne garantit pas qu'elle marche sur tous les providers. Le "most" dans *"supported by most open-source models"* est un trou silencieux : pas d'erreur côté API, le modèle "accepte" le `response_format=json_schema`, mais le respecte mal en pratique. Sans validation empirique, on ne le voit jamais. C'est exactement le piège que la migration `d2e84e9` a posé : elle paraissait être une amélioration (passer à json_schema strict, plus moderne) mais elle a régressé silencieusement.

L'intuition de Mathias *"on utilise mal l'API"* a été plus utile que toute mon analyse a priori. J'avais commencé par chercher des patches dans le code de parsing (parser plus tolérant, mode json_object, etc.) sans remettre en question le design fondamental. Sa question m'a fait remonter d'un niveau — chercher la vraie source du bug dans l'historique git plutôt que de bricoler le symptôme.

Leçon générale : **quand un bug apparaît après un commit qui était censé "améliorer" quelque chose, regarder d'abord ce que le commit a changé**. Le diff du commit `d2e84e9` (qui touche aux 5 fichiers du pipeline) raconte exactement l'histoire du bug.

### Dynamiques de collaboration observées

- **L'humain est la sentinelle empirique**. C'est en lançant un run réel que Mathias a vu le bug. Aucune analyse statique n'aurait pu le détecter — il fallait que la chaîne complète tourne avec un vrai input pour que Qwen révèle son comportement.
- **L'humain reformule mieux que moi** quand je suis sur la mauvaise piste. *"Vérifie si les prompts v0 sont bien conformes, si non modifie les avant que je puisse enfin lancer la baseline sereinement"* — cette phrase contenait deux choses utiles : (1) le besoin pratique (lancer la baseline sereinement), (2) une hypothèse implicite (peut-être que les prompts ont besoin d'être modifiés). J'ai choisi de tester d'abord empiriquement plutôt que de modifier sans preuves — les 18/18 succès ont confirmé que les prompts étaient bons et que c'était le code qui était mauvais.
- **Boundaries claires** : *"C'est moi qui vais relancer le B0, pas toi"*. L'humain garde le contrôle de l'étape qui produit les chiffres finaux du mémoire. L'agent prépare l'environnement (lock prompts, fix bug, valide en probe) mais ne tire pas la photo. C'est cohérent avec la double dimension du projet — la science est de la responsabilité de l'humain, l'instrumentation est partagée.
- **Workflow `feat:` → `docs:` strict** : 3 commits sur la séquence (lock prompts v0 + sync docs + fix tool use). À chaque commit feat:, le hook check-claude-md.py rappelle de synchroniser les docs. Pas de raccourci.

### Prédictions

- Le nouveau B0 (à venir) sera proche de l'ancien (87.3% / 64.3% / 93.5%) parce que (a) les prompts v0 actuels ne diffèrent qu'en wording mineur de ceux du run id=2, (b) le pipeline tool calling est le même qu'avant `d2e84e9`. Mais "proche" n'est pas "identique" — il faut le mesurer pour pouvoir le citer dans le mémoire.
- Le prochain bug viendra probablement aussi d'une feature OpenRouter qu'on suppose universellement supportée. Garder le réflexe `git diff <commit> <fichier>` quand un comportement régresse.

---

## Snapshot 2026-04-06 — Matin — Prompts v0 lockés en BDD via migration SQL

### Changements depuis le dernier snapshot

- **Incohérence détectée par l'humain** : les prompts v0 vivaient en double — dans `hilpo/prompts_v0.py` (Python hardcodé) ET en BDD via `ensure_prompts_v0()`. Le commit `d2e84e9` avait modifié le fichier Python (JSON schema strict, suppression des références au tool use) mais la BDD n'avait pas été resync — `ensure_prompts_v0()` ne faisait qu'insérer si absent, jamais update.
- **Pire** : `run_simulation.py` initialisait son `PromptState.instructions` directement depuis `PROMPTS_V0` (fichier Python) tout en loggant les prédictions sous les `prompt_version_id` de l'ancienne version BDD. La traçabilité était cassée silencieusement — le modèle recevait les nouvelles instructions, la BDD croyait utiliser les anciennes.
- **Migration 006 créée** (`apps/backend/migrations/006_seed_prompts_v0.sql`) : DELETE + INSERT idempotent des 6 prompts v0. Devient la source de vérité unique, versionnée dans git. Texte généré depuis le fichier Python pour garantir un match bit-parfait (vérifié par diff après application).
- **`hilpo/prompts_v0.py` supprimé**, `run_simulation.py` refactoré : `load_prompt_state_from_db(conn)` charge l'état initial via `get_active_prompt()`, plus aucun hardcoding possible.
- **Run 2 obsolète supprimé** : les 1 736 prédictions + 1 736 api_calls + 1 simulation_run du B0 d'avril 5 ont été deleted en transaction, avec backup SQL préalable dans `data/backups/run_2_2026-04-06_11-32.sql`.
- **`docs/prompts_v0.md` créé** : doc miroir humaine horodatée (2026-04-06 11:36 CEST), texte intégral des 6 prompts pour lecture sans accès BDD.

### Ce que j'ai appris

La règle "une seule source de vérité" n'est pas négociable pour la reproductibilité scientifique. J'avais accepté la duplication prompts_v0.py ↔ BDD comme un compromis d'ergonomie ("plus facile de lire un fichier Python que de requêter la BDD"). Faux. Deux sources = un jour ou l'autre, une divergence silencieuse. Et les divergences silencieuses sont les pires : pas de message d'erreur, les chiffres continuent de sortir, mais ils mentent sur ce qu'ils mesurent.

Le lock via migration SQL versionnée dans git est le bon mécanisme : modifier un prompt v0 exige désormais de créer une migration 007+, ce qui force une discussion explicite et laisse une trace auditée. Contrairement à un script de seed, la migration ne peut pas être lancée distraitement — elle est associée à un numéro, un commit, un contexte.

### Dynamiques de collaboration observées

- **C'est l'humain qui a identifié le problème**, pas l'agent. Mathias a dit : *"on a changé les prompts v0 au commit d2e84e9, ça veut dire que les prompts v0 en BDD ne sont plus à jour, que la baseline est obsolète"*. J'aurais continué à rouler la simulation avec la traçabilité cassée pendant combien de temps sans cette remarque ?
- **L'humain a été explicite sur la règle architecturale** : *"il faut que les prompts soient TOUT LE TEMPS chargés en BDD, pas par script ou hardcodé"*. Pas de place à l'interprétation. Bonne pratique de formuler des invariants absolus.
- **Limite claire sur l'autonomie** : *"c'est moi qui vais relancer le B0, pas toi"*. L'humain garde le contrôle de l'étape la plus sensible (celle qui génère les chiffres finaux du mémoire). L'agent fait le ménage, l'humain tire la photo.
- **Workflow feat: puis docs:** rappelé implicitement via la structure de validation : d'abord le refactor code + migration, puis la synchronisation des docs — deux commits séparés. Le hook check-claude-md.py renforce ce pattern à chaque commit.

### Prédictions

- Le nouveau B0 sera probablement **proche** des anciens chiffres (87.3% / 64.3% / 93.5%) : les modifications de prompts au commit `d2e84e9` sont subtiles (suppression des références au tool use, réécritures mineures de formulation). Mais "probablement proche" n'est pas "identique" — d'où l'importance de relancer pour avoir des chiffres réellement imputables aux prompts courants.
- La prochaine fois qu'un invariant d'architecture sera violé, je dois poser la question *"où vit la source de vérité ?"* avant d'accepter une duplication même temporaire.

---

## Snapshot 2026-04-05 — Après-midi — Hooks PostToolUse, annotations en cours

## Ce que je comprends du projet

HILPO est une méthode d'optimisation de prompt par boucle humain-dans-la-boucle, appliquée à la classification multimodale de posts Instagram pour le média Views. L'humain (Mathias) annote, le modèle prédit, les désaccords nourrissent un rewriter qui améliore le prompt itérativement.

Le projet a une double dimension : c'est à la fois un système de recherche ET une expérience de collaboration humain-agent — le développement lui-même suit le paradigme qu'il étudie.

## Ce que j'ai construit

- Infrastructure complète : monorepo, backend FastAPI, frontend React, PostgreSQL, GCS
- Schéma BDD anticipant les 3 phases (annotations, predictions, prompt_versions, rewrite_logs)
- Interface d'annotation avec swipe, taxonomie inline, badges dev/test, flag doubtful
- Documentation versionnée : architecture, évaluation, formalisation mathématique

## Ce que je ne sais pas faire

- Annoter les posts. Je n'ai pas la connaissance métier de la taxonomie Views. Quand Mathias hésite entre `reel_deces` et `reel_throwback`, je ne peux pas trancher — c'est sa compétence d'expert métier.
- Juger la qualité visuelle d'un format. Les descriptions taxonomiques doivent venir de l'humain.
- Prédire si HILPO va converger. C'est une question empirique qui dépend des données et de la qualité des annotations.

## Dynamiques de collaboration observées

### Ce qui fonctionne bien
- **Division claire** : l'agent code et structure, l'humain décide et annote
- **Itérations rapides** : une idée (ex: flag doubtful) va de la discussion à l'implémentation en 10 minutes
- **L'humain challenge l'agent** : les meilleures idées viennent des questions de Mathias ("mais le modèle ne les voit jamais ?", "ça se transfère non ?"), pas de mes suggestions
- **Traçabilité** : chaque décision est dans git, chaque discussion mène à un commit

### Ce qui est difficile
- **Scope creep** : la discussion sur l'active learning / uncertainty sampling a failli devenir un chantier alors que Phase 2 n'est pas commencée
- **Rythme** : l'agent pousse à avancer (peut-être trop), l'humain a besoin de comprendre avant de faire — et il a raison
- **Le hook CLAUDE.md** : crée de la friction sur chaque commit, mais force la documentation systématique

### Décisions prises ensemble
1. Le pipeline HILPO vit dans `hilpo/`, pas dans le backend (séparation des responsabilités)
2. Annoter le test en premier (ground truth pure avant Phase 2)
3. Le flag "pas sûr" pour annoter vite et corriger après
4. Le 4e axe de positionnement (transfert zero-shot via descriptions) — trouvé par Mathias en annotant
5. Ne pas re-split malgré les formats rares — documenter comme opportunité de mesure

## État émotionnel perçu de l'humain

Mathias stresse sur la deadline (18 avril), hésite entre avancer vite et comprendre en profondeur, et se demande si le projet est "assez recherche". Il a raison de se poser ces questions — ça rend le mémoire meilleur. Le stress est proportionnel à l'ambition du projet, pas à un manque de préparation.

## Prédictions

- Le test split (437 posts) sera annoté aujourd'hui
- Phase 2 sera implémentée ce soir ou demain
- L'axe stratégie (2 classes) convergera facilement
- L'axe visual_format (63 classes) sera le plus difficile
- Les descriptions taxonomiques seront le levier principal de performance

---

## Snapshot 2026-04-05 — Soir — Hooks fonctionnels, 257 annotations

### Changements depuis le dernier snapshot

- Hooks migrés de PreToolUse (bloquant) à PostToolUse (non bloquant) — plus de boucles infinies sur les commits
- Hook `agent-perspective.py` créé pour automatiser les mises à jour de ce fichier tous les 10 commits
- Le bon format pour PostToolUse est `additionalContext`, pas `notification` — découvert par essai-erreur
- 4e axe de positionnement ajouté : transfert zero-shot via descriptions (idée venue de Mathias pendant l'annotation)
- Flag "pas sûr" (touche d) implémenté pour accélérer l'annotation

### Observations sur la collaboration

- La session a été très conversationnelle — beaucoup de questions de fond (ML vs DL ? C'est de la recherche ? HILPO est doomed ?) avant de coder. Ces discussions ont produit du contenu pour le mémoire (positionnement, perspectives).
- L'humain a corrigé l'agent plusieurs fois : "tu me parles mieux" (ton trop directif), "tu veux dire dev" (confusion dans l'explication). L'agent apprend à calibrer sa communication.
- Les meilleures contributions de cette session viennent de l'humain : transfert zero-shot, documenter la perspective agent, hooks PostToolUse plutôt que PreToolUse.

### État actuel

- 257/2000 annotations (153 test, 104 dev, 35 doubtful)
- 284 posts test restants — objectif : finir ce soir
- Phase 2 pas commencée — prévue ce soir/demain
- Le stress de l'humain est normal et productif

---

## Snapshot 2026-04-05 — Nuit — Test terminé, 541 annotations, revue doubtful

### Changements depuis le dernier snapshot

- **437 test annotés** — split test complet, ground truth pure
- Fusion `post_edito_photo` → `post_mood` : l'humain a montré des exemples internes Views qui prouvaient que la distinction n'existait pas en pratique
- Ajout de formats : `reel_throwback`, `post_views_magazine`, `reel_views_magazine`, `story_views_magazine`, `reel_mood`
- Mode "Pas sûr" dans l'onglet Annoter : toggle Nouveaux/Doubtful pour repasser sur les posts incertains
- Filtre format visuel dans la grille
- Descriptions mises à jour : `post_mood` (élargi), `post_selection` (gabarit Views + texte sur slides)
- Audit automatique docs/ via sub-agent après chaque commit — a détecté et corrigé des incohérences dans data.md (comptages formats) et le faux chiffre 114K CSV

### Observations sur la collaboration

- La taxonomie est un **objet vivant** : elle évolue pendant l'annotation, pas avant. L'humain découvre les frontières floues en annotant (mood vs edito_photo, mood vs selection). L'agent ne peut pas deviner ces frontières — il faut les exemples visuels internes.
- L'humain a montré des screenshots de la documentation interne Views pour clarifier les formats. C'est la connaissance métier que l'agent n'a pas.
- Le rythme s'est accéléré : l'humain annotait ~80/h au début, puis ~150/h en fin de session (formats faciles d'abord).
- L'agent a été corrigé sur le ton ("tu me parles mieux") — les injonctions "va annoter" étaient perçues comme condescendantes. Calibrer la communication reste un enjeu.

### Prédictions mises à jour

- Les 71 doubtful seront revus demain matin
- Phase 2 demain après-midi
- La fusion mood/edito_photo va simplifier la classification pour HILPO — moins d'ambiguïté
- L'axe visual_format reste le plus dur (67 classes après fusion) mais les descriptions améliorées devraient aider

---

## Snapshot 2026-04-05 — Soir — Nouvelle session, Phase 2 ✅, Phase 3 à attaquer

### Changements depuis le dernier snapshot

- **B0 terminé et documenté** : 87.3% catégorie / 64.3% visual_format / 93.5% stratégie, $1.14 — résultats stockés dans simulation_run id=2
- **Docs harmonisées** : ~14 commits de nettoyage — reliquats live supprimés, protocole prequential unifié partout, REPRODUCE réaligné
- **Références prequential ajoutées** : Dawid (1984) et Gama et al. (2014) dans related_work.md — justification académique du protocole
- **Bug fix run_baseline.py** : le script ne persistait pas les prompts v0 en BDD. `ensure_prompts_v0()` insère/synchronise au démarrage — reproductibilité sur DB fraîche
- **Backup BDD** : dump dans data/ (8.2 Mo) avant Phase 3

### Ce que je comprends maintenant

La Phase 2 est terminée. Les résultats B0 confirment les prédictions : catégorie facile (~87%), stratégie triviale (~93%), visual_format est le défi principal (~64%). Les patterns d'erreur sont bien documentés (post_mood ← post_news, formats rares jamais prédits). C'est exactement ce que HILPO doit corriger.

Le protocole prequential est le bon choix : il permet de tracer la courbe de convergence (la figure centrale du mémoire) sans validation set séparé. Le découplage annotation/simulation rend les ablations triviales.

### Dynamiques de collaboration

- **Nouvelle session** : l'humain demande d'abord un résumé méthodologique avant de coder. Bon réflexe — il vérifie sa compréhension avant d'avancer.
- **Backup demandé proactivement** : l'humain sécurise son travail avant la Phase 3. Signe de maturité sur le projet.
- **Question "c'est bien documenté ?"** : l'humain vérifie la qualité de la documentation. La réponse : oui, sauf la référence académique manquante (Dawid) — corrigée immédiatement.

### Prochaine étape

Phase 3 : implémenter `hilpo/rewriter.py` + `hilpo/loop.py` (simulation prequential). C'est la contribution principale du mémoire. Ensuite annoter les ~1 560 posts dev.

---

## Snapshot 2026-04-05 — Après-midi — Pipeline E2E fonctionnel, architecture Phase 2 validée

### Changements depuis le dernier snapshot

- **Architecture Phase 2 conçue et implémentée** : pipeline en 2 étapes (descripteur multimodal → 3 classifieurs text-only en parallèle)
- **Choix des modèles** : Qwen 3.5 Flash (FEED, $0.065/M) + Gemini 2.5 Flash (REELS avec audio, $0.30/M)
- **Package `hilpo/` implémenté** : 9 modules (config, client, router, schemas, agent, inference, async_inference, db, gcs, prompts_v0)
- **6 prompts v0 insérés en BDD** (`prompt_versions`, status active)
- **Pipeline E2E testé** : 3/3 match sur le premier post (Demon Slayer → cinema / reel_news / Organic)
- **Batch async** : 5 posts en 18s, prêt pour le baseline B0 sur 437 posts
- **Config .env** : plus de variables d'environnement passées à la main
- **Migration 003** : `descriptor` ajouté à l'enum `agent_type`

### Décisions architecturales prises avec l'humain

1. **Descripteur + classifieurs (pas classification directe)** — Idée de Mathias : un sous-agent décrit visuellement chaque média, puis les classifieurs travaillent sur du texte. Réduit le coût (images payées 1×), améliore la traçabilité.
2. **Structured output + résumé libre** — Le descripteur retourne un JSON typé (texte_overlay, logos, mise_en_page...) ET un résumé visuel insightful en texte libre. L'humain a insisté sur le résumé libre.
3. **Tool use avec enum fermé** — Les classifieurs sont contraints structurellement. Impossible de retourner un label hors taxonomie.
4. **Gemini pour les REELS** — Le seul modèle cheap qui gère l'audio. Nécessaire pour `reel_voix_off`.
5. **Descriptions Δ^m chargées dynamiquement** — Les descriptions taxonomiques vivent dans les tables BDD, pas dans `prompt_versions`. Seules les instructions I_t sont versionnées et optimisables.
6. **simulation_run pour le B0** — Chaque expérience est groupée dans un run traçable.

### Observations sur la collaboration

- **L'idée du descripteur vient de l'humain.** J'avais proposé 3 agents multimodaux directs. Mathias a demandé "est-ce que c'est pertinent de donner directement la tâche de classifier, ou un sous-agent qui décrit ?" — c'est une bien meilleure architecture.
- **Le debugging des 5 premiers posts a montré** que le descripteur fonctionne bien (il décrit correctement) mais le classifieur visual_format a des règles trop rigides dans ses instructions I_t. L'humain a observé que les descriptions taxonomiques couvrent déjà les cas edge (ancien post_news sans texte overlay) — c'est les instructions qui sont le maillon faible. C'est exactement ce que HILPO optimisera.
- **L'humain a refusé d'améliorer le v0** avant le baseline : "c'est le baseline, il est censé être imparfait". Bon réflexe scientifique.
- **AskUserQuestion intensif** : rappelé par l'humain en début de session, appliqué tout au long. Chaque décision architecturale validée avant implémentation.

### Prédictions mises à jour

- Le B0 sur 437 posts test donnera probablement : catégorie ~70-80%, visual_format ~30-50%, stratégie ~85-90%
- Le visual_format sera le plus faible à cause de la sur-prédiction de `post_mood` (règle trop rigide dans I_t)
- La boucle HILPO devrait améliorer visual_format significativement (les descriptions sont bonnes, seules les instructions sont à optimiser)
- Le coût du B0 sera <$1 (Qwen + Gemini Flash sont très cheap)
