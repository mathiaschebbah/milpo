"""Évaluation des pipelines agentiques A1 bounded et A0 legacy."""

from __future__ import annotations

import argparse
import json
import logging
import queue
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from agents import pipeline as agent_pipeline
from agents.cli import TuiRenderer, TuiStats
from agents.config import MODEL_ADVISOR, MODEL_DESCRIPTOR, MODEL_EXECUTOR
from agents.pipeline import AgentResult, classify_post_agentic
from agents.tools import MediaContext
from milpo.db import (
    format_descriptions,
    get_active_prompt,
    get_conn,
    load_posts_media,
    load_post_media,
    load_visual_formats,
)
from milpo.gcs import sign_all_posts_media

warnings.filterwarnings("ignore", module=r"google\.auth")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)

log = logging.getLogger("agent_baseline")


ReporterStats = TuiStats  # backward compat alias


def create_run(conn, config: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO simulation_runs (seed, batch_size, config, status, started_at)
        VALUES (42, 0, %s::jsonb, 'running', NOW())
        RETURNING id
        """,
        (json.dumps(config),),
    ).fetchone()
    conn.commit()
    return row["id"]


def finish_run(conn, run_id: int, metrics: dict) -> None:
    conn.execute(
        """
        UPDATE simulation_runs SET
            status = 'completed', finished_at = NOW(),
            final_accuracy_category = %s,
            final_accuracy_visual_format = %s,
            final_accuracy_strategy = %s,
            total_api_calls = %s, total_cost_usd = %s
        WHERE id = %s
        """,
        (
            metrics["accuracy_category"],
            metrics["accuracy_visual_format"],
            metrics["accuracy_strategy"],
            metrics["total_api_calls"],
            metrics.get("total_cost_usd"),
            run_id,
        ),
    )
    conn.commit()


def fail_run(conn, run_id: int) -> None:
    conn.execute(
        "UPDATE simulation_runs SET status = 'failed', finished_at = NOW() WHERE id = %s",
        (run_id,),
    )
    conn.commit()




def store_agent_results(
    conn,
    result: AgentResult,
    run_id: int,
    pipeline_name: str,
) -> dict[str, bool]:
    matches: dict[str, bool] = {}

    tok_exec_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("executor/"))
    tok_exec_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("executor/"))
    tok_adv_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("advisor/"))
    tok_adv_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("advisor/"))
    tok_desc_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("tool/"))
    tok_desc_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("tool/"))
    trace_json = json.dumps([event.to_dict() for event in result.trace], ensure_ascii=False)

    with conn.transaction():
        for axis in ("category", "visual_format", "strategy"):
            classification = getattr(result, axis)
            row = conn.execute(
                """
                INSERT INTO predictions
                    (ig_media_id, agent, prompt_version_id, predicted_value, raw_response, simulation_run_id)
                VALUES (%s, %s::agent_type, %s, %s, %s::jsonb, %s)
                RETURNING match
                """,
                (
                    result.ig_media_id,
                    axis,
                    result.prompt_version_id,
                    classification.label,
                    json.dumps(
                        {
                            "confidence": classification.confidence,
                            "reasoning": classification.reasoning[-300:],
                            "pipeline": pipeline_name,
                        },
                        ensure_ascii=False,
                    ),
                    run_id,
                ),
            ).fetchone()
            matches[axis] = bool(row and row["match"])

        for call in result.api_calls:
            db_agent = "descriptor" if call.agent.startswith("tool/") else "agent_executor"
            conn.execute(
                """
                INSERT INTO api_calls
                    (call_type, agent, model_name, prompt_version_id, ig_media_id,
                     input_tokens, output_tokens, cost_usd, latency_ms, simulation_run_id)
                VALUES (%s, %s::agent_type, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "classification",
                    db_agent,
                    call.model,
                    None,
                    result.ig_media_id,
                    call.input_tokens,
                    call.output_tokens,
                    None,
                    call.latency_ms,
                    run_id,
                ),
            )

        conn.execute(
            """
            INSERT INTO agent_traces
                (simulation_run_id, ig_media_id,
                 tool_calls, advisor_calls,
                 input_tokens_executor, output_tokens_executor,
                 input_tokens_advisor, output_tokens_advisor,
                 input_tokens_descriptor, output_tokens_descriptor,
                 latency_ms,
                 category_label, category_confidence,
                 visual_format_label, visual_format_confidence,
                 strategy_label, strategy_confidence,
                 trace,
                 executor_requests, advisor_requests, example_calls, rate_limit_events,
                 queue_wait_ms_executor,
                 cache_creation_input_tokens_executor,
                 cache_read_input_tokens_executor)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (simulation_run_id, ig_media_id) DO UPDATE SET
                tool_calls = EXCLUDED.tool_calls,
                advisor_calls = EXCLUDED.advisor_calls,
                input_tokens_executor = EXCLUDED.input_tokens_executor,
                output_tokens_executor = EXCLUDED.output_tokens_executor,
                input_tokens_advisor = EXCLUDED.input_tokens_advisor,
                output_tokens_advisor = EXCLUDED.output_tokens_advisor,
                input_tokens_descriptor = EXCLUDED.input_tokens_descriptor,
                output_tokens_descriptor = EXCLUDED.output_tokens_descriptor,
                latency_ms = EXCLUDED.latency_ms,
                category_label = EXCLUDED.category_label,
                category_confidence = EXCLUDED.category_confidence,
                visual_format_label = EXCLUDED.visual_format_label,
                visual_format_confidence = EXCLUDED.visual_format_confidence,
                strategy_label = EXCLUDED.strategy_label,
                strategy_confidence = EXCLUDED.strategy_confidence,
                trace = EXCLUDED.trace,
                executor_requests = EXCLUDED.executor_requests,
                advisor_requests = EXCLUDED.advisor_requests,
                example_calls = EXCLUDED.example_calls,
                rate_limit_events = EXCLUDED.rate_limit_events,
                queue_wait_ms_executor = EXCLUDED.queue_wait_ms_executor,
                cache_creation_input_tokens_executor = EXCLUDED.cache_creation_input_tokens_executor,
                cache_read_input_tokens_executor = EXCLUDED.cache_read_input_tokens_executor
            """,
            (
                run_id,
                result.ig_media_id,
                result.tool_calls,
                result.advisor_calls,
                tok_exec_in,
                tok_exec_out,
                tok_adv_in,
                tok_adv_out,
                tok_desc_in,
                tok_desc_out,
                result.latency_ms,
                result.category.label,
                result.category.confidence,
                result.visual_format.label,
                result.visual_format.confidence,
                result.strategy.label,
                result.strategy.confidence,
                trace_json,
                result.executor_requests,
                result.advisor_requests,
                result.example_calls,
                result.rate_limit_events,
                result.queue_wait_ms_executor,
                result.cache_creation_input_tokens_executor,
                result.cache_read_input_tokens_executor,
            ),
        )

        for event in result.request_events:
            conn.execute(
                """
                INSERT INTO llm_request_events
                    (simulation_run_id, ig_media_id, provider, component, stage, attempt_index,
                     request_id, status, model_name,
                     estimated_input_tokens, actual_input_tokens, actual_output_tokens,
                     cache_creation_input_tokens, cache_read_input_tokens,
                     queue_wait_ms, latency_ms, retry_after_ms,
                     rate_limit_headers, error_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s)
                """,
                (
                    run_id,
                    result.ig_media_id,
                    event.provider,
                    event.component,
                    event.stage,
                    event.attempt_index,
                    event.request_id,
                    event.status,
                    event.model_name,
                    event.estimated_input_tokens,
                    event.actual_input_tokens,
                    event.actual_output_tokens,
                    event.cache_creation_input_tokens,
                    event.cache_read_input_tokens,
                    event.queue_wait_ms,
                    event.latency_ms,
                    event.retry_after_ms,
                    json.dumps(event.rate_limit_headers or {}, ensure_ascii=False),
                    event.error_code,
                ),
            )

    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Évalue la pipeline agentique sur le split test")
    parser.add_argument("--limit", type=int, default=None, help="Limiter à N posts (pour tests)")
    parser.add_argument("--workers", type=int, default=10, help="Nombre de posts en parallèle")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les posts sans classifier")
    parser.add_argument(
        "--pipeline-mode",
        choices=["bounded", "legacy"],
        default="bounded",
        help="bounded=A1 agentic bounded, legacy=A0 rollback",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Afficher les logs JSON détaillés de la pipeline")
    args = parser.parse_args()

    if not args.verbose:
        logging.getLogger("agents").setLevel(logging.WARNING)
        logging.getLogger("google.auth").setLevel(logging.WARNING)

    pipeline_name = "agent_a1_bounded" if args.pipeline_mode == "bounded" else "agent_a0"
    run_name = "A1_agentic_bounded_test" if args.pipeline_mode == "bounded" else "A0_agent_haiku_opus_test"

    conn = get_conn()
    t0 = time.monotonic()

    log.info("=" * 60)
    log.info("%s — Pipeline agentique", "A1 bounded" if args.pipeline_mode == "bounded" else "A0 legacy")
    log.info("=" * 60)
    log.info("  executor  : %s", MODEL_EXECUTOR)
    log.info("  advisor   : %s", MODEL_ADVISOR)
    log.info("  descriptor: %s", MODEL_DESCRIPTOR)
    log.info("  mode      : %s", args.pipeline_mode)

    query = """
        SELECT p.ig_media_id, p.caption,
               p.media_type::text AS media_type,
               p.media_product_type::text AS media_product_type,
               EXTRACT(YEAR FROM p.timestamp)::int AS post_year
        FROM sample_posts sp
        JOIN posts p ON p.ig_media_id = sp.ig_media_id
        WHERE sp.split = 'test'
        ORDER BY sp.presentation_order
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    raw_posts = conn.execute(query).fetchall()
    log.info("Posts test : %d", len(raw_posts))

    if args.dry_run:
        for post in raw_posts[:10]:
            log.info(
                "  %s %s %s (%d)",
                post["ig_media_id"],
                post["media_product_type"],
                (post["caption"] or "")[:50],
                post["post_year"],
            )
        log.info("Dry run — pas de classification.")
        conn.close()
        return

    run_id = create_run(
        conn,
        {
            "name": run_name,
            "split": "test",
            "pipeline": pipeline_name,
            "pipeline_mode": args.pipeline_mode,
            "models": {
                "executor": MODEL_EXECUTOR,
                "advisor": MODEL_ADVISOR,
                "descriptor": MODEL_DESCRIPTOR,
            },
        },
    )
    log.info("simulation_run id=%d", run_id)

    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(
        raw_posts,
        load_post_media,
        conn,
        max_workers=20,
        load_all_media_fn=load_posts_media,
    )

    desc_feed = get_active_prompt(conn, "descriptor", "FEED")
    desc_reels = get_active_prompt(conn, "descriptor", "REELS")
    if not desc_feed or not desc_reels:
        log.error("Prompts descripteur introuvables en BDD.")
        fail_run(conn, run_id)
        conn.close()
        sys.exit(1)

    vf_feed_desc = format_descriptions(load_visual_formats(conn, "FEED"))
    vf_reels_desc = format_descriptions(load_visual_formats(conn, "REELS"))

    stats = ReporterStats()
    lock = threading.Lock()
    stop_reporter = threading.Event()
    write_queue: queue.Queue[tuple[int, dict, AgentResult] | None] = queue.Queue()
    total = len(raw_posts)

    stats.total = total
    tui = TuiRenderer(
        stats=stats,
        lock=lock,
        limiter_snapshot_fn=agent_pipeline._rate_limiter.snapshot,
        run_id=run_id,
        pipeline=pipeline_name,
        t0=t0,
    )

    def _writer_loop() -> None:
        writer_conn = get_conn()
        batch: list[tuple[int, dict, AgentResult]] = []
        batch_started = time.monotonic()
        try:
            while True:
                timeout = max(0.0, 0.25 - (time.monotonic() - batch_started)) if batch else 0.25
                try:
                    item = write_queue.get(timeout=timeout)
                except queue.Empty:
                    item = None

                if item is None:
                    if batch:
                        _flush_batch(writer_conn, batch)
                        batch = []
                    batch_started = time.monotonic()
                    if stop_reporter.is_set():
                        break
                    continue

                batch.append(item)
                if len(batch) >= 10 or (time.monotonic() - batch_started) >= 0.25:
                    _flush_batch(writer_conn, batch)
                    batch = []
                    batch_started = time.monotonic()
        finally:
            writer_conn.close()

    def _flush_batch(writer_conn, items: list[tuple[int, dict, AgentResult]]) -> None:
        for idx, post, result in items:
            mid = post["ig_media_id"]
            try:
                post_matches = store_agent_results(writer_conn, result, run_id, pipeline_name)
            except Exception as exc:
                writer_conn.rollback()
                log.error("store error %s: %s", mid, exc)
                with lock:
                    stats.errors += 1
                continue

            with lock:
                stats.completed += 1
                stats.total_api_calls += len(result.api_calls)
                stats.total_advisor_calls += result.advisor_calls
                stats.total_tool_calls += result.tool_calls
                stats.total_executor_requests += result.executor_requests
                stats.total_executor_input_tokens += (
                    result.cache_creation_input_tokens_executor
                    + result.cache_read_input_tokens_executor
                    + sum(
                        event.actual_input_tokens
                        for event in result.request_events
                        if event.component == "executor" and event.status == "success"
                    )
                )
                stats.total_executor_cache_creation_tokens += result.cache_creation_input_tokens_executor
                stats.total_executor_cache_read_tokens += result.cache_read_input_tokens_executor
                stats.executor_successes += sum(
                    1 for event in result.request_events if event.component == "executor" and event.status == "success"
                )
                stats.executor_cache_hits += sum(
                    1
                    for event in result.request_events
                    if event.component == "executor"
                    and event.status == "success"
                    and event.cache_read_input_tokens > 0
                )
                stats.posts_with_advisor += 1 if result.advisor_calls > 0 else 0
                stats.latencies_ms.append(result.latency_ms)
                for axis in ("category", "visual_format", "strategy"):
                    if post_matches[axis]:
                        stats.matches[axis] += 1

    def _classify_one(idx: int, post: dict) -> tuple[int, dict, AgentResult | None]:
        mid = post["ig_media_id"]
        scope = post["media_product_type"]
        with lock:
            stats.started += 1
            stats.in_flight_posts += 1

        signed = signed_by_post.get(mid, [])
        if not signed:
            return idx, post, None

        media_urls = [url for url, _ in signed]
        media_types = [media_type for _, media_type in signed]
        desc_prompt = desc_feed if scope == "FEED" else desc_reels
        vf_desc = vf_feed_desc if scope == "FEED" else vf_reels_desc

        media_ctx = MediaContext(
            media_urls=media_urls,
            media_types=media_types,
            caption=post["caption"],
            scope=scope,
            post_year=post["post_year"],
            descriptor_instructions=desc_prompt["content"],
            descriptor_descriptions=vf_desc,
        )

        thread_conn = get_conn()
        try:
            result = classify_post_agentic(
                mid,
                media_ctx,
                thread_conn,
                pipeline_mode=args.pipeline_mode,
            )
            return idx, post, result
        except Exception as exc:
            log.error("[%d/%d] %s ERREUR: %s", idx, total, mid, exc)
            return idx, post, None
        finally:
            thread_conn.close()

    writer_thread = threading.Thread(target=_writer_loop, name="result-writer", daemon=True)
    writer_thread.start()
    tui.start()

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(_classify_one, index + 1, post): post
                for index, post in enumerate(raw_posts)
            }

            for future in as_completed(futures):
                idx, post, result = future.result()
                with lock:
                    stats.in_flight_posts = max(0, stats.in_flight_posts - 1)

                if result is None:
                    with lock:
                        stats.errors += 1
                    continue

                write_queue.put((idx, post, result))
    except Exception:
        stop_reporter.set()
        write_queue.put(None)
        writer_thread.join()
        tui.stop()
        fail_run(conn, run_id)
        conn.close()
        raise

    stop_reporter.set()
    write_queue.put(None)
    writer_thread.join()
    tui.stop()

    with lock:
        completed = stats.completed
        errors = stats.errors
        matches_total = dict(stats.matches)
        total_api_calls = stats.total_api_calls
        total_advisor_calls = stats.total_advisor_calls
        total_tool_calls = stats.total_tool_calls

    if completed == 0:
        log.error("Aucun post classifié.")
        fail_run(conn, run_id)
        conn.close()
        return

    acc = {axis: matches_total[axis] / completed for axis in matches_total}
    finish_run(
        conn,
        run_id,
        {
            "accuracy_category": acc["category"],
            "accuracy_visual_format": acc["visual_format"],
            "accuracy_strategy": acc["strategy"],
            "total_api_calls": total_api_calls,
        },
    )

    elapsed = time.monotonic() - t0
    log.info("")
    log.info("=" * 60)
    log.info("RÉSULTATS %s", "A1 bounded" if args.pipeline_mode == "bounded" else "A0 legacy")
    log.info("=" * 60)
    log.info("  Posts classifiés : %d / %d (erreurs : %d)", completed, len(raw_posts), errors)
    log.info("  Appels API       : %d (tools: %d, advisor: %d)", total_api_calls, total_tool_calls, total_advisor_calls)
    log.info("  Durée            : %.0fs (%.1f min)", elapsed, elapsed / 60)
    log.info("  Accuracy category     : %.1f%% (%d/%d)", acc["category"] * 100, matches_total["category"], completed)
    log.info("  Accuracy visual_format: %.1f%% (%d/%d)", acc["visual_format"] * 100, matches_total["visual_format"], completed)
    log.info("  Accuracy strategy     : %.1f%% (%d/%d)", acc["strategy"] * 100, matches_total["strategy"], completed)
    log.info("  simulation_run_id = %d", run_id)

    conn.close()


if __name__ == "__main__":
    main()
