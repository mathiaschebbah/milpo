"""Pipeline agentique A0 — Haiku executor + Opus advisor.

Architecture par post (1 conversation multi-tours) :
1. Phase category   : tools de perception → raisonnement → classification
2. Phase vf         : informé par category → tools → classification
3. Phase strategy   : informé par category + vf → tools → classification

L'advisor Opus est disponible comme tool natif Anthropic. Haiku décide
seul quand l'invoquer (cas d'hésitation entre labels proches).

Routage FEED/REELS : déterministe, basé sur media_product_type du post.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import anthropic

from agents.config import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS_PER_TURN,
    MAX_TOOL_ROUNDS,
    MODEL_EXECUTOR,
)
from agents.tools import MediaContext, ToolPrompts, build_tools_for_phase, execute_tool, load_tool_prompts
from milpo.db import get_active_prompt

log = logging.getLogger("agents")


# ── Structures de résultat ────────────────────────────────────────


@dataclass
class AxisClassification:
    label: str
    confidence: str
    reasoning: str


@dataclass
class ApiCallRecord:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class TraceEvent:
    """Un événement dans la trace structurée de l'agent."""

    type: str       # "tool_call" | "advisor_call" | "classification"
    phase: str      # "category" | "visual_format" | "strategy"
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "phase": self.phase, **self.data}


@dataclass
class AgentResult:
    """Résultat complet de la pipeline agentique pour un post."""

    ig_media_id: int
    category: AxisClassification
    visual_format: AxisClassification
    strategy: AxisClassification
    api_calls: list[ApiCallRecord] = field(default_factory=list)
    advisor_calls: int = 0
    tool_calls: int = 0
    trace: list[TraceEvent] = field(default_factory=list)
    latency_ms: int = 0
    prompt_version_id: int | None = None


# ── System prompt ─────────────────────────────────────────────────
# Versionné en BDD (agent='agent_executor', source='agent_v0').
# Pas de fallback hardcodé — la BDD est la source de vérité unique.


def load_agent_system_prompt(
    conn,
    source: str = "agent_v0",
) -> tuple[str, int]:
    """Charge le system prompt de l'agent depuis la BDD (migration 012)."""
    row = get_active_prompt(conn, "agent_executor", None, source=source)
    return row["content"], row["id"]




# ── Boucle agentique ──────────────────────────────────────────────


def _get_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY non définie. Ajoute-la dans .env."
        )
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _run_agent_phase(
    client: anthropic.Anthropic,
    system: str,
    messages: list[dict],
    tools: list[dict],
    media_ctx: MediaContext,
    conn,
    axis: str,
    tool_prompts: ToolPrompts | None = None,
) -> tuple[AxisClassification, list[ApiCallRecord], list[TraceEvent], int, int]:
    """Exécute une phase de classification (1 axe) dans la conversation.

    Gère la boucle tool-use jusqu'à ce que l'agent émette sa classification.

    Returns:
        (classification, api_calls, trace_events, advisor_count, tool_count)
    """
    api_calls: list[ApiCallRecord] = []
    trace_events: list[TraceEvent] = []
    advisor_count = 0
    tool_count = 0
    full_reasoning = []

    for round_idx in range(MAX_TOOL_ROUNDS):
        t0 = time.monotonic()

        # Retry avec backoff exponentiel sur les 429 (rate limit)
        for attempt in range(5):
            try:
                response = client.beta.messages.create(
                    model=MODEL_EXECUTOR,
                    max_tokens=MAX_TOKENS_PER_TURN,
                    system=system,
                    tools=tools,
                    messages=messages,
                    betas=["advisor-tool-2026-03-01"],
                )
                break
            except anthropic.RateLimitError:
                wait = 2 ** attempt * 15  # 15s, 30s, 60s, 120s, 240s
                log.debug("  rate limit, retry in %ds (attempt %d/5)", wait, attempt + 1)
                time.sleep(wait)
        else:
            raise anthropic.RateLimitError("rate limit épuisé après 5 retries")

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Comptabiliser les tokens executor
        if response.usage:
            api_calls.append(ApiCallRecord(
                agent=f"agent/{axis}",
                model=MODEL_EXECUTOR,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
            ))

        # Comptabiliser les tokens advisor (dans iterations)
        if hasattr(response, "usage") and response.usage:
            for it in getattr(response.usage, "iterations", []) or []:
                if getattr(it, "type", None) == "advisor_message":
                    api_calls.append(ApiCallRecord(
                        agent=f"advisor/{axis}",
                        model=getattr(it, "model", "claude-opus-4-6"),
                        input_tokens=getattr(it, "input_tokens", 0),
                        output_tokens=getattr(it, "output_tokens", 0),
                        latency_ms=0,
                    ))
                    advisor_count += 1
                    trace_events.append(TraceEvent(
                        type="advisor_call", phase=axis,
                    ))

        # Collecter le texte, détecter advisor_tool_result_error
        for block in response.content:
            if hasattr(block, "text"):
                full_reasoning.append(block.text)
            # server_tool_use (advisor) est déjà tracé via iterations ci-dessus
            # Tracer les erreurs advisor (overloaded, max_uses_exceeded, etc.)
            if getattr(block, "type", None) == "advisor_tool_result":
                content = getattr(block, "content", None)
                if content and getattr(content, "type", None) == "advisor_tool_result_error":
                    error_code = getattr(content, "error_code", "unknown")
                    log.warning("  %s: advisor error — %s", axis, error_code)
                    trace_events.append(TraceEvent(
                        type="advisor_error", phase=axis,
                        data={"error_code": error_code},
                    ))

        # Chercher submit_classification parmi les tool_use blocks
        all_tool_uses = [b for b in response.content if b.type == "tool_use"]
        submit_tu = next((b for b in all_tool_uses if b.name == "submit_classification"), None)

        if submit_tu:
            # Classification soumise via structured output
            label = submit_tu.input.get("label", "MISSING")
            confidence = submit_tu.input.get("confidence", "low")
            reasoning = submit_tu.input.get("reasoning", "")

            trace_events.append(TraceEvent(
                type="classification", phase=axis,
                data={"label": label, "confidence": confidence},
            ))

            # Ajouter la réponse assistant pour le contexte multi-tours
            messages.append({"role": "assistant", "content": response.content})
            # Fournir le tool_result pour submit (obligatoire dans le protocole)
            messages.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": submit_tu.id,
                "content": f"Classification enregistrée : {label} ({confidence})",
            }]})

            all_text = "\n".join(full_reasoning)
            return (
                AxisClassification(
                    label=label, confidence=confidence,
                    reasoning=(reasoning or all_text[-500:]),
                ),
                api_calls, trace_events, advisor_count, tool_count,
            )

        # Pas de submit_classification et pas de tool_use → fin sans classification
        if response.stop_reason != "tool_use":
            log.warning("  %s: l'agent a terminé sans appeler submit_classification", axis)
            all_text = "\n".join(full_reasoning)
            trace_events.append(TraceEvent(
                type="classification", phase=axis,
                data={"label": "NO_SUBMIT", "confidence": "low"},
            ))
            messages.append({"role": "assistant", "content": response.content})
            return (
                AxisClassification(label="NO_SUBMIT", confidence="low", reasoning=all_text[-500:]),
                api_calls, trace_events, advisor_count, tool_count,
            )

        # Pas de submit mais des tool_use de perception → exécuter et continuer
        perception_tool_uses = [b for b in all_tool_uses if b.name != "submit_classification"]
        if not perception_tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in perception_tool_uses:
            tool_count += 1

            t_tool = time.monotonic()
            result_text, api_usage = execute_tool(
                tu.name, tu.input, media_ctx, conn, tool_prompts,
            )
            tool_latency = int((time.monotonic() - t_tool) * 1000)

            trace_events.append(TraceEvent(
                type="tool_call", phase=axis,
                data={
                    "tool": tu.name,
                    "input": {k: v for k, v in tu.input.items() if k != "focus" or v} if tu.input else {},
                    "latency_ms": tool_latency,
                },
            ))

            if api_usage:
                api_calls.append(ApiCallRecord(
                    agent=f"tool/{tu.name}",
                    model=api_usage.get("model", "unknown"),
                    input_tokens=api_usage.get("input_tokens", 0),
                    output_tokens=api_usage.get("output_tokens", 0),
                    latency_ms=api_usage.get("latency_ms", 0),
                ))

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})

    # Sécurité : max rounds atteint sans submit
    all_text = "\n".join(full_reasoning)
    log.warning("  %s: max rounds (%d) atteint sans submit_classification", axis, MAX_TOOL_ROUNDS)
    trace_events.append(TraceEvent(
        type="classification", phase=axis,
        data={"label": "MAX_ROUNDS", "confidence": "low"},
    ))
    return (
        AxisClassification(label="MAX_ROUNDS", confidence="low", reasoning=all_text[-500:]),
        api_calls, trace_events, advisor_count, tool_count,
    )


# ── Pipeline complète ─────────────────────────────────────────────


def classify_post_agentic(
    ig_media_id: int,
    media_ctx: MediaContext,
    conn,
    prompt_source: str = "agent_v0",
) -> AgentResult:
    """Classifie un post via la pipeline agentique A0.

    1 conversation multi-tours, séquentiel : category → visual_format → strategy.
    Le system prompt est chargé depuis la BDD (versionné, optimisable).
    """
    from milpo.db import load_categories, load_strategies, load_visual_formats

    client = _get_client()

    # Charger tous les prompts depuis la BDD
    system_template, prompt_version_id = load_agent_system_prompt(conn, source=prompt_source)
    tool_prompts = load_tool_prompts(conn)
    format_prefix = "post" if media_ctx.scope == "FEED" else "reel"
    system = system_template.format(scope=media_ctx.scope, format_prefix=format_prefix)

    # Charger les labels pour les enums du tool submit_classification
    category_labels = [c["name"] for c in load_categories(conn)]
    vf_labels = [f["name"] for f in load_visual_formats(conn, media_ctx.scope)]
    strategy_labels = [s["name"] for s in load_strategies(conn)]

    all_api_calls: list[ApiCallRecord] = []
    total_advisor = 0
    total_tools = 0

    messages: list[dict] = []

    # ── Phase 1 : Category ────────────────────────────────────────

    tools_cat = build_tools_for_phase("category", category_labels, tool_prompts)

    messages.append({
        "role": "user",
        "content": (
            f"Voici un post Instagram Views ({media_ctx.scope}).\n\n"
            f"- **Caption** : {(media_ctx.caption or '(pas de caption)')[:500]}\n\n"
            f"**Étape 1/3 — Classifie la CATÉGORIE de ce post.**\n"
            f"Commence par appeler describe_media, puis get_taxonomy. "
            f"Quand tu es prêt, appelle submit_classification."
        ),
    })

    t0_post = time.monotonic()
    all_trace: list[TraceEvent] = []

    log.debug("  phase category...")
    cat, calls, trace, adv, tc = _run_agent_phase(
        client, system, messages, tools_cat, media_ctx, conn, "category", tool_prompts,
    )
    all_api_calls.extend(calls)
    all_trace.extend(trace)
    total_advisor += adv
    total_tools += tc
    log.debug("  → category=%s (%s) [%d tools, %d advisor]", cat.label, cat.confidence, tc, adv)

    # ── Phase 2 : Visual Format ───────────────────────────────────

    tools_vf = build_tools_for_phase("visual_format", vf_labels, tool_prompts)

    messages.append({
        "role": "user",
        "content": (
            f"Catégorie classifiée : **{cat.label}** (confiance: {cat.confidence}).\n\n"
            f"**Étape 2/3 — Classifie le VISUAL_FORMAT de ce post.**\n"
            f"Les labels sont {format_prefix}_*. "
            f"Appelle get_taxonomy pour les découvrir, puis submit_classification."
        ),
    })

    log.debug("  phase visual_format...")
    vf, calls, trace, adv, tc = _run_agent_phase(
        client, system, messages, tools_vf, media_ctx, conn, "visual_format", tool_prompts,
    )
    all_api_calls.extend(calls)
    all_trace.extend(trace)
    total_advisor += adv
    total_tools += tc
    log.debug("  → visual_format=%s (%s) [%d tools, %d advisor]", vf.label, vf.confidence, tc, adv)

    # ── Phase 3 : Strategy ────────────────────────────────────────

    tools_strat = build_tools_for_phase("strategy", strategy_labels, tool_prompts)

    messages.append({
        "role": "user",
        "content": (
            f"Visual format classifié : **{vf.label}** (confiance: {vf.confidence}).\n\n"
            f"**Étape 3/3 — Classifie la STRATEGY de ce post.**\n"
            f"Tu as déjà tout le contexte. Appelle submit_classification."
        ),
    })

    log.debug("  phase strategy...")
    strat, calls, trace, adv, tc = _run_agent_phase(
        client, system, messages, tools_strat, media_ctx, conn, "strategy", tool_prompts,
    )
    all_api_calls.extend(calls)
    all_trace.extend(trace)
    total_advisor += adv
    total_tools += tc
    log.debug("  → strategy=%s (%s) [%d tools, %d advisor]", strat.label, strat.confidence, tc, adv)

    total_latency = int((time.monotonic() - t0_post) * 1000)

    return AgentResult(
        ig_media_id=ig_media_id,
        category=cat,
        visual_format=vf,
        strategy=strat,
        api_calls=all_api_calls,
        advisor_calls=total_advisor,
        tool_calls=total_tools,
        trace=all_trace,
        latency_ms=total_latency,
        prompt_version_id=prompt_version_id,
    )
