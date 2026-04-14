"""Catalogue partagé des prompts et taxonomies MILPO."""

from __future__ import annotations

from collections.abc import Mapping

from milpo.db import (
    get_active_prompt,
    get_prompt_version,
)
from milpo.inference import PromptSet
from milpo.taxonomy_renderer import load_taxonomy_yaml, render_taxonomy_for_scope

PromptKey = tuple[str, str | None]
PromptRecordMap = dict[PromptKey, dict]
PromptIdMap = dict[PromptKey, int]
PromptVersionMap = dict[PromptKey, int]
PromptContentMap = Mapping[PromptKey, str]

PROMPT_KEYS: list[PromptKey] = [
    ("descriptor", "FEED"),
    ("descriptor", "REELS"),
    ("category", None),
    ("visual_format", "FEED"),
    ("visual_format", "REELS"),
    ("strategy", None),
]

DSPY_MODES = ("dspy_constrained", "dspy_free")


def build_labels(conn, scope: str) -> dict[str, list[str]]:
    del conn
    return {
        "category": [c["class"] for c in load_taxonomy_yaml("CATEGORY")],
        "visual_format": [f["class"] for f in load_taxonomy_yaml(scope)],
        "strategy": [s["class"] for s in load_taxonomy_yaml("STRATEGY")],
    }


def build_prompt_set(
    conn,
    scope: str,
    prompt_contents: PromptContentMap,
) -> PromptSet:
    del conn

    vf_canonical = render_taxonomy_for_scope(scope)
    cat_canonical = render_taxonomy_for_scope("CATEGORY")
    strat_canonical = render_taxonomy_for_scope("STRATEGY")

    return PromptSet(
        descriptor_instructions=prompt_contents[("descriptor", scope)],
        category_instructions=prompt_contents[("category", None)],
        visual_format_instructions=prompt_contents[("visual_format", scope)],
        strategy_instructions=prompt_contents[("strategy", None)],
        descriptor_descriptions=(
            "## Formats visuels\n\n" + vf_canonical
            + "\n\n## Catégories\n\n" + cat_canonical
            + "\n\n## Stratégies\n\n" + strat_canonical
        ),
        category_descriptions=cat_canonical,
        visual_format_descriptions=vf_canonical,
        strategy_descriptions=strat_canonical,
    )


def prompt_contents_from_records(prompt_records: PromptRecordMap) -> dict[PromptKey, str]:
    return {key: row["content"] for key, row in prompt_records.items()}


def load_prompt_bundle(
    conn,
    prompt_mode: str,
    prompt_keys: list[PromptKey] | None = None,
) -> tuple[PromptRecordMap, PromptIdMap]:
    """Charge les prompts requis depuis la BDD pour un mode baseline."""
    prompt_records: PromptRecordMap = {}
    prompt_ids: PromptIdMap = {}

    for key in prompt_keys or PROMPT_KEYS:
        agent, scope = key
        if agent == "descriptor" and prompt_mode in DSPY_MODES:
            effective_mode = "v0"
        else:
            effective_mode = prompt_mode

        row = load_prompt_record(conn, agent, scope, effective_mode)
        prompt_records[key] = row
        prompt_ids[key] = row["id"]

    return prompt_records, prompt_ids


def load_prompt_record(conn, agent: str, scope: str | None, prompt_mode: str) -> dict:
    """Charge un prompt depuis la BDD selon le mode demandé."""
    if prompt_mode == "active":
        row = get_active_prompt(conn, agent, scope, source="human_v0")
    elif prompt_mode == "v0":
        row = get_prompt_version(conn, agent, scope, version=0, source="human_v0")
    elif prompt_mode in DSPY_MODES:
        row = get_active_prompt(conn, agent, scope, source=prompt_mode)
        if row is None:
            row = get_active_prompt(conn, agent, scope, source="human_v0")
    else:
        raise ValueError(f"Mode prompt inconnu : {prompt_mode!r}")

    if row is None:
        raise RuntimeError(
            f"Prompt introuvable en BDD pour {agent}/{scope or 'all'} (mode={prompt_mode})."
        )
    return row


def load_active_prompt_records(
    conn,
    prompt_keys: list[PromptKey] | None = None,
    source: str = "human_v0",
) -> tuple[PromptRecordMap, PromptIdMap, PromptVersionMap]:
    """Charge les prompts actifs d'une liste de slots."""
    prompt_records: PromptRecordMap = {}
    prompt_ids: PromptIdMap = {}
    prompt_versions: PromptVersionMap = {}

    for agent, scope in prompt_keys or PROMPT_KEYS:
        row = get_active_prompt(conn, agent, scope, source=source)
        if row is None:
            raise RuntimeError(
                f"Prompt actif introuvable en BDD pour {agent}/{scope or 'all'}."
            )
        key = (agent, scope)
        prompt_records[key] = row
        prompt_ids[key] = row["id"]
        prompt_versions[key] = row["version"]

    return prompt_records, prompt_ids, prompt_versions


def load_descriptor_prompt_configs(conn, source: str = "human_v0") -> dict[str, dict]:
    """Charge les prompts descripteur scopeés avec leurs descriptions taxonomiques."""
    out: dict[str, dict] = {}
    for scope in ("FEED", "REELS"):
        record = get_active_prompt(conn, "descriptor", scope, source=source)
        if record is None:
            raise RuntimeError(f"Prompt descripteur introuvable pour scope={scope}")
        vf_canonical = render_taxonomy_for_scope(scope)
        cat_canonical = render_taxonomy_for_scope("CATEGORY")
        strat_canonical = render_taxonomy_for_scope("STRATEGY")
        out[scope] = {
            "instructions": record["content"],
            "descriptions": (
                "## Formats visuels\n\n" + vf_canonical
                + "\n\n## Catégories\n\n" + cat_canonical
                + "\n\n## Stratégies\n\n" + strat_canonical
            ),
            "id": record["id"],
        }
    return out


def build_target_descriptions(
    conn,
    target_agent: str,
    target_scope: str | None,
) -> str:
    """Charge les descriptions taxonomiques pertinentes pour une cible de rewrite."""
    del conn
    effective_scope = target_scope or "FEED"
    if target_agent == "descriptor":
        return (
            "## Formats visuels\n\n"
            + render_taxonomy_for_scope(effective_scope)
            + "\n\n## Catégories\n\n"
            + render_taxonomy_for_scope("CATEGORY")
            + "\n\n## Stratégies\n\n"
            + render_taxonomy_for_scope("STRATEGY")
        )
    if target_agent == "visual_format":
        return render_taxonomy_for_scope(effective_scope)
    if target_agent == "category":
        return render_taxonomy_for_scope("CATEGORY")
    if target_agent == "strategy":
        return render_taxonomy_for_scope("STRATEGY")
    raise ValueError(f"target_agent inconnu: {target_agent}")
