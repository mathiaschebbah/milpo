VERSION 1.0 - L'agent n'a pas le droit d'écrire dans ce fichier.

# Perspective humaine

## 1. Pourquoi une telle démarche, et pourquoi le faire au sein de mon Mémoire de Master 1 ? 
L'émergence des IA génératives a profondément bousculé notre rapport à l'apprentissage, notre travail scolaire et étudiant. Le constat est simple, clair et sans appel, tout le monde utilise les outils d'IA génératives pour produire des rendus, quelqu'ils soient, et-ce même pour les travaux tels que les mémoires.

Mon idée est celle-ci : plutôt que de réaliser mon mémoire silencieusement avec Claude, ChatGPT, et tous les outils dont je peux disposer, en prétendant qu'il s'agit du fruit de mon travail seul, je mets en lumière cette collaboration, et observe, dans la durée, ce qui en émerge. Je prends le problème à l'envers. Mon travail est double : produire un système utile à mon entreprise d'accueil, et contribuer à mon échelle sur l'explicabilité des modèles de language.

Il s'agit de la première fois, à ma connaissance, qu'un étudiant de l'Université Paris Dauphine documente à ce niveau de granularité, et de traçabilité un travail rédigé avec l'intelligence artificielle. Je trouve très difficile d'intégrer une "note sur l'IA" au sein du mémoire, en ceci qu'il est toujours difficile de récupérer de mesurer l'impact de les LLMs sur nos travaux, tant ils sont un puissants simulateurs d'idées, et parfois introduisent des biais dans nos raisonnements.

Toutes mes intéractions avec le modèle, et Claude sont stockées en mémoire (de ma machine), car mes seules intéractions avec l'IA pour se projet se sont limitées à des sessions Claude Code.
Nous pourrons analyser les traces des conversations, avec les fichiers .jsonl.

## 2. Ce qui en émerge
Cette section est dédiée aux observations que je fais durant le travail de préparation, conception, et rédaction du mémoire.

### 2.1 Les premiers écueils visibles
- Au 7 avril, le projet est à un stade avancé, et j'entends parler d'un phénomène qui grandit, le "claude's psychosis" ([voir l'exemple sur X/Twitter](https://x.com/banteg/status/2041446845721854401)). Ce phénomène est assez répandu et documenté sur X. En résumé : Claude encense les idées de l'utilisateur, en créant un univers autour d'une idée assez simple.
- Je suspecte ce projet d'être victime de ce phénomène. En effet, ce projet est né d'un besoin réel chez Views, et la problématique a été actée en décembre 2025. Pour autant, l'agent a : inventé un nom (initialement Human In The Loop Prompt Optimization), affirmé que cette méthodologie était **complétement novatrice** (on a vu plus tard qu'un papier de 2023 introduit le concept de SGD pour les prompts, j'ai décidé de garder cette parentalité et de dire que je l'étend aux données multimodales, même si DSPy répondent déjà à ces questions d'une manière concurrente, (probablement pas totalement adaptée au contexte de Views)).

### 3. Le projet, tel que je le vois.

Actuellement, (au 7 Avril) je considère que le projet permettera : 
- À Views d'acquérir une pipeline de classification optimisée sur son Dataset, qui servira aux outils d'aide à la décision que je développe au sein du média
- D'analyser les traces des conversations entre le modèle (Claude Opus 4.6) et moi, ce qui fera l'objet d'une partie du rendu
- De proposer une réflexion sur le travail étudiant assisté par IA