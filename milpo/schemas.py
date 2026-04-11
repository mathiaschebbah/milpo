"""Schemas Pydantic pour le pipeline MILPO."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class StrictBaseModel(BaseModel):
    """Base model avec schéma strict pour les structured outputs."""

    model_config = ConfigDict(extra="forbid")


# ── Résultat de classification d'un post ───────────────────────


class PostPrediction(StrictBaseModel):
    """Prédictions pour un post (3 axes)."""

    ig_media_id: int
    category: str
    visual_format: str
    strategy: str
    features: str


# ── Schémas pour la boucle ProTeGi (Pryzant et al. 2023) ───────


class GradientPayload(StrictBaseModel):
    """Sortie du LLM_∇ (critic) — liste de critiques en langage naturel."""

    critiques: list[str]

    @field_validator("critiques")
    @classmethod
    def validate_non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("critiques must not be empty")
        for c in value:
            if not c.strip():
                raise ValueError("each critique must not be blank")
        return value


class EditCandidatePayload(StrictBaseModel):
    """Un candidat édité par le LLM_δ (editor)."""

    new_instructions: str
    reasoning: str

    @field_validator("new_instructions", "reasoning")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class EditCandidatesPayload(StrictBaseModel):
    """Sortie du LLM_δ — liste de candidats édités."""

    candidates: list[EditCandidatePayload]

    @field_validator("candidates")
    @classmethod
    def validate_non_empty(cls, value: list[EditCandidatePayload]) -> list[EditCandidatePayload]:
        if not value:
            raise ValueError("candidates must not be empty")
        return value


class ParaphrasesPayload(StrictBaseModel):
    """Sortie du LLM_mc (paraphraser) — liste de paraphrases."""

    paraphrases: list[str]

    @field_validator("paraphrases")
    @classmethod
    def validate_non_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("paraphrases must not be empty")
        for p in value:
            if not p.strip():
                raise ValueError("each paraphrase must not be blank")
        return value


def build_json_schema_response_format(name: str, schema: dict) -> dict:
    """Construit un response_format json_schema strict pour chat.completions."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


def build_classifier_response_schema(labels: list[str]) -> dict:
    """Schéma strict (reasoning + label + confidence) pour un classifieur MILPO.

    L'ordre des champs matters : reasoning est placé en premier pour
    forcer le LLM à raisonner explicitement avant de commiter un label
    (chain-of-thought structuré, Wei et al. 2022).

    Réutilisé par build_classifier_tool() pour les paramètres du tool function.
    """

    return {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "Raisonnement explicite avant de décider du label. "
                    "Cite les signaux observés dans les features descripteur "
                    "et applique les règles de désambiguation de la taxonomie."
                ),
            },
            "label": {
                "type": "string",
                "enum": labels,
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["reasoning", "label", "confidence"],
        "additionalProperties": False,
    }


def build_classifier_tool(axis: str, labels: list[str]) -> dict:
    """Construit la définition tool/function pour un classifieur MILPO.

    On utilise l'API tool calling (function calling) plutôt que
    response_format=json_schema parce que tool calling est universellement
    supporté par tous les providers OpenRouter, alors que json_schema strict
    n'est pas honoré par certains providers (notamment Qwen 3.5 Flash sur
    les enums binaires : il renvoie un float au lieu d'un objet).
    """

    return {
        "type": "function",
        "function": {
            "name": f"classify_{axis}",
            "description": f"Classifie le post sur l'axe '{axis}'.",
            "parameters": build_classifier_response_schema(labels),
        },
    }


class ClassifierDecision(StrictBaseModel):
    """Décision structurée d'un classifieur (reasoning + label + confidence).

    Utilisée pour valider les arguments parsés depuis tool_call.function.arguments.
    Le champ reasoning implémente un chain-of-thought structuré (Wei et al. 2022) :
    le LLM est forcé de raisonner explicitement avant de choisir un label.
    Optionnel pour rétrocompatibilité avec d'anciens call-sites qui ne
    l'émettaient pas.
    """

    reasoning: str = ""
    label: str
    confidence: Literal["high", "medium", "low"]


# ── Schémas pour l'optimisation structurée à patches DSL ─────────


class RuleCritiquePayload(StrictBaseModel):
    """Sortie du critic règles : 1 critique + index de la règle ciblée."""

    critique: str
    target_rule_index: Optional[int] = None

    @field_validator("critique")
    @classmethod
    def validate_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("critique must not be blank")
        return value


class DSLRulePayload(StrictBaseModel):
    """Payload d'une règle DSL pour le structured output de l'editor."""

    rule_type: Literal[
        "signal_to_label", "disambiguation", "priority", "fallback", "caption_policy"
    ]
    signals: Optional[list[str]] = None
    label: Optional[str] = None
    label_a: Optional[str] = None
    label_b: Optional[str] = None
    criterion: Optional[str] = None
    high_signal: Optional[str] = None
    low_signal: Optional[str] = None
    caption_mode: Optional[str] = None


class RulePatchPayload(StrictBaseModel):
    """Un patch typé proposé par l'editor."""

    op_type: Literal["add_rule", "remove_rule", "replace_rule", "reorder_rule"]
    index: Optional[int] = None
    new_rule: Optional[DSLRulePayload] = None
    new_position: Optional[int] = None
    reasoning: str

    @field_validator("reasoning")
    @classmethod
    def validate_reasoning_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reasoning must not be blank")
        return value


class RulePatchesPayload(StrictBaseModel):
    """Sortie de l'editor règles : exactement 3 patches."""

    patches: list[RulePatchPayload]

    @field_validator("patches")
    @classmethod
    def validate_patches(cls, value: list[RulePatchPayload]) -> list[RulePatchPayload]:
        if not value:
            raise ValueError("patches must not be empty")
        return value
