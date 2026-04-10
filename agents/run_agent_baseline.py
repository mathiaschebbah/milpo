"""Évaluation pipeline agentique A0 sur le split test.

Usage :
    uv run python agents/run_agent_baseline.py
    uv run python agents/run_agent_baseline.py --limit 10   # test rapide sur 10 posts
    uv run python agents/run_agent_baseline.py --dry-run     # affiche les posts sans classifier

Variables d'environnement (chargées depuis .env) :
    ANTHROPIC_API_KEY               — clé API Anthropic (pour Haiku + advisor Opus)
    OPENROUTER_API_KEY              — clé API OpenRouter (pour Gemini descripteur)
    HILPO_GCS_SIGNING_SA_EMAIL      — service account pour signer les URLs GCS
    HILPO_DATABASE_DSN              — DSN PostgreSQL
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from milpo.db import (
    format_descriptions,
    get_active_prompt,
    get_conn,
    load_categories,
    load_post_media,
    load_strategies,
    load_visual_formats,
    store_api_call,
    store_prediction,
)
from milpo.gcs import sign_all_posts_media

from agents.config import MODEL_ADVISOR, MODEL_DESCRIPTOR, MODEL_EXECUTOR
from agents.pipeline import AgentResult, classify_post_agentic
from agents.tools import MediaContext

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


# ── Helpers BDD ───────────────────────────────────────────────────


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


def finish_run(conn, run_id: int, metrics: dict):
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


def fail_run(conn, run_id: int):
    conn.execute(
        "UPDATE simulation_runs SET status = 'failed', finished_at = NOW() WHERE id = %s",
        (run_id,),
    )
    conn.commit()


# ── Stockage résultats ────────────────────────────────────────────


def store_agent_results(
    conn,
    result: AgentResult,
    run_id: int,
) -> dict[str, bool]:
    """Stocke les prédictions, api_calls et trace de l'agent en BDD."""
    matches = {}

    for axis in ("category", "visual_format", "strategy"):
        classification = getattr(result, axis)
        pid = store_prediction(
            conn,
            ig_media_id=result.ig_media_id,
            agent=axis,
            prompt_version_id=result.prompt_version_id,
            predicted_value=classification.label,
            raw_response={
                "confidence": classification.confidence,
                "reasoning": classification.reasoning[-300:],
                "pipeline": "agent_a0",
            },
            simulation_run_id=run_id,
        )
        row = conn.execute("SELECT match FROM predictions WHERE id = %s", (pid,)).fetchone()
        matches[axis] = bool(row and row["match"])

    # Stocker les api_calls — mapper vers agent_type enum valide
    for call in result.api_calls:
        if call.agent.startswith("tool/describe"):
            db_agent = "descriptor"
        else:
            db_agent = "agent_executor"
        store_api_call(
            conn,
            call_type="classification",
            agent=db_agent,
            model_name=call.model,
            prompt_version_id=None,
            ig_media_id=result.ig_media_id,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=None,
            latency_ms=call.latency_ms,
            simulation_run_id=run_id,
        )

    # Stocker la trace structurée dans agent_traces
    # Agréger les tokens par type (executor, advisor, descriptor)
    tok_exec_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("agent/"))
    tok_exec_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("agent/"))
    tok_adv_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("advisor/"))
    tok_adv_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("advisor/"))
    tok_desc_in = sum(c.input_tokens for c in result.api_calls if c.agent.startswith("tool/"))
    tok_desc_out = sum(c.output_tokens for c in result.api_calls if c.agent.startswith("tool/"))

    trace_json = json.dumps([e.to_dict() for e in result.trace])

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
             trace)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            run_id, result.ig_media_id,
            result.tool_calls, result.advisor_calls,
            tok_exec_in, tok_exec_out,
            tok_adv_in, tok_adv_out,
            tok_desc_in, tok_desc_out,
            result.latency_ms,
            result.category.label, result.category.confidence,
            result.visual_format.label, result.visual_format.confidence,
            result.strategy.label, result.strategy.confidence,
            trace_json,
        ),
    )
    conn.commit()

    return matches


# ── Main ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Évalue la pipeline agentique A0 sur le split test")
    parser.add_argument("--limit", type=int, default=None, help="Limiter à N posts (pour tests)")
    parser.add_argument("--workers", type=int, default=3, help="Nombre de posts classifiés en parallèle (défaut: 3, rate limit Haiku 50K tok/min)")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les posts sans classifier")
    args = parser.parse_args()

    conn = get_conn()
    t0 = time.monotonic()

    log.info("=" * 60)
    log.info("A0 — Pipeline agentique Haiku + Opus advisor (split test)")
    log.info("=" * 60)
    log.info("  executor  : %s", MODEL_EXECUTOR)
    log.info("  advisor   : %s", MODEL_ADVISOR)
    log.info("  descriptor: %s", MODEL_DESCRIPTOR)

    # 1. Posts test
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
        for p in raw_posts[:10]:
            log.info("  %s %s %s (%d)", p["ig_media_id"], p["media_product_type"],
                     (p["caption"] or "")[:50], p["post_year"])
        log.info("Dry run — pas de classification.")
        return

    # 2. Simulation run
    run_id = create_run(conn, {
        "name": "A0_agent_haiku_opus_test",
        "split": "test",
        "pipeline": "agent_a0",
        "models": {
            "executor": MODEL_EXECUTOR,
            "advisor": MODEL_ADVISOR,
            "descriptor": MODEL_DESCRIPTOR,
        },
    })
    log.info("simulation_run id=%d", run_id)

    # 3. Signature URLs GCS
    log.info("Signature des URLs GCS...")
    signed_by_post = sign_all_posts_media(raw_posts, load_post_media, conn, max_workers=20)

    # 4. Charger les prompts descripteur (pour le tool describe_media)
    desc_feed = get_active_prompt(conn, "descriptor", "FEED")
    desc_reels = get_active_prompt(conn, "descriptor", "REELS")
    if not desc_feed or not desc_reels:
        log.error("Prompts descripteur introuvables en BDD!")
        fail_run(conn, run_id)
        sys.exit(1)

    # Descriptions taxonomiques pour le descripteur
    vf_feed_desc = format_descriptions(load_visual_formats(conn, "FEED"))
    vf_reels_desc = format_descriptions(load_visual_formats(conn, "REELS"))

    # 5. Classification parallèle
    max_workers = args.workers
    total = len(raw_posts)
    log.info("Classification en cours (%d workers)...", max_workers)

    matches_total = {"category": 0, "visual_format": 0, "strategy": 0}
    total_api_calls = 0
    total_advisor_calls = 0
    total_tool_calls = 0
    errors = 0
    done_count = 0
    lock = threading.Lock()

    def _progress_bar():
        elapsed = time.monotonic() - t0
        rate = done_count / elapsed if elapsed > 0 else 0
        remaining = total - done_count
        eta = remaining / rate if rate > 0 else 0
        pct = done_count * 100 // total if total else 0
        filled = done_count * 30 // total if total else 0
        bar = "█" * filled + "░" * (30 - filled)
        ok = done_count - errors
        acc_cat = matches_total["category"] / ok * 100 if ok else 0
        acc_vf = matches_total["visual_format"] / ok * 100 if ok else 0
        acc_str = matches_total["strategy"] / ok * 100 if ok else 0
        print(
            f"\r  {bar} {done_count:>3}/{total} ({pct:>2}%) "
            f"| {rate:.2f} posts/s "
            f"| ETA {eta:.0f}s "
            f"| err {errors} "
            f"| cat {acc_cat:.0f}% vf {acc_vf:.0f}% str {acc_str:.0f}%",
            end="", flush=True,
        )

    def _classify_one(idx: int, post: dict) -> tuple[int, dict, AgentResult | None]:
        """Classifie un post dans un thread dédié (connexion BDD propre)."""
        mid = post["ig_media_id"]
        scope = post["media_product_type"]
        signed = signed_by_post.get(mid, [])

        if not signed:
            return idx, post, None

        media_urls = [u for u, _ in signed]
        media_types = [m for _, m in signed]
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
            result = classify_post_agentic(mid, media_ctx, thread_conn)
            return idx, post, result
        except Exception as exc:
            log.error("  [%d/%d] %s ERREUR: %s", idx, total, mid, exc)
            return idx, post, None
        finally:
            thread_conn.close()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_classify_one, i + 1, post): post
            for i, post in enumerate(raw_posts)
        }

        for future in as_completed(futures):
            idx, post, result = future.result()
            mid = post["ig_media_id"]

            with lock:
                done_count += 1

                if result is None:
                    errors += 1
                    _progress_bar()
                    continue

                try:
                    post_matches = store_agent_results(conn, result, run_id)
                except Exception as exc:
                    log.error("  store error %s: %s", mid, exc)
                    conn.rollback()
                    errors += 1
                    _progress_bar()
                    continue

                for axis in ("category", "visual_format", "strategy"):
                    if post_matches[axis]:
                        matches_total[axis] += 1

                total_api_calls += len(result.api_calls)
                total_advisor_calls += result.advisor_calls
                total_tool_calls += result.tool_calls
                _progress_bar()

    print()  # newline après la barre

    # 6. Métriques
    n = len(raw_posts) - errors
    if n == 0:
        log.error("Aucun post classifié!")
        fail_run(conn, run_id)
        return

    acc = {k: v / n for k, v in matches_total.items()}

    finish_run(conn, run_id, {
        "accuracy_category": acc["category"],
        "accuracy_visual_format": acc["visual_format"],
        "accuracy_strategy": acc["strategy"],
        "total_api_calls": total_api_calls,
    })

    elapsed = time.monotonic() - t0

    log.info("")
    log.info("=" * 60)
    log.info("RÉSULTATS A0 — Pipeline agentique")
    log.info("=" * 60)
    log.info("  Posts classifiés : %d / %d (erreurs : %d)", n, len(raw_posts), errors)
    log.info("  Appels API       : %d (tools: %d, advisor: %d)", total_api_calls, total_tool_calls, total_advisor_calls)
    log.info("  Durée            : %.0fs (%.1f min)", elapsed, elapsed / 60)
    log.info("")
    log.info("  Accuracy catégorie     : %.1f%% (%d/%d)", acc["category"] * 100, matches_total["category"], n)
    log.info("  Accuracy visual_format : %.1f%% (%d/%d)", acc["visual_format"] * 100, matches_total["visual_format"], n)
    log.info("  Accuracy stratégie     : %.1f%% (%d/%d)", acc["strategy"] * 100, matches_total["strategy"], n)
    log.info("")
    log.info("  simulation_run_id = %d", run_id)
    log.info("✓ A0 terminé")

    conn.close()


if __name__ == "__main__":
    main()
