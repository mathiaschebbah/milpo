"""Workflow de simulation MILPO prequential."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import warnings

from rich.console import Console
from rich.live import Live

from milpo.async_inference import async_classify_batch, set_api_call_hook
from milpo.config import MODEL_CRITIC, MODEL_EDITOR, MODEL_PARAPHRASER
from milpo.db import (
    get_conn,
    load_dev_annotations,
    load_dev_posts,
    load_post_media,
    load_posts_media,
)
from milpo.gcs import sign_all_posts_media
from milpo.inference import PostInput
from milpo.persistence import create_run, fail_run, finish_run
from milpo.prompting import build_labels, build_prompt_set
from milpo.rewriter import ErrorCase, set_rewriter_api_hook
from milpo.simulation.display import SimulationDisplay
from milpo.simulation.evaluation import evaluate_result_and_store
from milpo.simulation.rewrite import get_target_errors, pick_rewrite_target, run_protegi_rewrite
from milpo.simulation.state import RewriteOutcome, build_run_metrics, load_prompt_state_from_db
from milpo.simulation.telemetry import (
    emit_init_status,
    emit_telemetry,
    init_telemetry,
    reset_init_telemetry,
)

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("milpo").setLevel(logging.WARNING)
log = logging.getLogger("simulation")

MICRO_BATCH_SIZE = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulation MILPO prequential — boucle ProTeGi (Pryzant et al. 2023)",
    )
    parser.add_argument("-B", "--batch-size", type=int, default=30)
    parser.add_argument("--delta", type=float, default=0.0)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--eval-window", type=int, default=60)
    parser.add_argument("--split", choices=["dev", "test"], default="dev", help="Split à utiliser (défaut dev)")
    parser.add_argument("--dry-run", action="store_true", help="Pas de rewrite (B0-on-dev)")
    parser.add_argument("--no-rollback", action="store_true", help="Ablation A5")
    parser.add_argument("--limit", type=int, default=None, help="Nombre de posts max")
    parser.add_argument(
        "--micro-batch",
        type=int,
        default=MICRO_BATCH_SIZE,
        help="Posts classifiés en parallèle (défaut 10)",
    )
    parser.add_argument(
        "-m",
        "--protegi-m",
        type=int,
        default=3,
        help="critiques par appel critic LLM_∇ (paper m=4, défaut 3)",
    )
    parser.add_argument(
        "-c",
        "--protegi-c",
        type=int,
        default=4,
        help="candidats édités par appel editor LLM_δ (paper c=8, défaut 4)",
    )
    parser.add_argument(
        "-p",
        "--protegi-p",
        type=int,
        default=1,
        help="paraphrases par candidat LLM_mc (paper p=2, défaut 1 = skip étape MC)",
    )
    parser.add_argument(
        "--protegi-paper-defaults",
        action="store_true",
        help="Convenience : applique m=4 c=8 p=2 (hyperparams paper Pryzant et al.)",
    )
    parser.add_argument(
        "--sgd",
        action="store_true",
        help="Mode SGD : évalue les candidats sur le batch d'erreurs (pas d'eval window séparée)",
    )
    return parser


async def run_simulation(args) -> int:
    if args.protegi_paper_defaults:
        args.protegi_m, args.protegi_c, args.protegi_p = 4, 8, 2
        log.info("[PROTEGI] paper defaults appliqués : m=4 c=8 p=2")
    if args.sgd and args.batch_size == 30:
        args.batch_size = 10
        log.info("[SGD] batch_size réduit à 10 (mode SGD)")

    conn = get_conn()
    run_id: int | None = None
    t0 = time.monotonic()
    matches_by_axis = {"category": 0, "visual_format": 0, "strategy": 0}
    n_processed = 0
    total_api_calls = 0
    live_cost_estimate_usd = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    matches_by_scope = {
        "FEED": {"category": 0, "visual_format": 0, "strategy": 0},
        "REELS": {"category": 0, "visual_format": 0, "strategy": 0},
    }
    n_by_scope = {"FEED": 0, "REELS": 0}
    rewrite_count = 0
    promoted_rewrite_count = 0
    rollback_rewrite_count = 0
    skipped_rewrite_count = 0
    skipped_classification_posts = 0
    failed_rewrite_attempts = 0

    init_telemetry()
    reset_init_telemetry()

    warnings.filterwarnings("ignore")
    logging.getLogger().setLevel(logging.ERROR)
    emit_init_status("loading posts & annotations...", stage="bootstrap")

    try:
        raw_posts = load_dev_posts(conn, limit=args.limit, split=args.split)
        annotations = load_dev_annotations(conn, split=args.split)
        annotated_ids = set(annotations.keys())
        raw_posts = [post for post in raw_posts if post["ig_media_id"] in annotated_ids]
        if not raw_posts:
            console.print(f"[red]Aucun post annoté dans le split {args.split}.[/red]")
            sys.exit(1)

        run_config = {
            "name": f"MILPO_protegi_B{args.batch_size}" + ("_dryrun" if args.dry_run else ""),
            "split": args.split,
            "batch_size": args.batch_size,
            "delta": args.delta,
            "patience": args.patience,
            "eval_window": args.eval_window,
            "dry_run": args.dry_run,
            "no_rollback": args.no_rollback,
            "sgd": args.sgd,
            "protegi": {
                "m": args.protegi_m,
                "c": args.protegi_c,
                "p": args.protegi_p,
                "critic_model": MODEL_CRITIC,
                "editor_model": MODEL_EDITOR,
                "paraphraser_model": MODEL_PARAPHRASER,
            },
        }
        run_id = create_run(conn, run_config)

        def _on_sign_progress(phase: str, done: int, total: int):
            if phase == "loading_media":
                emit_init_status(
                    f"loading media from DB ({done}/{total} posts)...",
                    stage="loading_media",
                    done=done,
                    total=total,
                    unit="posts",
                )
            elif phase == "collecting_urls":
                emit_init_status(
                    f"collected {done} unique media URLs...",
                    stage="collecting_urls",
                    done=done,
                    total=total,
                    unit="urls",
                )
            else:
                emit_init_status(
                    f"signing GCS URLs ({done}/{total})...",
                    stage="signing",
                    done=done,
                    total=total,
                    unit="urls",
                )

        emit_init_status(
            f"loading media from DB (0/{len(raw_posts)} posts)...",
            stage="loading_media",
            done=0,
            total=len(raw_posts),
            unit="posts",
        )
        signed_by_post = sign_all_posts_media(
            raw_posts,
            load_post_media,
            conn,
            max_workers=20,
            load_all_media_fn=load_posts_media,
            on_progress=_on_sign_progress,
        )

        post_inputs: list[PostInput] = []
        for post in raw_posts:
            signed = signed_by_post.get(post["ig_media_id"], [])
            if not signed:
                continue
            post_inputs.append(PostInput(
                ig_media_id=post["ig_media_id"],
                media_product_type=post["media_product_type"],
                media_urls=[url for url, _ in signed],
                media_types=[media_type for _, media_type in signed],
                caption=post["caption"],
            ))

        post_by_id = {p.ig_media_id: p for p in post_inputs}

        prompt_state = load_prompt_state_from_db(conn, logger=log)
        labels_by_scope = {scope: build_labels(conn, scope) for scope in ("FEED", "REELS")}

        error_buffer: list[ErrorCase] = []
        all_matches = []
        cursor = 0
        consecutive_failures = 0
        rewrites_stopped = False
        per_slot_failures: dict[tuple[str, str | None], int] = {}

        total = len(post_inputs)
        feed = sum(1 for post in post_inputs if post.media_product_type == "FEED")
        display = SimulationDisplay(run_id=run_id, total=total, batch_size=args.batch_size)

        def _on_api(agent, model, latency_ms, in_tok, out_tok, status):
            display.add_api_log(agent, model, latency_ms, in_tok, out_tok, status)
            emit_telemetry(display)

        set_api_call_hook(_on_api)
        set_rewriter_api_hook(_on_api)
        display.add_event(f"Loaded {total} posts (FEED {feed} / REELS {total - feed})")
        display.add_event(
            f"Config B={args.batch_size} delta={args.delta*100:.0f}% "
            f"patience={args.patience} m={args.protegi_m} c={args.protegi_c} p={args.protegi_p}"
        )
        display.heartbeat("ready to classify")
        display.sync(cursor, n_processed, matches_by_axis, len(error_buffer), live_cost_estimate_usd, prompt_state.versions)
        display.total_input_tokens = total_input_tokens
        display.total_output_tokens = total_output_tokens
        display.matches_by_scope = matches_by_scope
        display.n_by_scope = n_by_scope
        emit_telemetry(display)

        post_timeout = 120
        with Live(display.build(), refresh_per_second=2, console=console, screen=True) as live:
            async def _with_heartbeat(coro):
                """Run a coroutine with periodic 2s display refresh (no heartbeat reset)."""
                task = asyncio.ensure_future(coro)
                try:
                    while not task.done():
                        done_set, _ = await asyncio.wait({task}, timeout=2)
                        if done_set:
                            return task.result()
                        live.update(display.build())
                        emit_telemetry(display)
                    return task.result()
                except asyncio.CancelledError:
                    task.cancel()
                    raise

            while cursor < total:
                prompts_by_scope = {
                    scope: build_prompt_set(conn, scope, prompt_state.instructions)
                    for scope in ("FEED", "REELS")
                }
                batch_end = min(cursor + args.micro_batch, total)
                micro_batch = post_inputs[cursor:batch_end]

                display.heartbeat("classifying batch")

                def _on_post_done(done: int, total_batch: int, errors: int):
                    display.heartbeat(f"post {cursor + done}/{total}")
                    live.update(display.build())
                    emit_telemetry(display)

                batch_results = await async_classify_batch(
                    posts=micro_batch,
                    prompts_by_scope=prompts_by_scope,
                    labels_by_scope=labels_by_scope,
                    max_concurrent_api=20,
                    max_concurrent_posts=args.micro_batch,
                    on_progress=_on_post_done,
                    per_post_timeout=post_timeout,
                )
                skipped_in_batch = len(micro_batch) - len(batch_results)
                if skipped_in_batch:
                    skipped_classification_posts += skipped_in_batch

                results_by_id = {result.prediction.ig_media_id: result for result in batch_results}
                batch_cursor = cursor
                batch_skipped = 0
                for post in micro_batch:
                    result = results_by_id.get(post.ig_media_id)
                    if result is None:
                        skipped_classification_posts += 1
                        batch_skipped += 1
                        batch_cursor += 1
                        continue

                    try:
                        errors, matches = evaluate_result_and_store(
                            post,
                            result,
                            annotations[post.ig_media_id],
                            prompt_state,
                            conn,
                            run_id,
                        )
                    except Exception as exc:
                        log.warning("evaluate_result_and_store échoué post %s: %s", post.ig_media_id, exc)
                        skipped_classification_posts += 1
                        batch_skipped += 1
                        batch_cursor += 1
                        continue

                    for match_record in matches:
                        match_record.cursor = batch_cursor
                        all_matches.append(match_record)
                        if match_record.match:
                            matches_by_axis[match_record.axis] += 1
                            if match_record.scope:
                                matches_by_scope[match_record.scope][match_record.axis] += 1

                    error_buffer.extend(errors)
                    n_processed += 1
                    n_by_scope[post.media_product_type] += 1
                    total_api_calls += len(result.api_calls)
                    total_input_tokens += result.total_input_tokens
                    total_output_tokens += result.total_output_tokens
                    live_cost_estimate_usd += sum(
                        call.input_tokens * 0.0001 / 1000 + call.output_tokens * 0.0003 / 1000
                        for call in result.api_calls
                    )
                    batch_cursor += 1

                cursor = batch_cursor
                if batch_skipped:
                    display.skipped = skipped_classification_posts
                    display.add_event(f"{batch_skipped} post(s) skipped (LLM error)")

                display.heartbeat(f"batch done {cursor}/{total}")
                display.sync(cursor, n_processed, matches_by_axis, len(error_buffer), live_cost_estimate_usd, prompt_state.versions)
                display.total_input_tokens = total_input_tokens
                display.total_output_tokens = total_output_tokens
                display.matches_by_scope = matches_by_scope
                display.n_by_scope = n_by_scope
                display.update_rolling(all_matches)
                live.update(display.build())
                emit_telemetry(display)

                if not args.dry_run and not rewrites_stopped and len(error_buffer) >= args.batch_size:
                    target_agent, target_scope = pick_rewrite_target(error_buffer, per_slot_failures)
                    target_errors = get_target_errors(error_buffer, target_agent, target_scope)

                    if not target_errors:
                        display.add_event(f"No exploitable errors for {target_agent}/{target_scope or 'all'}")
                        error_buffer.clear()
                        live.update(display.build())
                        emit_telemetry(display)
                        continue

                    if args.sgd:
                        # Mode SGD : évaluer sur les posts du batch d'erreurs
                        error_ids = list(dict.fromkeys(e.ig_media_id for e in target_errors))
                        eval_posts = [post_by_id[pid] for pid in error_ids if pid in post_by_id]
                    else:
                        ew = 20 if target_agent == "descriptor" else args.eval_window
                        eval_end = min(cursor + ew, total)
                        eval_posts = post_inputs[cursor:eval_end]
                    if len(eval_posts) < 3:
                        skipped_rewrite_count += 1
                        display.add_event(f"Rewrite skipped (only {len(eval_posts)} posts for eval)")
                        error_buffer.clear()
                        live.update(display.build())
                        emit_telemetry(display)
                        continue

                    rewrite_count += 1
                    display.phase = f"rewrite #{rewrite_count} — {target_agent}/{target_scope or 'all'}"
                    display.add_event(
                        f"REWRITE #{rewrite_count} triggered — {target_agent}/{target_scope or 'all'} "
                        f"({len(target_errors)} errors)"
                    )
                    live.update(display.build())
                    emit_telemetry(display)

                    def _on_rewrite_status(msg: str):
                        display.set_rewrite_phase(msg)
                        display.heartbeat(msg[:30])

                    # Descripteur : c=2 (moins de candidats, chaque eval est 4x plus chère)
                    saved_c = args.protegi_c
                    if target_agent == "descriptor":
                        args.protegi_c = min(args.protegi_c, 2)

                    try:
                        outcome = await asyncio.wait_for(
                            _with_heartbeat(run_protegi_rewrite(
                                args,
                                conn,
                                run_id,
                                rewrite_count,
                                target_agent,
                                target_scope,
                                target_errors,
                                prompt_state,
                                eval_posts,
                                cursor,
                                annotations,
                                labels_by_scope,
                                on_status=_on_rewrite_status,
                            )),
                            timeout=600,
                        )
                    except asyncio.TimeoutError:
                        display.add_event(f"REWRITE #{rewrite_count} TIMEOUT (600s)")
                        outcome = RewriteOutcome(
                            triggered=True,
                            promoted=False,
                            winner_db_id=None,
                            incumbent_acc=None,
                            candidate_acc=None,
                            eval_window_consumed=0,
                            incumbent_records=[],
                            failed=True,
                        )
                    except Exception as exc:
                        log.warning("REWRITE #%d crash: %s", rewrite_count, exc)
                        display.add_event(f"REWRITE #{rewrite_count} CRASH: {exc}", event_type="error")
                        outcome = RewriteOutcome(
                            triggered=True,
                            promoted=False,
                            winner_db_id=None,
                            incumbent_acc=None,
                            candidate_acc=None,
                            eval_window_consumed=0,
                            incumbent_records=[],
                            failed=True,
                        )

                    rewrite_slot = (target_agent, target_scope)
                    if outcome.failed:
                        failed_rewrite_attempts += 1
                        consecutive_failures += 1
                        per_slot_failures[rewrite_slot] = per_slot_failures.get(rewrite_slot, 0) + 1
                        display.add_event(f"REWRITE #{rewrite_count} FAILED")
                        error_buffer.clear()
                    else:
                        if outcome.promoted:
                            promoted_rewrite_count += 1
                            consecutive_failures = 0
                            per_slot_failures[rewrite_slot] = 0
                            delta = (outcome.candidate_acc - outcome.incumbent_acc) * 100
                            display.add_event(
                                f"REWRITE #{rewrite_count} PROMOTED "
                                f"({outcome.incumbent_acc*100:.1f}% -> {outcome.candidate_acc*100:.1f}%, +{delta:.1f}%)"
                            )
                        else:
                            rollback_rewrite_count += 1
                            consecutive_failures += 1
                            per_slot_failures[rewrite_slot] = per_slot_failures.get(rewrite_slot, 0) + 1
                            delta = (outcome.candidate_acc - outcome.incumbent_acc) * 100
                            display.add_event(
                                f"REWRITE #{rewrite_count} ROLLBACK "
                                f"({outcome.incumbent_acc*100:.1f}% vs {outcome.candidate_acc*100:.1f}%, {delta:+.1f}%)"
                            )

                        if not args.sgd:
                            # Mode classique : les eval_posts sont des posts futurs,
                            # on les compte dans les métriques globales et on avance le cursor
                            for match_record in outcome.incumbent_records:
                                all_matches.append(match_record)
                                if match_record.match:
                                    matches_by_axis[match_record.axis] += 1

                            rewrite_scope_posts: dict[str, int] = {}
                            for match_record in outcome.incumbent_records:
                                if match_record.scope:
                                    if match_record.match:
                                        matches_by_scope[match_record.scope][match_record.axis] += 1
                                    rewrite_scope_posts[match_record.scope] = rewrite_scope_posts.get(match_record.scope, 0) + 1
                            for scope, count in rewrite_scope_posts.items():
                                n_by_scope[scope] += count // 3

                            n_processed += outcome.eval_window_consumed
                            cursor += outcome.eval_window_consumed

                        # SGD mode : pas d'avance du cursor, posts déjà comptés
                        n_arms = 1 + (
                            args.protegi_c if args.protegi_p < 2 else args.protegi_c * args.protegi_p
                        )
                        total_api_calls += outcome.eval_window_consumed * 4 * n_arms
                        error_buffer.clear()

                    args.protegi_c = saved_c
                    display.set_rewrite_phase(None)
                    display.phase = "classification"
                    display.rewrites_promoted = promoted_rewrite_count
                    display.rewrites_rollback = rollback_rewrite_count
                    display.sync(cursor, n_processed, matches_by_axis, len(error_buffer), live_cost_estimate_usd, prompt_state.versions)
                    display.total_input_tokens = total_input_tokens
                    display.total_output_tokens = total_output_tokens
                    display.matches_by_scope = matches_by_scope
                    display.n_by_scope = n_by_scope
                    live.update(display.build())
                    emit_telemetry(display)

                    if consecutive_failures >= args.patience:
                        display.add_event(f"Patience exhausted ({consecutive_failures}/{args.patience})")
                        live.update(display.build())
                        emit_telemetry(display)
                        rewrites_stopped = True

        logging.getLogger().setLevel(logging.INFO)
        log.setLevel(logging.INFO)

        metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
        finish_run(conn, run_id, metrics)

        elapsed = time.monotonic() - t0
        log.info("")
        log.info("=" * 60)
        log.info("  RÉSULTATS SIMULATION MILPO")
        log.info("=" * 60)
        log.info("  Posts scorés   : %d", n_processed)
        log.info("  Posts ignorés  : %d (échec LLM après retries)", skipped_classification_posts)
        log.info("  Appels API     : %d", total_api_calls)
        log.info("  Durée          : %.0fs (%.1f min)", elapsed, elapsed / 60)
        log.info("  Coût live est. : ~$%.2f (monitoring only, non reporté)", live_cost_estimate_usd)
        log.info("")
        log.info("  Prompts finaux :")
        for (agent, scope), version in sorted(prompt_state.versions.items()):
            log.info("    %s/%s : v%d", agent, scope or "all", version)
        log.info("")
        log.info(
            "  Rewrites       : %d tentés, %d promus, %d rollback, %d erreurs rewriter, %d skip eval",
            rewrite_count,
            promoted_rewrite_count,
            rollback_rewrite_count,
            failed_rewrite_attempts,
            skipped_rewrite_count,
        )
        log.info("")
        log.info("  Accuracy (tout le %s scoré) :", args.split)
        log.info("    Catégorie      : %.1f%% (%d/%d)", metrics["accuracy_category"] * 100, matches_by_axis["category"], n_processed)
        log.info("    Visual_format  : %.1f%% (%d/%d)", metrics["accuracy_visual_format"] * 100, matches_by_axis["visual_format"], n_processed)
        log.info("    Stratégie      : %.1f%% (%d/%d)", metrics["accuracy_strategy"] * 100, matches_by_axis["strategy"], n_processed)
        log.info("")
        log.info("  simulation_run_id = %d", run_id)
        log.info("✓ Simulation terminée")
        return run_id
    except (KeyboardInterrupt, SystemExit):
        log.info("Simulation interrompue par l'utilisateur (run_id=%s)", run_id)
        if run_id is not None:
            try:
                conn.rollback()
                metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
                fail_run(conn, run_id, "interrupted", metrics)
            except Exception as db_exc:
                log.warning("fail_run échoué: %s", db_exc)
        sys.exit(1)
    except Exception as exc:
        print()
        log.setLevel(logging.INFO)
        log.exception("[FATAL] Simulation interrompue: %s", exc)
        if run_id is not None:
            try:
                conn.rollback()
                metrics = build_run_metrics(matches_by_axis, n_processed, rewrite_count, total_api_calls)
                fail_run(conn, run_id, str(exc), metrics)
            except Exception as db_exc:
                log.warning("fail_run échoué: %s", db_exc)
            log.info("  simulation_run_id = %d", run_id)
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run_simulation(args))


__all__ = ["build_parser", "main", "run_simulation"]
