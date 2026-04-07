"""Signatures et modules DSPy pour la classification multimodale Views.

Architecture parallèle à `milpo/inference.py` :
- Pas de descripteur ici (gelé, on charge les features cachées en BDD)
- 3 classifieurs : category, visual_format, strategy
- Chaque classifieur a 2 flavors :
    * constrained : descriptions = dspy.InputField fixe (MIPROv2 ne touche pas)
    * free        : descriptions injectées dans le docstring de la signature
                    (MIPROv2 peut tout réécrire)

Pour visual_format, il faut gérer le scope (FEED → 44 formats, REELS → 16
formats). On instancie 2 programmes distincts qui sont optimisés séparément.

Le choix d'avoir un fichier Python séparé (et pas une factory pure) est
motivé par MIPROv2 : l'optimizer manipule la `signature.instructions` au
runtime, donc les classes doivent être déclarables / inspectables et ne pas
dépendre de closures qui muteraient à chaque appel.

NB : DSPy ne contraint pas l'output à un enum fermé comme le tool calling
MILPO. Le LM peut générer un label hors-enum, qui est alors comptabilisé
comme une erreur (cf. metrics.py). Pour récupérer ces erreurs, on garde
trace des labels invalides via `validate_label`.
"""

from __future__ import annotations

from typing import Type

import dspy

# ─────────────────────────────────────────────────────────────────
# MODE CONSTRAINED : descriptions = InputField fixe (jamais optimisé)
# ─────────────────────────────────────────────────────────────────


class CategoryClassifierConstrained(dspy.Signature):
    """Classifie la catégorie éditoriale d'un post Instagram du média Views.

    À partir des features visuelles extraites par un descripteur multimodal
    et de la caption du post, déterminer la catégorie éditoriale parmi celles
    décrites dans le bloc `descriptions`.
    """

    features: str = dspy.InputField(
        desc="Features visuelles du post au format JSON (sortie du descripteur multimodal)"
    )
    caption: str = dspy.InputField(
        desc="Caption Instagram du post (peut être vide)"
    )
    descriptions: str = dspy.InputField(
        desc="Descriptions des 15 catégories éditoriales valides (taxonomie fixe)"
    )
    category: str = dspy.OutputField(
        desc="Nom exact de la catégorie choisie, doit correspondre à l'une des descriptions"
    )


class VisualFormatClassifierConstrained(dspy.Signature):
    """Classifie le format visuel d'un post Instagram du média Views.

    À partir des features visuelles extraites par un descripteur multimodal
    et de la caption du post, déterminer le format visuel parmi ceux décrits
    dans le bloc `descriptions`. Les formats sont scopés par type de post
    (FEED → post_*, REELS → reel_*).
    """

    features: str = dspy.InputField(
        desc="Features visuelles du post au format JSON (sortie du descripteur multimodal)"
    )
    caption: str = dspy.InputField(
        desc="Caption Instagram du post (peut être vide)"
    )
    descriptions: str = dspy.InputField(
        desc="Descriptions des formats visuels valides pour ce scope (taxonomie fixe)"
    )
    visual_format: str = dspy.OutputField(
        desc="Nom exact du format visuel choisi, doit correspondre à l'une des descriptions"
    )


class StrategyClassifierConstrained(dspy.Signature):
    """Classifie la stratégie d'un post Instagram du média Views.

    À partir des features visuelles extraites par un descripteur multimodal
    et de la caption du post, déterminer si le post est de type Organic
    (contenu éditorial Views) ou Brand Content (sponsorisé / partenariat).
    """

    features: str = dspy.InputField(
        desc="Features visuelles du post au format JSON (sortie du descripteur multimodal)"
    )
    caption: str = dspy.InputField(
        desc="Caption Instagram du post (peut être vide)"
    )
    descriptions: str = dspy.InputField(
        desc="Descriptions des 2 stratégies valides : Organic et Brand Content"
    )
    strategy: str = dspy.OutputField(
        desc="Nom exact de la stratégie : Organic ou Brand Content"
    )


CONSTRAINED_SIGNATURES: dict[str, Type[dspy.Signature]] = {
    "category": CategoryClassifierConstrained,
    "visual_format": VisualFormatClassifierConstrained,
    "strategy": StrategyClassifierConstrained,
}


# ─────────────────────────────────────────────────────────────────
# MODE FREE : descriptions injectées dans le docstring (MIPROv2 peut réécrire)
# ─────────────────────────────────────────────────────────────────
#
# DSPy ne permet pas d'altérer dynamiquement le docstring d'une classe
# définie statiquement. On utilise donc une factory qui crée une classe
# Signature à la volée à partir des descriptions chargées en BDD.


def make_free_signature(
    axis: str,
    scope: str | None,
    descriptions: str,
) -> Type[dspy.Signature]:
    """Construit dynamiquement une dspy.Signature 'free mode' pour un axe donné.

    Le docstring de la signature contient l'intégralité des descriptions
    taxonomiques, qui devient une partie de l'instruction initiale envoyée
    au LM. MIPROv2 peut réécrire ce docstring lors de l'optimisation, donc
    les descriptions ne sont PAS protégées dans ce mode.

    Args:
        axis: 'category', 'visual_format' ou 'strategy'
        scope: 'FEED' / 'REELS' / None (utilisé pour le naming uniquement)
        descriptions: bloc de descriptions formatté (un item par ligne)

    Returns:
        Une classe Signature DSPy fraîchement créée.
    """
    if axis == "category":
        base_doc = (
            "Classifie la catégorie éditoriale d'un post Instagram du média "
            "Views à partir des features extraites et de la caption.\n\n"
            "## Catégories valides\n\n"
            f"{descriptions}"
        )
        cls = type(
            "CategoryClassifierFree",
            (dspy.Signature,),
            {
                "__doc__": base_doc,
                "__annotations__": {
                    "features": str,
                    "caption": str,
                    "category": str,
                },
                "features": dspy.InputField(desc="Features visuelles JSON"),
                "caption": dspy.InputField(desc="Caption Instagram (peut être vide)"),
                "category": dspy.OutputField(
                    desc="Nom exact de la catégorie parmi celles listées dans le docstring"
                ),
            },
        )
        return cls

    if axis == "visual_format":
        scope_label = scope or "ALL"
        base_doc = (
            f"Classifie le format visuel d'un post Instagram du média Views "
            f"(scope {scope_label}) à partir des features extraites et de la "
            f"caption.\n\n"
            f"## Formats visuels valides ({scope_label})\n\n"
            f"{descriptions}"
        )
        cls = type(
            f"VisualFormatClassifierFree_{scope_label}",
            (dspy.Signature,),
            {
                "__doc__": base_doc,
                "__annotations__": {
                    "features": str,
                    "caption": str,
                    "visual_format": str,
                },
                "features": dspy.InputField(desc="Features visuelles JSON"),
                "caption": dspy.InputField(desc="Caption Instagram (peut être vide)"),
                "visual_format": dspy.OutputField(
                    desc="Nom exact du format visuel parmi ceux listés dans le docstring"
                ),
            },
        )
        return cls

    if axis == "strategy":
        base_doc = (
            "Classifie la stratégie d'un post Instagram du média Views (Organic "
            "ou Brand Content) à partir des features extraites et de la caption.\n\n"
            "## Stratégies valides\n\n"
            f"{descriptions}"
        )
        cls = type(
            "StrategyClassifierFree",
            (dspy.Signature,),
            {
                "__doc__": base_doc,
                "__annotations__": {
                    "features": str,
                    "caption": str,
                    "strategy": str,
                },
                "features": dspy.InputField(desc="Features visuelles JSON"),
                "caption": dspy.InputField(desc="Caption Instagram (peut être vide)"),
                "strategy": dspy.OutputField(
                    desc="Nom exact de la stratégie parmi celles listées dans le docstring"
                ),
            },
        )
        return cls

    raise ValueError(f"axis invalide : {axis!r}")


# ─────────────────────────────────────────────────────────────────
# MODULES DSPy : wrappers autour de dspy.Predict
# ─────────────────────────────────────────────────────────────────


class ConstrainedClassifierProgram(dspy.Module):
    """Programme DSPy pour le mode constrained.

    Le champ `descriptions` est injecté à chaque appel comme InputField
    fixe — MIPROv2 ne le verra jamais comme un paramètre optimisable.
    """

    def __init__(
        self,
        axis: str,
        descriptions: str,
        valid_labels: list[str],
    ):
        super().__init__()
        if axis not in CONSTRAINED_SIGNATURES:
            raise ValueError(f"axis invalide : {axis!r}")
        self.axis = axis
        self.descriptions = descriptions
        self.valid_labels = valid_labels
        self.predict = dspy.Predict(CONSTRAINED_SIGNATURES[axis])

    def forward(self, features: str, caption: str, scope: str | None = None):
        # `scope` est dans la signature `dspy.Example` (cf. data.py) mais pas
        # dans la signature DSPy : on l'ignore ici.
        result = self.predict(
            features=features,
            caption=caption,
            descriptions=self.descriptions,
        )
        # Post-validation : vérifier que le label est dans l'enum
        # (DSPy ne contraint pas l'output, contrairement au tool calling MILPO)
        predicted = getattr(result, self.axis, None)
        if predicted is not None and predicted not in self.valid_labels:
            # On garde le label brut mais on log un warning via dspy.settings
            # si configuré. Pour les métriques, ça comptera comme erreur.
            pass
        return result


class FreeClassifierProgram(dspy.Module):
    """Programme DSPy pour le mode free.

    La signature est générée dynamiquement avec les descriptions dans le
    docstring. MIPROv2 peut alors réécrire l'intégralité du docstring (= les
    descriptions) lors de l'optimisation.
    """

    def __init__(
        self,
        axis: str,
        scope: str | None,
        descriptions: str,
        valid_labels: list[str],
    ):
        super().__init__()
        self.axis = axis
        self.scope = scope
        self.valid_labels = valid_labels
        signature_cls = make_free_signature(axis, scope, descriptions)
        self.predict = dspy.Predict(signature_cls)

    def forward(self, features: str, caption: str, scope: str | None = None):
        result = self.predict(features=features, caption=caption)
        return result


# ─────────────────────────────────────────────────────────────────
# Factory : construit le bon programme selon (mode, axis, scope)
# ─────────────────────────────────────────────────────────────────


def build_program(
    mode: str,
    axis: str,
    scope: str | None,
    descriptions: str,
    valid_labels: list[str],
) -> dspy.Module:
    """Instancie le programme adapté à (mode, axis, scope).

    Args:
        mode: 'constrained' ou 'free'
        axis: 'category', 'visual_format' ou 'strategy'
        scope: 'FEED', 'REELS' ou None (selon l'axe)
        descriptions: bloc des descriptions taxonomiques pour ce scope
        valid_labels: liste plate des labels valides (utilisée pour validation)
    """
    if mode == "constrained":
        return ConstrainedClassifierProgram(
            axis=axis,
            descriptions=descriptions,
            valid_labels=valid_labels,
        )
    if mode == "free":
        return FreeClassifierProgram(
            axis=axis,
            scope=scope,
            descriptions=descriptions,
            valid_labels=valid_labels,
        )
    raise ValueError(f"mode invalide : {mode!r}")
