"""Sélection de cibles et boucle de rewrite ProTeGi."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Callable

from milpo.bandits import successive_rejects
from milpo.db import (
    insert_prompt_version,
    promote_prompt,
    store_api_call,
    store_beam_candidate,
    store_gradient,
    store_rewrite_log,
    update_beam_candidate_eval,
    update_beam_candidate_sr,
)
from milpo.errors import LLMCallError
from milpo.eval import accuracy
from milpo.prompting import build_target_descriptions
from milpo.rewriter import ErrorCase, ProtegiStepResult, protegi_step
from milpo.simulation.evaluation import async_multi_evaluate
from milpo.simulation.state import ProtegiArm, PromptState, RewriteOutcome

log = logging.getLogger("simulation")

INCUMBENT_ARM_ID = 0


def _align_candidate_arms(
    candidate_arms: dict[int, list[bool]],
) -> dict[int, list[bool]]:
    """Aligne les bras candidats pour SR : retire les vides, tronque au min."""
    non_empty = {aid: m for aid, m in candidate_arms.items() if m}
    if not non_empty:
        return {}
    min_len = min(len(m) for m in non_empty.values())
    return {aid: m[:min_len] for aid, m in non_empty.items()}


def pick_rewrite_target(
    error_buffer: list[ErrorCase],
    per_slot_failures: dict[tuple[str, str | None], int] | None = None,
    slot_cooldown: int = 2,
) -> tuple[str, str | None]:
    """Choisit (agent, scope) avec le plus d'erreurs dans le buffer.

    per_slot_failures : compteur d'échecs consécutifs par slot.
    slot_cooldown : nombre d'échecs avant de skip un slot.
    """
    counts: Counter[tuple[str, str | None]] = Counter()
    grouped_by_post: dict[tuple[int, str], list[ErrorCase]] = defaultdict(list)

    for error in error_buffer:
        counts[(error.axis, error.prompt_scope)] += 1
        grouped_by_post[(error.ig_media_id, error.post_scope)].append(error)

    # Chaque post avec ≥1 erreur vote pour le descripteur (pondéré par nb d'erreurs)
    for (_, scope), grouped_errors in grouped_by_post.items():
        counts[("descriptor", scope)] += len(grouped_errors)

    # Skip les slots en cooldown (trop d'échecs consécutifs)
    if per_slot_failures:
        for slot, n_fails in per_slot_failures.items():
            if n_fails >= slot_cooldown and slot in counts:
                del counts[slot]

    if not counts:
        return error_buffer[0].axis, error_buffer[0].prompt_scope

    return counts.most_common(1)[0][0]


def get_target_errors(
    error_buffer: list[ErrorCase],
    target_agent: str,
    target_scope: str | None,
) -> list[ErrorCase]:
    """Filtre les erreurs pertinentes pour la cible du rewrite."""
    if target_agent != "descriptor":
        return [
            error for error in error_buffer
            if error.axis == target_agent and error.prompt_scope == target_scope
        ]

    return [
        error for error in error_buffer
        if error.post_scope == target_scope
    ]


def _persist_protegi_artifacts(
    conn,
    *,
    run_id: int,
    iteration: int,
    target_agent: str,
    target_scope: str | None,
    incumbent_db_id: int,
    incumbent_version: int,
    step_result: ProtegiStepResult,
    p: int,
) -> tuple[int, list[ProtegiArm]]:
    """Persiste le gradient et matérialise les candidats ProTeGi."""
    gradient_id = store_gradient(
        conn,
        simulation_run_id=run_id,
        iteration=iteration,
        target_agent=target_agent,
        target_scope=target_scope,
        prompt_id=incumbent_db_id,
        gradient_text=step_result.gradient.gradient_text,
        n_critiques=step_result.gradient.n_critiques,
        model=step_result.gradient.model,
        input_tokens=step_result.gradient.input_tokens,
        output_tokens=step_result.gradient.output_tokens,
        latency_ms=step_result.gradient.latency_ms,
    )

    # Query max version in DB to avoid collisions after a timed-out rewrite
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS max_v FROM prompt_versions "
        "WHERE simulation_run_id = %s AND agent = %s AND scope IS NOT DISTINCT FROM %s",
        (run_id, target_agent, target_scope),
    ).fetchone()
    next_version = max(row["max_v"] + 1, incumbent_version + 1)
    edit_arms: list[ProtegiArm] = []
    for index, candidate in enumerate(step_result.edit.candidates):
        edit_version = next_version + index
        edit_id = insert_prompt_version(
            conn,
            target_agent,
            target_scope,
            edit_version,
            candidate.new_instructions,
            status="draft",
            parent_id=incumbent_db_id,
            simulation_run_id=run_id,
        )
        beam_row = store_beam_candidate(
            conn,
            simulation_run_id=run_id,
            iteration=iteration,
            target_agent=target_agent,
            target_scope=target_scope,
            parent_prompt_id=incumbent_db_id,
            candidate_prompt_id=edit_id,
            gradient_id=gradient_id,
            generation_kind="edit",
        )
        edit_arms.append(ProtegiArm(
            beam_row_id=beam_row,
            prompt_db_id=edit_id,
            version=edit_version,
            kind="edit",
            instructions=candidate.new_instructions,
        ))

    if p >= 2 and step_result.paraphrases:
        para_arms: list[ProtegiArm] = []
        para_offset = next_version + len(edit_arms)
        idx = 0
        for edit_index, paraphrase_result in enumerate(step_result.paraphrases):
            edit = edit_arms[edit_index]
            for paraphrase_text in paraphrase_result.paraphrases:
                version = para_offset + idx
                prompt_id = insert_prompt_version(
                    conn,
                    target_agent,
                    target_scope,
                    version,
                    paraphrase_text,
                    status="draft",
                    parent_id=edit.prompt_db_id,
                    simulation_run_id=run_id,
                )
                beam_row = store_beam_candidate(
                    conn,
                    simulation_run_id=run_id,
                    iteration=iteration,
                    target_agent=target_agent,
                    target_scope=target_scope,
                    parent_prompt_id=edit.prompt_db_id,
                    candidate_prompt_id=prompt_id,
                    gradient_id=gradient_id,
                    generation_kind="paraphrase",
                )
                para_arms.append(ProtegiArm(
                    beam_row_id=beam_row,
                    prompt_db_id=prompt_id,
                    version=version,
                    kind="paraphrase",
                    instructions=paraphrase_text,
                ))
                idx += 1
        return gradient_id, para_arms

    return gradient_id, edit_arms


async def run_protegi_rewrite(
    args,
    conn,
    run_id: int,
    rewrite_count: int,
    target_agent: str,
    target_scope: str | None,
    target_errors: list[ErrorCase],
    prompt_state: PromptState,
    eval_posts,
    eval_start_cursor: int,
    annotations: dict[int, dict],
    labels_by_scope: dict[str, dict[str, list[str]]],
    on_status: Callable[[str], None] | None = None,
) -> RewriteOutcome:
    """Boucle ProTeGi complète : gradient + edit + paraphrase + SR + promotion."""
    current_key = (target_agent, target_scope)
    incumbent_db_id = prompt_state.db_ids[current_key]
    incumbent_version = prompt_state.versions[current_key]
    incumbent_instructions = prompt_state.instructions[current_key]
    all_descs = build_target_descriptions(conn, target_agent, target_scope)

    log.info(
        "[REWRITE #%d] (protegi) gradient → edit → %s eval × %d posts",
        rewrite_count,
        "paraphrase →" if args.protegi_p >= 2 else "(skip paraphrase) →",
        len(eval_posts),
    )

    try:
        step_result = await asyncio.to_thread(
            protegi_step,
            target_agent=target_agent,
            target_scope=target_scope,
            current_instructions=incumbent_instructions,
            errors=target_errors,
            all_descriptions=all_descs,
            m=args.protegi_m,
            c=args.protegi_c,
            p=args.protegi_p,
            on_phase=on_status,
        )
    except Exception as exc:
        log.warning(
            "[REWRITE #%d] (protegi) Échec %s/%s : %s",
            rewrite_count,
            target_agent,
            target_scope or "all",
            exc,
        )
        return RewriteOutcome(
            triggered=True,
            promoted=False,
            winner_db_id=None,
            incumbent_acc=None,
            candidate_acc=None,
            eval_window_consumed=0,
            incumbent_records=[],
            failed=True,
        )

    store_api_call(
        conn,
        "rewrite",
        target_agent,
        step_result.gradient.model,
        incumbent_db_id,
        None,
        step_result.gradient.input_tokens,
        step_result.gradient.output_tokens,
        None,
        step_result.gradient.latency_ms,
        run_id,
    )
    store_api_call(
        conn,
        "rewrite",
        target_agent,
        step_result.edit.model,
        incumbent_db_id,
        None,
        step_result.edit.input_tokens,
        step_result.edit.output_tokens,
        None,
        step_result.edit.latency_ms,
        run_id,
    )
    for paraphrase in step_result.paraphrases:
        store_api_call(
            conn,
            "rewrite",
            target_agent,
            paraphrase.model,
            incumbent_db_id,
            None,
            paraphrase.input_tokens,
            paraphrase.output_tokens,
            None,
            paraphrase.latency_ms,
            run_id,
        )

    gradient_id, arms_to_eval = _persist_protegi_artifacts(
        conn,
        run_id=run_id,
        iteration=rewrite_count,
        target_agent=target_agent,
        target_scope=target_scope,
        incumbent_db_id=incumbent_db_id,
        incumbent_version=incumbent_version,
        step_result=step_result,
        p=args.protegi_p,
    )

    if not arms_to_eval:
        log.warning("[REWRITE #%d] (protegi) aucun candidat à évaluer.", rewrite_count)
        return RewriteOutcome(
            triggered=True,
            promoted=False,
            winner_db_id=None,
            incumbent_acc=None,
            candidate_acc=None,
            eval_window_consumed=0,
            incumbent_records=[],
            failed=True,
        )

    arms: dict[int, tuple[str, int]] = {
        INCUMBENT_ARM_ID: (incumbent_instructions, incumbent_db_id),
    }
    for arm in arms_to_eval:
        arms[arm.beam_row_id] = (arm.instructions, arm.prompt_db_id)

    # Pour les rewrites descripteur, identifier l'axe principal (le plus erroné)
    # afin d'évaluer le delta de promotion sur cet axe seul au lieu de moyenner
    # les 3 axes (ce qui dilue un gain réel).
    primary_axis: str | None = None
    if target_agent == "descriptor":
        axis_counts = Counter(e.axis for e in target_errors)
        primary_axis = axis_counts.most_common(1)[0][0]
        log.info("[REWRITE #%d] descripteur → métrique de promotion sur %s", rewrite_count, primary_axis)

    if on_status:
        on_status(f"eval {len(arms)} bras × {len(eval_posts)} posts...")

    def _on_eval_progress(done: int, total: int):
        if on_status:
            on_status(f"eval {done}/{total}")

    try:
        multi_result = await asyncio.wait_for(
            async_multi_evaluate(
                eval_posts=eval_posts,
                annotations=annotations,
                start_cursor=eval_start_cursor,
                base_prompt_state=prompt_state,
                target_agent=target_agent,
                target_scope=target_scope,
                arms=arms,
                incumbent_arm_id=INCUMBENT_ARM_ID,
                conn=conn,
                run_id=run_id,
                labels_by_scope=labels_by_scope,
                on_progress=_on_eval_progress,
                primary_axis=primary_axis,
            ),
            timeout=600,
        )
    except (LLMCallError, asyncio.TimeoutError) as exc:
        log.warning("[REWRITE #%d] (protegi) Échec multi_evaluate : %s", rewrite_count, exc)
        return RewriteOutcome(
            triggered=True,
            promoted=False,
            winner_db_id=None,
            incumbent_acc=None,
            candidate_acc=None,
            eval_window_consumed=0,
            incumbent_records=[],
            failed=True,
        )

    inc_acc = accuracy(multi_result.matches_by_arm[INCUMBENT_ARM_ID])
    candidate_arms = {
        arm_id: matches
        for arm_id, matches in multi_result.matches_by_arm.items()
        if arm_id != INCUMBENT_ARM_ID
    }
    for beam_row_id, matches in candidate_arms.items():
        update_beam_candidate_eval(
            conn,
            candidate_row_id=beam_row_id,
            eval_accuracy=accuracy(matches),
            eval_sample_size=len(matches),
        )

    if not candidate_arms:
        log.warning("[REWRITE #%d] (protegi) aucun bras candidat évaluable.", rewrite_count)
        return RewriteOutcome(
            triggered=True,
            promoted=False,
            winner_db_id=None,
            incumbent_acc=inc_acc,
            candidate_acc=None,
            eval_window_consumed=len(eval_posts),
            incumbent_records=multi_result.incumbent_records,
            failed=False,
        )

    candidate_arms = _align_candidate_arms(candidate_arms)
    if not candidate_arms:
        log.warning("[REWRITE #%d] (protegi) aucun bras avec résultats après alignement.", rewrite_count)
        return RewriteOutcome(
            triggered=True,
            promoted=False,
            winner_db_id=None,
            incumbent_acc=inc_acc,
            candidate_acc=None,
            eval_window_consumed=len(eval_posts),
            incumbent_records=multi_result.incumbent_records,
            failed=False,
        )

    if on_status:
        on_status("bandit SR...")
    sr_result = successive_rejects(candidate_arms, k=1)
    winner_beam_row_id = sr_result.winner_arm_id
    winner_acc = sr_result.winner_score
    winner_db_id = arms[winner_beam_row_id][1]

    for phase in sr_result.phases:
        update_beam_candidate_sr(
            conn,
            candidate_row_id=phase.eliminated_arm_id,
            sr_phase=phase.phase,
            sr_eliminated=True,
            is_winner=False,
        )
    update_beam_candidate_sr(
        conn,
        candidate_row_id=winner_beam_row_id,
        sr_phase=None,
        sr_eliminated=False,
        is_winner=True,
    )

    promoted = winner_acc > inc_acc + args.delta

    store_rewrite_log(
        conn,
        prompt_before_id=incumbent_db_id,
        prompt_after_id=winner_db_id,
        error_batch=[{
            "axis": error.axis,
            "predicted": error.predicted,
            "expected": error.expected,
            "ig_media_id": error.ig_media_id,
            "post_scope": error.post_scope,
        } for error in target_errors],
        rewriter_reasoning=(
            f"[protegi] gradient_id={gradient_id} "
            f"({step_result.gradient.n_critiques} critiques) | "
            f"{len(arms_to_eval)} candidats évalués, SR winner = beam_row_id={winner_beam_row_id}"
        ),
        accepted=promoted,
        simulation_run_id=run_id,
        target_agent=target_agent,
        target_scope=target_scope,
        incumbent_accuracy=inc_acc,
        candidate_accuracy=winner_acc,
        eval_sample_size=len(eval_posts),
        iteration=rewrite_count,
    )

    if promoted:
        promote_prompt(conn, target_agent, target_scope, winner_db_id)
        new_version = next(
            (arm.version for arm in arms_to_eval if arm.beam_row_id == winner_beam_row_id),
            incumbent_version + 1,
        )
        prompt_state.instructions[current_key] = arms[winner_beam_row_id][0]
        prompt_state.db_ids[current_key] = winner_db_id
        prompt_state.versions[current_key] = new_version

    return RewriteOutcome(
        triggered=True,
        promoted=promoted,
        winner_db_id=winner_db_id,
        incumbent_acc=inc_acc,
        candidate_acc=winner_acc,
        eval_window_consumed=len(eval_posts),
        incumbent_records=multi_result.incumbent_records,
        failed=False,
    )
