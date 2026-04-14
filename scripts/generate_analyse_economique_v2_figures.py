#!/usr/bin/env python3
"""Generate reproducible figures for the v2 economic analysis chapter."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg


DEFAULT_DSN = "postgresql://hilpo:hilpo@localhost:5433/hilpo"
OUTPUT_ORDER = [96, 93, 97, 95, 94, 90]
FRONTIER_ORDER = [96, 93, 95, 90]
PAIR_COMPARISONS = [(96, 93), (97, 95), (94, 90), (93, 95), (95, 90)]

GEMINI_FLASH_LITE = "gemini-3.1-flash-lite-preview"
GEMINI_FLASH = "gemini-3-flash-preview"
CLAUDE_SONNET = "claude-sonnet-4-6"
CLASSIFIER_SAMPLE_K = 3

MODEL_PRICES = {
    GEMINI_FLASH_LITE: {"input": 0.25, "output": 1.50},
    GEMINI_FLASH: {"input": 0.50, "output": 3.00},
    CLAUDE_SONNET: {"input": 3.00, "output": 15.00},
}

RUN_META = {
    96: {
        "short": "96  FL naive",
        "mode": "E2E naive",
        "tier": "Flash Lite",
        "mode_color": "#4C78A8",
    },
    93: {
        "short": "93  Flash naive",
        "mode": "E2E naive",
        "tier": "Flash",
        "mode_color": "#4C78A8",
    },
    97: {
        "short": "97  FL harness",
        "mode": "E2E harness",
        "tier": "Flash Lite",
        "mode_color": "#F58518",
    },
    95: {
        "short": "95  FL pipeline",
        "mode": "Pipeline",
        "tier": "Flash Lite",
        "mode_color": "#54A24B",
    },
    94: {
        "short": "94  Flash harness",
        "mode": "E2E harness",
        "tier": "Flash",
        "mode_color": "#F58518",
    },
    90: {
        "short": "90  Flash pipeline",
        "mode": "Pipeline",
        "tier": "Flash (vf only)",
        "mode_color": "#54A24B",
    },
}


@dataclass
class PairResult:
    run_a: int
    run_b: int
    a_only: int
    b_only: int
    p_value: float
    delta_pp: float


def wilson_interval(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = correct / total
    denom = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + (z * z) / (4.0 * total)) / total) / denom
    return center - margin, center + margin


def mcnemar_exact_p(a_only: int, b_only: int) -> float:
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def build_summary(conn: psycopg.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                simulation_run_id,
                count(*) FILTER (WHERE agent = 'visual_format') AS n_total,
                sum(CASE WHEN agent = 'visual_format' AND match THEN 1 ELSE 0 END) AS n_correct
            FROM predictions
            WHERE simulation_run_id = ANY(%s)
            GROUP BY simulation_run_id
            ORDER BY simulation_run_id
            """,
            (OUTPUT_ORDER,),
        )
        accuracy_rows = {
            run_id: {"n_total": n_total, "n_correct": n_correct}
            for run_id, n_total, n_correct in cur.fetchall()
        }

        cur.execute(
            """
            SELECT
                simulation_run_id,
                agent,
                model_name,
                count(*) AS n_logs,
                sum(input_tokens) AS input_tokens,
                sum(output_tokens) AS output_tokens
            FROM api_calls
            WHERE simulation_run_id = ANY(%s)
            GROUP BY simulation_run_id, agent, model_name
            ORDER BY simulation_run_id, agent, model_name
            """,
            (OUTPUT_ORDER,),
        )
        api_rows = cur.fetchall()

        cur.execute(
            """
            SELECT
                simulation_run_id,
                count(*) FILTER (
                    WHERE raw_response -> 'oracle' ->> 'triggered' = 'true'
                ) AS oracle_calls,
                COALESCE(sum((raw_response -> 'oracle' ->> 'input_tokens')::int), 0) AS input_tokens,
                COALESCE(sum((raw_response -> 'oracle' ->> 'output_tokens')::int), 0) AS output_tokens
            FROM predictions
            WHERE simulation_run_id IN (90, 95)
              AND agent = 'visual_format'
            GROUP BY simulation_run_id
            ORDER BY simulation_run_id
            """
        )
        hidden_oracle = {
            run_id: {
                "oracle_calls": oracle_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            for run_id, oracle_calls, input_tokens, output_tokens in cur.fetchall()
        }

        cur.execute(
            """
            WITH vf AS (
                SELECT simulation_run_id, ig_media_id, match
                FROM predictions
                WHERE agent = 'visual_format'
                  AND simulation_run_id = ANY(%s)
            )
            SELECT
                a.simulation_run_id AS run_a,
                b.simulation_run_id AS run_b,
                sum(CASE WHEN a.match AND NOT b.match THEN 1 ELSE 0 END) AS a_only,
                sum(CASE WHEN NOT a.match AND b.match THEN 1 ELSE 0 END) AS b_only
            FROM vf a
            JOIN vf b USING (ig_media_id)
            WHERE a.simulation_run_id < b.simulation_run_id
            GROUP BY a.simulation_run_id, b.simulation_run_id
            ORDER BY a.simulation_run_id, b.simulation_run_id
            """,
            (OUTPUT_ORDER,),
        )
        pair_lookup = {
            (run_a, run_b): (a_only, b_only)
            for run_a, run_b, a_only, b_only in cur.fetchall()
        }

    component_totals: dict[int, dict[str, float | int]] = {}
    raw_requests: dict[int, int] = {}
    oracle_calls: dict[int, int] = {run_id: 0 for run_id in OUTPUT_ORDER}

    for run_id in OUTPUT_ORDER:
        component_totals[run_id] = {
            "logged_calls": 0,
            "flash_lite_cost": 0.0,
            "flash_cost": 0.0,
            "sonnet_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "descriptor_logs": 0,
            "category_logs": 0,
            "visual_logs": 0,
            "strategy_logs": 0,
            "e2e_logs": 0,
        }

    for run_id, agent, model_name, n_logs, input_tokens, output_tokens in api_rows:
        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
        component_totals[run_id]["logged_calls"] += int(n_logs)
        component_totals[run_id]["input_tokens"] += input_tokens
        component_totals[run_id]["output_tokens"] += output_tokens

        if agent == "descriptor":
            component_totals[run_id]["descriptor_logs"] += int(n_logs)
        elif agent == "category":
            component_totals[run_id]["category_logs"] += int(n_logs)
        elif agent == "visual_format":
            component_totals[run_id]["visual_logs"] += int(n_logs)
        elif agent == "strategy":
            component_totals[run_id]["strategy_logs"] += int(n_logs)
        elif agent == "e2e":
            component_totals[run_id]["e2e_logs"] += int(n_logs)
        elif agent == "e2e_oracle":
            oracle_calls[run_id] += int(n_logs)

        price = MODEL_PRICES[model_name]
        cost = (input_tokens / 1_000_000) * price["input"] + (output_tokens / 1_000_000) * price["output"]

        if model_name == GEMINI_FLASH_LITE:
            component_totals[run_id]["flash_lite_cost"] += cost
        elif model_name == GEMINI_FLASH:
            component_totals[run_id]["flash_cost"] += cost
        elif model_name == CLAUDE_SONNET:
            component_totals[run_id]["sonnet_cost"] += cost

    for run_id in OUTPUT_ORDER:
        hidden = hidden_oracle.get(run_id)
        if hidden:
            oracle_calls[run_id] += int(hidden["oracle_calls"])
            component_totals[run_id]["sonnet_cost"] += (
                hidden["input_tokens"] / 1_000_000 * MODEL_PRICES[CLAUDE_SONNET]["input"]
                + hidden["output_tokens"] / 1_000_000 * MODEL_PRICES[CLAUDE_SONNET]["output"]
            )

        if component_totals[run_id]["e2e_logs"]:
            raw_requests[run_id] = component_totals[run_id]["logged_calls"]
        else:
            raw_requests[run_id] = (
                int(component_totals[run_id]["descriptor_logs"])
                + CLASSIFIER_SAMPLE_K
                * (
                    int(component_totals[run_id]["category_logs"])
                    + int(component_totals[run_id]["visual_logs"])
                    + int(component_totals[run_id]["strategy_logs"])
                )
                + oracle_calls[run_id]
            )

    summary_rows = []
    for run_id in OUTPUT_ORDER:
        n_total = int(accuracy_rows[run_id]["n_total"])
        n_correct = int(accuracy_rows[run_id]["n_correct"])
        ci_low, ci_high = wilson_interval(n_correct, n_total)
        total_cost = (
            component_totals[run_id]["flash_lite_cost"]
            + component_totals[run_id]["flash_cost"]
            + component_totals[run_id]["sonnet_cost"]
        )
        summary_rows.append(
            {
                "run_id": run_id,
                "short_label": RUN_META[run_id]["short"],
                "mode": RUN_META[run_id]["mode"],
                "tier": RUN_META[run_id]["tier"],
                "accuracy_pct": 100.0 * n_correct / n_total,
                "ci_low_pct": 100.0 * ci_low,
                "ci_high_pct": 100.0 * ci_high,
                "n_correct": n_correct,
                "n_total": n_total,
                "cost_total_usd": total_cost,
                "cost_per_correct_usd": total_cost / n_correct,
                "logged_calls": int(component_totals[run_id]["logged_calls"]),
                "raw_provider_requests": raw_requests[run_id],
                "oracle_calls": oracle_calls[run_id],
                "input_tokens_m": component_totals[run_id]["input_tokens"] / 1_000_000,
                "output_tokens_m": component_totals[run_id]["output_tokens"] / 1_000_000,
                "flash_lite_cost_usd": component_totals[run_id]["flash_lite_cost"],
                "flash_cost_usd": component_totals[run_id]["flash_cost"],
                "sonnet_cost_usd": component_totals[run_id]["sonnet_cost"],
            }
        )

    pairs = []
    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.set_index("run_id").loc[OUTPUT_ORDER].reset_index()

    for run_a, run_b in PAIR_COMPARISONS:
        key = tuple(sorted((run_a, run_b)))
        left_only, right_only = pair_lookup[key]
        if key == (run_a, run_b):
            a_only, b_only = left_only, right_only
        else:
            a_only, b_only = right_only, left_only
        delta_pp = (
            summary_df.loc[summary_df["run_id"] == run_b, "accuracy_pct"].iloc[0]
            - summary_df.loc[summary_df["run_id"] == run_a, "accuracy_pct"].iloc[0]
        )
        pairs.append(
            PairResult(
                run_a=run_a,
                run_b=run_b,
                a_only=int(a_only),
                b_only=int(b_only),
                p_value=mcnemar_exact_p(int(a_only), int(b_only)),
                delta_pp=float(delta_pp),
            )
        )

    pair_df = pd.DataFrame(
        [
            {
                "run_a": pair.run_a,
                "run_b": pair.run_b,
                "label": f"{pair.run_a} vs {pair.run_b}",
                "a_only": pair.a_only,
                "b_only": pair.b_only,
                "delta_pp": pair.delta_pp,
                "p_value": pair.p_value,
            }
            for pair in pairs
        ]
    )
    return summary_df, pair_df


def save_summary_tables(summary_df: pd.DataFrame, pair_df: pd.DataFrame, outdir: Path) -> None:
    summary_df.to_csv(outdir / "analyse_economique_v2_summary.tsv", sep="\t", index=False)
    pair_df.to_csv(outdir / "analyse_economique_v2_pairs.tsv", sep="\t", index=False)


def plot_frontier(summary_df: pd.DataFrame, outdir: Path) -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 160,
            "savefig.dpi": 220,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 10,
        }
    )
    fig, ax = plt.subplots(figsize=(10.5, 6.2))

    frontier_df = summary_df.set_index("run_id").loc[FRONTIER_ORDER].reset_index()
    frontier_set = set(FRONTIER_ORDER)

    for _, row in summary_df.iterrows():
        is_frontier = row["run_id"] in frontier_set
        yerr = np.array(
            [
                [row["accuracy_pct"] - row["ci_low_pct"]],
                [row["ci_high_pct"] - row["accuracy_pct"]],
            ]
        )
        ax.errorbar(
            row["cost_total_usd"],
            row["accuracy_pct"],
            yerr=yerr,
            fmt="o",
            color=RUN_META[row["run_id"]]["mode_color"],
            ecolor="#9CA3AF" if not is_frontier else "#374151",
            elinewidth=1.2,
            capsize=3,
            alpha=1.0 if is_frontier else 0.55,
            ms=9 if is_frontier else 8,
            markeredgecolor="#111827" if is_frontier else "#6B7280",
            markeredgewidth=1.0,
            zorder=3,
        )
        dx = 0.07 if row["run_id"] in {96, 97, 95} else 0.10
        dy = 0.22 if row["run_id"] in {96, 93, 94} else -0.55
        ax.annotate(
            RUN_META[row["run_id"]]["short"],
            (row["cost_total_usd"], row["accuracy_pct"]),
            xytext=(row["cost_total_usd"] + dx, row["accuracy_pct"] + dy),
            fontsize=9,
            color="#111827",
        )

    ax.plot(
        frontier_df["cost_total_usd"],
        frontier_df["accuracy_pct"],
        color="#C62828",
        linewidth=2.0,
        linestyle="-",
        zorder=2,
        label="Frontiere de Pareto",
    )

    ax.set_title("Frontiere cout-performance sur le test set (437 posts)")
    ax.set_xlabel("Cout total du run (USD)")
    ax.set_ylabel("Accuracy visual_format (%)")
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    ax.set_xlim(0.8, 10.2)
    ax.set_ylim(69.5, 89.5)

    legend_handles = [
        plt.Line2D([], [], marker="o", linestyle="", color="#4C78A8", label="E2E naive"),
        plt.Line2D([], [], marker="o", linestyle="", color="#F58518", label="E2E harness"),
        plt.Line2D([], [], marker="o", linestyle="", color="#54A24B", label="Pipeline"),
        plt.Line2D([], [], color="#C62828", linewidth=2.0, label="Frontiere de Pareto"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(outdir / "analyse_economique_v2_frontier.png", bbox_inches="tight")
    plt.close(fig)


def plot_cost_structure(summary_df: pd.DataFrame, outdir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.8))
    x = np.arange(len(summary_df))

    axes[0].bar(x, summary_df["flash_lite_cost_usd"], color="#2A9D8F", label="Gemini Flash Lite")
    axes[0].bar(
        x,
        summary_df["flash_cost_usd"],
        bottom=summary_df["flash_lite_cost_usd"],
        color="#E9C46A",
        label="Gemini Flash",
    )
    axes[0].bar(
        x,
        summary_df["sonnet_cost_usd"],
        bottom=summary_df["flash_lite_cost_usd"] + summary_df["flash_cost_usd"],
        color="#D62828",
        label="Claude Sonnet",
    )
    for xpos, total in zip(x, summary_df["cost_total_usd"]):
        axes[0].text(xpos, total + 0.12, f"${total:.2f}", ha="center", va="bottom", fontsize=9)

    axes[0].set_title("Decomposition du cout par run")
    axes[0].set_ylabel("USD")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f"{run}\n{mode}" for run, mode in zip(summary_df["run_id"], summary_df["mode"])], fontsize=9)
    axes[0].grid(axis="y", color="#E5E7EB", linewidth=0.8)
    axes[0].legend(frameon=False, loc="upper left")

    width = 0.36
    axes[1].bar(x - width / 2, summary_df["logged_calls"], width=width, color="#7C8DB5", label="Appels journalises")
    axes[1].bar(x + width / 2, summary_df["raw_provider_requests"], width=width, color="#1F9D8A", label="Requetes provider")
    for xpos, logged, raw in zip(x, summary_df["logged_calls"], summary_df["raw_provider_requests"]):
        if raw > logged:
            axes[1].text(xpos, raw + 80, f"x{raw / logged:.2f}", ha="center", va="bottom", fontsize=8, color="#111827")

    axes[1].set_title("Mesure correcte de l'orchestration")
    axes[1].set_ylabel("Nombre d'appels")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([str(run) for run in summary_df["run_id"]], fontsize=9)
    axes[1].grid(axis="y", color="#E5E7EB", linewidth=0.8)
    axes[1].legend(frameon=False, loc="upper left")

    fig.tight_layout()
    fig.savefig(outdir / "analyse_economique_v2_cost_structure.png", bbox_inches="tight")
    plt.close(fig)


def plot_marginal_returns(summary_df: pd.DataFrame, pair_df: pd.DataFrame, outdir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.8))

    frontier_df = summary_df.set_index("run_id").loc[FRONTIER_ORDER].reset_index()
    segment_labels = []
    dollars_per_pp = []
    extra_corrects = []
    dollars_per_correct = []
    for left, right in zip(FRONTIER_ORDER, FRONTIER_ORDER[1:]):
        a = frontier_df[frontier_df["run_id"] == left].iloc[0]
        b = frontier_df[frontier_df["run_id"] == right].iloc[0]
        delta_cost = b["cost_total_usd"] - a["cost_total_usd"]
        delta_pp = b["accuracy_pct"] - a["accuracy_pct"]
        delta_correct = b["n_correct"] - a["n_correct"]
        segment_labels.append(f"{left}->{right}")
        dollars_per_pp.append(delta_cost / delta_pp)
        extra_corrects.append(delta_correct)
        dollars_per_correct.append(delta_cost / delta_correct)

    x = np.arange(len(segment_labels))
    axes[0].bar(x, dollars_per_pp, color=["#4C78A8", "#F58518", "#D62828"])
    for xpos, value, corrects, per_correct in zip(x, dollars_per_pp, extra_corrects, dollars_per_correct):
        axes[0].text(
            xpos,
            value + 0.08,
            f"${value:.2f}/pp\n{corrects} corrects\n${per_correct:.3f}/correct",
            ha="center",
            va="bottom",
            fontsize=8.5,
        )
    axes[0].set_title("Rendements marginaux le long de la frontiere")
    axes[0].set_ylabel("Cout marginal (USD par point de pourcentage)")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(segment_labels)
    axes[0].grid(axis="y", color="#E5E7EB", linewidth=0.8)

    plot_pairs = pair_df[pair_df["label"].isin(["96 vs 93", "97 vs 95", "94 vs 90", "93 vs 95", "95 vs 90"])].copy()
    y = np.arange(len(plot_pairs))
    axes[1].barh(y, -plot_pairs["a_only"], color="#B8C1D9", label="Correct uniquement pour le run de gauche")
    axes[1].barh(y, plot_pairs["b_only"], color="#3A7D44", label="Correct uniquement pour le run de droite")
    for ypos, (_, row) in zip(y, plot_pairs.iterrows()):
        axes[1].text(
            row["b_only"] + 1.8,
            ypos,
            f"p={row['p_value']:.3g}",
            va="center",
            fontsize=8.5,
            color="#111827",
        )
    axes[1].axvline(0, color="#111827", linewidth=1.0)
    axes[1].set_title("Discordances appariees (McNemar exact)")
    axes[1].set_xlabel("Nombre de posts")
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(plot_pairs["label"])
    axes[1].grid(axis="x", color="#E5E7EB", linewidth=0.8)
    axes[1].legend(frameon=False, loc="lower right")

    fig.tight_layout()
    fig.savefig(outdir / "analyse_economique_v2_marginal_returns.png", bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")
    parser.add_argument("--outdir", default="docs", help="Directory where the figures will be written")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.dsn) as conn:
        summary_df, pair_df = build_summary(conn)

    save_summary_tables(summary_df, pair_df, outdir)
    plot_frontier(summary_df, outdir)
    plot_cost_structure(summary_df, outdir)
    plot_marginal_returns(summary_df, pair_df, outdir)


if __name__ == "__main__":
    main()
