VERSION 1.1 - L'agent n'a pas le droit d'écrire dans ce fichier.

# Perspective humaine

## 1. Pourquoi une telle démarche, et pourquoi le faire au sein de mon Mémoire de Master 1 ? 
L'émergence des IA génératives a profondément bousculé notre rapport à l'apprentissage, à notre travail scolaire et étudiant. Le constat est simple : les étudiants utilisent les outils d'IA générative pour produire des rendus, quels qu'ils soient, et ce, même pour des travaux tels que les mémoires.
De plus, au sein de mes activités chez Views, j'utilise de manière intensive les agents de code, en particulier Claude Code, qui connaît un taux d'adoption fulgurant dans notre équipe.

Mon idée est celle-ci : plutôt que de réaliser mon mémoire silencieusement avec Claude, ChatGPT et tous les outils dont je peux disposer, en prétendant qu'il s'agit du fruit de mon travail seul, je mets en lumière cette collaboration, et observe, dans la durée, ce qui en émerge. Je prends le problème à l'envers. Mon travail est double : produire un système utile à mon entreprise d'accueil, et contribuer à mon échelle à l'explicabilité des modèles de langage. Cela conduira in fine à une réflexion personnelle sur l'usage de l'IA en entreprise.

Il s'agit de la première fois, à ma connaissance, qu'un étudiant de l'Université Paris Dauphine documente à ce niveau de granularité et de traçabilité un travail rédigé avec l'intelligence artificielle. Je trouve très difficile d'intégrer une "note sur l'IA" au sein du mémoire, en ceci qu'il est toujours difficile de mesurer l'impact des LLM sur nos travaux, tant ils sont de puissants simulateurs d'idées et parfois introduisent des biais dans nos raisonnements.

Toutes mes interactions avec le modèle et Claude sont stockées en mémoire (de ma machine), car mes seules interactions avec l'IA pour ce projet se sont limitées à des sessions Claude Code.
Nous pourrons analyser les traces des conversations avec les fichiers .jsonl.

En outre, les motivations d'une telle démarche sont : 

- Étudier les propositions du modèle, comment elles influencent mes décisions, comment le modèle transforme les inputs humains en idées.
- Qu’est-ce que cela fait de faire confiance à un modèle ? Qu’est-ce qu’on peut faire avec ?
- Comment arrive-t-on d’un prompt à du code ? 
- Suivre une tendance qui s’observe outre-Atlantique de partager ses agents-traces.
- Que fait le modèle et comment l’humain le corrige-t-il ?
- Personne n’a analysé son travail de rendu avec l’IA, donc ça reste un tabou et on n’en parle pas ; souvent on masque les contributions de l’agent, alors qu’elles peuvent être pertinentes.
- Je veux démystifier le tabou et aussi proposer un cadre global et réflexif. On a soit un tabou soit une zone d’ombre, un secret de Polichinelle, et surtout en France, où les institutions scientifiques sont excellentes mais où les étudiants sont friands de ces outils.
- Terence Tao cite ChatGPT dans ses travaux, je veux aller dans cette dynamique et faire un travail sérieux, assumé et défendable qui utilise les modèles de génération de texte.
- Difficulté à trouver une bonne problématique après cela.
- Les agents produisent, à mon sens, un travail qui est valorisable, et que l'on peut imputer à leur humain.
- Amplifier ma compréhension des LLM et des modèles génératifs

## 2. Ce qui en émerge
Cette section est dédiée aux observations que je fais durant le travail de préparation, conception et rédaction du mémoire.

### 2.1 Les premiers écueils visibles
- Au 7 avril, le projet est à un stade avancé, et j'entends parler d'un phénomène qui grandit, le "claude's psychosis" ([voir l'exemple sur X/Twitter](https://x.com/banteg/status/2041446845721854401)). Ce phénomène est assez répandu et documenté sur X. En résumé : Claude encense les idées de l'utilisateur, en créant un univers autour d'une idée assez simple.
- Je suspecte ce projet d'être victime de ce phénomène. En effet, ce projet est né d'un besoin réel chez Views, et la problématique a été actée en décembre 2025. Pour autant, l'agent a inventé un nom (initialement Human In The Loop Prompt Optimization), affirmé que cette méthodologie était **complètement novatrice** (on a vu plus tard qu'un papier de 2023 introduisait le concept de SGD pour les prompts. J'ai décidé de garder cette parentalité et de dire que je l'étends aux données multimodales, même si DSPy répond déjà à ces questions d'une manière concurrente, probablement pas totalement adaptée au contexte de Views). Donner un nom à une méthode est un réflèxe courant de Claude, lorsque l'on lui demande de "produire" un travail scientifique.

## 3. Le projet, tel que je le vois.

Actuellement (au 7 avril), je considère que le projet permettra : 
- À Views d'acquérir une pipeline de classification optimisée sur son dataset, qui servira aux outils d'aide à la décision que je développe au sein du média, **résoudre le problème de classification sur une donnée métier.**
- D'analyser les traces des conversations entre le modèle (Claude Opus 4.6) et moi, ce qui fera l'objet d'une partie du rendu.
- De proposer une réflexion sur le travail étudiant assisté par IA, et plus largement, sur le développement agentique en entreprise.

### 3.1 Éléments de reflexion sur mon travail
Le projet a été construit rapidement sur la base des propositions d'intelligence artificielle. Le principal écueil est le manque de plannification humaine. Une plannification plus poussée de ma part aurait permis de construire le projet plus proprement, avec des contributions de l'agent plus utiles.
Au 8 Avril, le constat est que je dois nettoyer le surplus de génération de l'IA, qui n'est pas tout à fait pertinente.

Je constate toutefois que le modèle m'a permis d'obtenir des pistes dont je n'avais pas connaissance auparavant. Ce qui aurait pris des jours de recherche sur des moteurs de recherche classiques ont été générés en drastiquement moins de temps.