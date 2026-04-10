"""Tools pour la pipeline agentique A0.

Tools de perception (construisent le contexte) :
- describe_media : Descripteur multimodal Gemini (JSON structuré ou texte libre)
- get_taxonomy   : Descriptions taxonomiques par axe/scope
- get_examples   : Exemples annotés du dev set (few-shot dynamique, filtre année)

Tool de sortie (structured output) :
- submit_classification : Soumet la classification (label enum strict + confidence)

L'advisor Opus est un tool serveur Anthropic natif (pas géré ici).
"""

from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from dataclasses import dataclass

from openai import OpenAI

from milpo.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from milpo.db import (
    format_descriptions,
    get_active_prompt,
    load_categories,
    load_strategies,
    load_visual_formats,
)
from milpo.schemas import DescriptorFeatures, build_json_schema_response_format

from agents.config import (
    DEFAULT_EXAMPLES,
    MAX_EXAMPLES_PER_CALL,
    MODEL_ADVISOR,
    MODEL_DESCRIPTOR,
)

log = logging.getLogger("agents")


# ── Prompts des tools chargés depuis la BDD ───────────────────────


@dataclass
class ToolPrompts:
    """Prompts des tools, chargés depuis prompt_versions."""

    describe_media: str
    get_taxonomy: str
    get_examples: str
    descriptor_focus: str


def load_tool_prompts(conn) -> ToolPrompts:
    """Charge les 4 prompts de tools depuis la BDD (migration 013)."""
    sources = {
        "describe_media": "agent_tool_describe",
        "get_taxonomy": "agent_tool_taxonomy",
        "get_examples": "agent_tool_examples",
        "descriptor_focus": "agent_tool_desc_focus",
    }
    return ToolPrompts(**{
        field: get_active_prompt(conn, "agent_executor", None, source=source)["content"]
        for field, source in sources.items()
    })


# ── Définitions des tools (format Anthropic) ──────────────────────


def _perception_tools(prompts: ToolPrompts) -> list[dict]:
    """Tools de perception avec descriptions chargées depuis la BDD."""
    return [
        {
            "type": "advisor_20260301",
            "name": "advisor",
            "model": MODEL_ADVISOR,
        },
        {
            "name": "describe_media",
            "description": prompts.describe_media,
            "input_schema": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": (
                            "Question libre optionnelle pour cibler l'analyse. "
                            "Si absent, retourne la description structurée complète."
                        ),
                    },
                },
                "required": [],
            },
        },
        {
            "name": "get_taxonomy",
            "description": prompts.get_taxonomy,
            "input_schema": {
                "type": "object",
                "properties": {
                    "axis": {
                        "type": "string",
                        "enum": ["category", "visual_format", "strategy"],
                        "description": "Axe de classification.",
                    },
                },
                "required": ["axis"],
            },
        },
        {
            "name": "get_examples",
            "description": prompts.get_examples,
            "input_schema": {
                "type": "object",
                "properties": {
                    "axis": {
                        "type": "string",
                        "enum": ["category", "visual_format", "strategy"],
                        "description": "Axe de classification.",
                    },
                    "label": {
                        "type": "string",
                        "description": "Label pour lequel récupérer des exemples.",
                    },
                    "n": {
                        "type": "integer",
                        "description": f"Nombre d'exemples (défaut: {DEFAULT_EXAMPLES}, max: {MAX_EXAMPLES_PER_CALL}).",
                    },
                },
                "required": ["axis", "label"],
            },
        },
    ]


def build_submit_tool(axis: str, labels: list[str]) -> dict:
    """Construit le tool submit_classification avec enum stricte pour un axe donné.

    L'agent DOIT appeler ce tool pour soumettre sa classification.
    strict=True garantit que le label est dans l'enum.
    """
    return {
        "name": "submit_classification",
        "description": (
            f"Soumet ta classification pour l'axe '{axis}'. "
            f"Appelle ce tool quand tu as fini de raisonner."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Ton raisonnement en quelques phrases.",
                },
                "label": {
                    "type": "string",
                    "enum": labels,
                    "description": f"Le label choisi pour l'axe '{axis}'.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Ton niveau de confiance.",
                },
            },
            "required": ["reasoning", "label", "confidence"],
            "additionalProperties": False,
        },
    }


def build_tools_for_phase(axis: str, labels: list[str], prompts: ToolPrompts) -> list[dict]:
    """Construit les tools complets pour une phase de classification.

    Perception tools (descriptions depuis BDD) + submit_classification (enum dynamique).
    """
    return _perception_tools(prompts) + [build_submit_tool(axis, labels)]


# ── Client OpenRouter pour le descripteur Gemini ──────────────────


def _get_openrouter_client() -> OpenAI:
    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)


# ── Contexte média (partagé entre les appels describe_media) ──────


class MediaContext:
    """Contexte média pré-chargé pour un post (URLs signées, scope, année)."""

    def __init__(
        self,
        media_urls: list[str],
        media_types: list[str],
        caption: str | None,
        scope: str,
        post_year: int,
        descriptor_instructions: str,
        descriptor_descriptions: str,
    ):
        self.media_urls = media_urls
        self.media_types = media_types
        self.caption = caption
        self.scope = scope
        self.post_year = post_year
        self.descriptor_instructions = descriptor_instructions
        self.descriptor_descriptions = descriptor_descriptions
        self._cached_features: DescriptorFeatures | None = None
        self._cached_features_json: str | None = None


# ── Implémentation des tools ──────────────────────────────────────


def execute_describe_media(
    media_ctx: MediaContext,
    focus: str | None = None,
    descriptor_focus_prompt: str = "",
) -> tuple[str, dict]:
    """Exécute le tool describe_media.

    Sans focus : appelle Gemini avec JSON structuré (comme la pipeline classique).
    Avec focus : appelle Gemini avec question libre, réponse texte.

    Returns:
        (result_text, api_usage)
    """
    client = _get_openrouter_client()

    # Construire les blocs média pour le message user
    content: list[dict] = []
    for url, mtype in zip(media_ctx.media_urls, media_ctx.media_types):
        if mtype == "VIDEO":
            content.append({"type": "video_url", "video_url": {"url": url}})
        else:
            content.append({"type": "image_url", "image_url": {"url": url}})

    caption_text = media_ctx.caption or "(pas de caption)"

    if focus is None:
        # Mode structuré (identique pipeline classique)
        if media_ctx._cached_features_json is not None:
            return media_ctx._cached_features_json, {
                "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
                "model": MODEL_DESCRIPTOR, "cached": True,
            }

        system = (
            f"{media_ctx.descriptor_instructions}\n\n"
            f"## Critères discriminants à observer\n\n"
            f"{media_ctx.descriptor_descriptions}"
        )
        content.append({"type": "text", "text": f"Caption du post :\n{caption_text}"})

        response_format = build_json_schema_response_format(
            "descriptor_features",
            DescriptorFeatures.model_json_schema(),
        )

        t0 = time.monotonic()
        response = client.chat.completions.create(
            model=MODEL_DESCRIPTOR,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            response_format=response_format,
            temperature=0.1,
        )

        raw = response.choices[0].message.content or ""
        features = DescriptorFeatures.model_validate_json(raw)
        features_json = features.model_dump_json(indent=2)
        latency_ms = int((time.monotonic() - t0) * 1000)

        media_ctx._cached_features = features
        media_ctx._cached_features_json = features_json

        usage = response.usage
        api_usage = {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "latency_ms": latency_ms,
            "model": MODEL_DESCRIPTOR,
        }
        return features_json, api_usage

    else:
        # Mode focus (texte libre) — prompt chargé depuis BDD
        system = descriptor_focus_prompt
        content.append({
            "type": "text",
            "text": f"Caption du post :\n{caption_text}\n\n---\n\nQuestion : {focus}",
        })

        t0 = time.monotonic()
        response = client.chat.completions.create(
            model=MODEL_DESCRIPTOR,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            temperature=0.3,
        )

        text = response.choices[0].message.content or ""
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = response.usage
        api_usage = {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "latency_ms": latency_ms,
            "model": MODEL_DESCRIPTOR,
        }
        return text, api_usage


def execute_get_taxonomy(
    axis: str,
    scope: str,
    conn,
) -> str:
    """Exécute le tool get_taxonomy. Retourne les descriptions formatées."""
    if axis == "category":
        items = load_categories(conn)
    elif axis == "visual_format":
        items = load_visual_formats(conn, scope)
    elif axis == "strategy":
        items = load_strategies(conn)
    else:
        return f"Erreur : axe inconnu '{axis}'. Axes valides : category, visual_format, strategy."

    return f"## Taxonomie — {axis} ({scope})\n\n{format_descriptions(items)}"


def execute_get_examples(
    axis: str,
    label: str,
    n: int,
    scope: str,
    post_year: int,
    conn,
) -> str:
    """Exécute le tool get_examples. Retourne des exemples annotés du dev set.

    Filtre par label, scope (pour vf), et année proche du post courant.
    Retourne caption + annotation humaine.
    """
    n = min(max(n, 1), MAX_EXAMPLES_PER_CALL)

    # Construire la requête selon l'axe
    if axis == "category":
        query = """
            SELECT p.caption, p.media_product_type::text AS scope,
                   c.name AS category, vf.name AS visual_format,
                   a.strategy::text AS strategy,
                   EXTRACT(YEAR FROM p.timestamp)::int AS year
            FROM annotations a
            JOIN posts p ON p.ig_media_id = a.ig_media_id
            JOIN sample_posts sp ON sp.ig_media_id = a.ig_media_id
            JOIN categories c ON c.id = a.category_id
            JOIN visual_formats vf ON vf.id = a.visual_format_id
            WHERE sp.split = 'dev' AND c.name = %s
              AND EXTRACT(YEAR FROM p.timestamp) BETWEEN %s AND %s
            ORDER BY ABS(EXTRACT(YEAR FROM p.timestamp) - %s), RANDOM()
            LIMIT %s
        """
        params = (label, post_year - 1, post_year + 1, post_year, n)

    elif axis == "visual_format":
        query = """
            SELECT p.caption, p.media_product_type::text AS scope,
                   c.name AS category, vf.name AS visual_format,
                   a.strategy::text AS strategy,
                   EXTRACT(YEAR FROM p.timestamp)::int AS year
            FROM annotations a
            JOIN posts p ON p.ig_media_id = a.ig_media_id
            JOIN sample_posts sp ON sp.ig_media_id = a.ig_media_id
            JOIN categories c ON c.id = a.category_id
            JOIN visual_formats vf ON vf.id = a.visual_format_id
            WHERE sp.split = 'dev' AND vf.name = %s
              AND p.media_product_type = %s::media_product_type
              AND EXTRACT(YEAR FROM p.timestamp) BETWEEN %s AND %s
            ORDER BY ABS(EXTRACT(YEAR FROM p.timestamp) - %s), RANDOM()
            LIMIT %s
        """
        params = (label, scope, post_year - 1, post_year + 1, post_year, n)

    elif axis == "strategy":
        query = """
            SELECT p.caption, p.media_product_type::text AS scope,
                   c.name AS category, vf.name AS visual_format,
                   a.strategy::text AS strategy,
                   EXTRACT(YEAR FROM p.timestamp)::int AS year
            FROM annotations a
            JOIN posts p ON p.ig_media_id = a.ig_media_id
            JOIN sample_posts sp ON sp.ig_media_id = a.ig_media_id
            JOIN categories c ON c.id = a.category_id
            JOIN visual_formats vf ON vf.id = a.visual_format_id
            WHERE sp.split = 'dev' AND a.strategy = %s::strategy_type
              AND EXTRACT(YEAR FROM p.timestamp) BETWEEN %s AND %s
            ORDER BY ABS(EXTRACT(YEAR FROM p.timestamp) - %s), RANDOM()
            LIMIT %s
        """
        params = (label, post_year - 1, post_year + 1, post_year, n)

    else:
        return f"Erreur : axe inconnu '{axis}'."

    rows = conn.execute(query, params).fetchall()

    if not rows:
        return f"Aucun exemple annoté trouvé pour {axis}='{label}' (année ~{post_year})."

    lines = [f"## Exemples annotés — {axis}='{label}' ({len(rows)} résultats)\n"]
    for i, r in enumerate(rows, 1):
        caption_preview = (r["caption"] or "(pas de caption)")[:200]
        lines.append(f"### Exemple {i} ({r['year']})")
        lines.append(f"- **Scope** : {r['scope']}")
        lines.append(f"- **Caption** : {caption_preview}")
        lines.append(f"- **Category** : {r['category']}")
        lines.append(f"- **Visual format** : {r['visual_format']}")
        lines.append(f"- **Strategy** : {r['strategy']}")
        lines.append("")

    return "\n".join(lines)


# ── Dispatch ──────────────────────────────────────────────────────


def execute_tool(
    tool_name: str,
    tool_input: dict,
    media_ctx: MediaContext,
    conn,
    tool_prompts: ToolPrompts | None = None,
) -> tuple[str, dict | None]:
    """Dispatch un appel tool et retourne (result_text, api_usage_or_none).

    Les tools serveur (advisor) ne passent jamais par ici — ils sont gérés
    par Anthropic côté serveur.
    """
    if tool_name == "describe_media":
        focus = tool_input.get("focus")
        desc_focus = tool_prompts.descriptor_focus if tool_prompts else ""
        result, api_usage = execute_describe_media(media_ctx, focus, desc_focus)
        return result, api_usage

    elif tool_name == "get_taxonomy":
        axis = tool_input.get("axis", "category")
        result = execute_get_taxonomy(axis, media_ctx.scope, conn)
        return result, None

    elif tool_name == "get_examples":
        axis = tool_input.get("axis", "category")
        label = tool_input.get("label", "")
        n = tool_input.get("n", DEFAULT_EXAMPLES)
        result = execute_get_examples(
            axis, label, n, media_ctx.scope, media_ctx.post_year, conn,
        )
        return result, None

    else:
        return f"Erreur : tool inconnu '{tool_name}'.", None
