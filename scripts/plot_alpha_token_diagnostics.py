#!/usr/bin/env python3
"""Generate token-focused diagnostic figures for the 8 alpha ablation runs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
import numpy as np
import psycopg
from dotenv import load_dotenv
from matplotlib.lines import Line2D

from plot_ablation_alpha import RUN_SPECS, RUN_SPECS_BY_ID


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_DSN = os.environ.get("HILPO_DATABASE_DSN", "postgresql://hilpo:hilpo@localhost:5433/hilpo")
OUTPUT_DIR = PROJECT_ROOT / "docs" / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RUN_IDS = tuple(run.run_id for run in RUN_SPECS)
MODE_COLORS = {
    "Alma": "#2563EB",
    "Simple": "#16A34A",
}
TIER_COLORS = {
    "Flash-Lite": "#2563EB",
    "Flash": "#F59E0B",
    "Full-Flash": "#DC2626",
    "Qwen": "#7C3AED",
}
ASSIST_LINESTYLES = {
    "ASSIST": "-",
    "no-assist": "--",
}
FRONTIER_LABELS = {
    158: {"offset": (8, 3), "ha": "left", "va": "bottom"},
    159: {"offset": (8, -3), "ha": "left", "va": "top"},
    160: {"offset": (10, 2), "ha": "left", "va": "bottom"},
    161: {"offset": (8, -6), "ha": "left", "va": "top"},
    164: {"offset": (-8, -2), "ha": "right", "va": "top"},
    165: {"offset": (8, 10), "ha": "left", "va": "bottom"},
    167: {"offset": (10, 0), "ha": "left", "va": "center"},
    171: {"offset": (10, 10), "ha": "left", "va": "bottom"},
}

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "savefig.dpi": 300,
    }
)


@dataclass(frozen=True)
class RunMetric:
    run_id: int
    total_tokens: int
    reasoning_tokens: int
    n_posts: int
    n_correct: int

    @property
    def accuracy_pct(self) -> float:
        return 100.0 * self.n_correct / self.n_posts

    @property
    def tokens_per_post(self) -> float:
        return self.total_tokens / self.n_posts

    @property
    def reasoning_share_pct(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return 100.0 * self.reasoning_tokens / self.total_tokens

    @property
    def spec(self):
        return RUN_SPECS_BY_ID[self.run_id]


@dataclass(frozen=True)
class PostMetric:
    run_id: int
    ig_media_id: int
    total_tokens: int
    reasoning_tokens: int
    vf_match: bool

    @property
    def spec(self):
        return RUN_SPECS_BY_ID[self.run_id]


@dataclass(frozen=True)
class QuintileMetric:
    label: str
    bucket: int
    mean_tokens: float
    match_rate_pct: float
    n_posts: int


def _assist_text(label: str) -> str:
    return "Sans ASSIST" if label == "no-assist" else label


def _run_name(run_id: int, *, include_mode: bool = True, width: int | None = None) -> str:
    spec = RUN_SPECS_BY_ID[run_id]
    parts = []
    if include_mode:
        parts.append(spec.mode_label)
    parts.append(spec.tier_label)
    if spec.mode_label == "Simple":
        parts.append(_assist_text(spec.assist_label))

    text = " ".join(parts)
    if width is None:
        return text
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def _group_label(run_id: int) -> str:
    spec = RUN_SPECS_BY_ID[run_id]
    if spec.mode_label == "Alma":
        return "Alma"
    if spec.assist_label == "ASSIST":
        return "Simple + ASSIST"
    return "Simple sans ASSIST"


def _load_run_metrics() -> list[RunMetric]:
    query = """
        WITH token_totals AS (
            SELECT
                simulation_run_id AS run_id,
                SUM(input_tokens + output_tokens) AS total_tokens,
                SUM(reasoning_tokens) AS reasoning_tokens
            FROM api_calls
            WHERE simulation_run_id = ANY(%s)
            GROUP BY simulation_run_id
        ),
        vf AS (
            SELECT
                simulation_run_id AS run_id,
                COUNT(*) AS n_posts,
                SUM(CASE WHEN match THEN 1 ELSE 0 END) AS n_correct
            FROM predictions
            WHERE agent = 'visual_format'
              AND simulation_run_id = ANY(%s)
            GROUP BY simulation_run_id
        )
        SELECT
            t.run_id,
            t.total_tokens,
            t.reasoning_tokens,
            vf.n_posts,
            vf.n_correct
        FROM token_totals t
        JOIN vf ON vf.run_id = t.run_id
        ORDER BY t.run_id
    """

    with psycopg.connect(DATABASE_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (list(RUN_IDS), list(RUN_IDS)))
            rows = cur.fetchall()

    return [
        RunMetric(
            run_id=run_id,
            total_tokens=int(total_tokens),
            reasoning_tokens=int(reasoning_tokens),
            n_posts=int(n_posts),
            n_correct=int(n_correct),
        )
        for run_id, total_tokens, reasoning_tokens, n_posts, n_correct in rows
    ]


def _load_post_metrics() -> list[PostMetric]:
    query = """
        WITH vf AS (
            SELECT
                simulation_run_id,
                ig_media_id,
                match
            FROM predictions
            WHERE agent = 'visual_format'
              AND simulation_run_id = ANY(%s)
        )
        SELECT
            a.simulation_run_id,
            a.ig_media_id,
            SUM(a.input_tokens + a.output_tokens) AS total_tokens,
            SUM(a.reasoning_tokens) AS reasoning_tokens,
            MAX(CASE WHEN vf.match THEN 1 ELSE 0 END) AS vf_match
        FROM api_calls a
        JOIN vf
          ON vf.simulation_run_id = a.simulation_run_id
         AND vf.ig_media_id = a.ig_media_id
        WHERE a.simulation_run_id = ANY(%s)
        GROUP BY a.simulation_run_id, a.ig_media_id
        ORDER BY a.simulation_run_id, a.ig_media_id
    """

    with psycopg.connect(DATABASE_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (list(RUN_IDS), list(RUN_IDS)))
            rows = cur.fetchall()

    return [
        PostMetric(
            run_id=int(run_id),
            ig_media_id=int(ig_media_id),
            total_tokens=int(total_tokens),
            reasoning_tokens=int(reasoning_tokens),
            vf_match=bool(vf_match),
        )
        for run_id, ig_media_id, total_tokens, reasoning_tokens, vf_match in rows
    ]


def _compute_frontier(run_metrics: list[RunMetric]) -> list[RunMetric]:
    frontier = []

    for candidate in run_metrics:
        dominated = False
        for other in run_metrics:
            if other.run_id == candidate.run_id:
                continue

            same_or_lower_tokens = other.tokens_per_post <= candidate.tokens_per_post
            same_or_higher_acc = other.accuracy_pct >= candidate.accuracy_pct
            strictly_better = (
                other.tokens_per_post < candidate.tokens_per_post
                or other.accuracy_pct > candidate.accuracy_pct
            )
            if same_or_lower_tokens and same_or_higher_acc and strictly_better:
                dominated = True
                break

        if not dominated:
            frontier.append(candidate)

    return sorted(frontier, key=lambda run: run.tokens_per_post)


def _compute_group_bins(post_metrics: list[PostMetric], n_bins: int = 6) -> dict[str, list[QuintileMetric]]:
    grouped: dict[str, list[PostMetric]] = {}
    for post in post_metrics:
        grouped.setdefault(_group_label(post.run_id), []).append(post)

    group_bins: dict[str, list[QuintileMetric]] = {}
    for label, posts in grouped.items():
        ordered = sorted(posts, key=lambda post: post.total_tokens)
        bins = []
        for q_index, bucket_indices in enumerate(np.array_split(np.arange(len(ordered)), n_bins), start=1):
            bucket = [ordered[int(idx)] for idx in bucket_indices]
            mean_tokens = float(np.mean([post.total_tokens for post in bucket]))
            match_rate_pct = 100.0 * float(np.mean([1.0 if post.vf_match else 0.0 for post in bucket]))
            bins.append(
                QuintileMetric(
                    label=label,
                    bucket=q_index,
                    mean_tokens=mean_tokens,
                    match_rate_pct=match_rate_pct,
                    n_posts=len(bucket),
                )
            )
        group_bins[label] = bins

    return group_bins


def plot_tokens_accuracy_frontier(run_metrics: list[RunMetric]) -> None:
    frontier = _compute_frontier(run_metrics)
    frontier_ids = {run.run_id for run in frontier}

    fig, ax = plt.subplots(figsize=(8.0, 4.9))
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)

    for run in sorted(run_metrics, key=lambda item: item.tokens_per_post):
        color = MODE_COLORS[run.spec.mode_label]
        is_frontier = run.run_id in frontier_ids
        ax.scatter(
            run.tokens_per_post / 1000.0,
            run.accuracy_pct,
            s=150 if is_frontier else 110,
            marker="o",
            facecolor=color,
            edgecolor=color,
            linewidth=1.0,
            alpha=0.95 if is_frontier else 0.28,
            zorder=3 if is_frontier else 2,
        )

        label_cfg = FRONTIER_LABELS[run.run_id]
        annotation = ax.annotate(
            f"{_run_name(run.run_id, width=16)}\n(run {run.run_id})",
            xy=(run.tokens_per_post / 1000.0, run.accuracy_pct),
            xytext=label_cfg["offset"],
            textcoords="offset points",
            ha=label_cfg["ha"],
            va=label_cfg["va"],
            fontsize=8.2,
            color=color if is_frontier else "#6B7280",
            fontweight="bold" if is_frontier else "normal",
            zorder=4,
        )
        annotation.set_path_effects(
            [pe.withStroke(linewidth=3.5, foreground="white")]
        )

    ax.plot(
        [run.tokens_per_post / 1000.0 for run in frontier],
        [run.accuracy_pct for run in frontier],
        color="#DC2626",
        linestyle=(0, (4, 2)),
        linewidth=2.0,
        zorder=1,
    )

    ax.set_xlabel("Tokens par post (k)")
    ax.set_ylabel("Accuracy VF (%)")
    ax.set_title("Frontiere tokens-performance (alpha, 8 runs)", fontweight="bold")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2.0))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax.set_xlim(22.0, 38.5)
    ax.set_ylim(81.0, 88.8)

    legend_handles = [
        Line2D([], [], marker="o", linestyle="", color=MODE_COLORS["Alma"], markersize=8, label="Alma"),
        Line2D([], [], marker="o", linestyle="", color=MODE_COLORS["Simple"], markersize=8, label="Simple"),
        Line2D([], [], color="#DC2626", linestyle=(0, (4, 2)), linewidth=2.0, label="Frontiere de Pareto"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", frameon=True, edgecolor="#D1D5DB")
    ax.text(
        0.02,
        0.04,
        "Tous les points de frontiere appartiennent a l'architecture Simple.",
        transform=ax.transAxes,
        fontsize=9,
        color="#374151",
    )

    fig.tight_layout()
    path = OUTPUT_DIR / "alpha_tokens_accuracy_frontier.png"
    fig.savefig(path, bbox_inches="tight")
    print(f"  -> {path}")
    plt.close(fig)


def plot_group_binned_match_rate(post_metrics: list[PostMetric]) -> None:
    grouped_bins = _compute_group_bins(post_metrics, n_bins=6)
    colors = {
        "Alma": "#2563EB",
        "Simple + ASSIST": "#16A34A",
        "Simple sans ASSIST": "#F59E0B",
    }

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.8)

    for label in ("Alma", "Simple + ASSIST", "Simple sans ASSIST"):
        series = grouped_bins[label]
        x = np.array([point.mean_tokens / 1000.0 for point in series], dtype=float)
        y = np.array([point.match_rate_pct for point in series], dtype=float)
        ax.plot(
            x,
            y,
            color=colors[label],
            linewidth=2.4,
            marker="o",
            markersize=5.5,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label=label,
        )
        if len(x) >= 2:
            coeffs = np.polyfit(np.log(x), y, 1)
            x_fit = np.linspace(x.min(), x.max(), 120)
            y_fit = coeffs[0] * np.log(x_fit) + coeffs[1]
            ax.plot(
                x_fit,
                y_fit,
                color=colors[label],
                linewidth=1.5,
                linestyle=(0, (3, 2)),
                alpha=0.8,
            )

    ax.set_xlabel("Tokens moyens par post (k)")
    ax.set_ylabel("Taux de match VF (%)")
    ax.set_title("Courbe agregee : plus de tokens signalent surtout des posts plus difficiles", fontweight="bold")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(5.0))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(2.0))
    ax.set_xlim(12.0, 52.0)
    ax.set_ylim(80.0, 90.5)
    ax.legend(loc="lower left", frameon=True, edgecolor="#D1D5DB")
    ax.text(
        0.98,
        0.06,
        "Points pleins = bins empiriques\nPointilles = fit lineaire en log(x)",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.7,
        color="#4B5563",
    )

    fig.tight_layout()
    path = OUTPUT_DIR / "alpha_tokens_match_binned.png"
    fig.savefig(path, bbox_inches="tight")
    print(f"  -> {path}")
    plt.close(fig)


def plot_pairwise_marginal_returns(run_metrics: list[RunMetric]) -> None:
    run_metrics_by_id = {run.run_id: run for run in run_metrics}
    comparisons = [
        {
            "label": "ASSIST sur Flash",
            "start": 167,
            "end": 171,
            "color": "#16A34A",
        },
        {
            "label": "ASSIST sur Flash-Lite",
            "start": 165,
            "end": 164,
            "color": "#F59E0B",
        },
        {
            "label": "Alma Flash-Lite -> Flash",
            "start": 158,
            "end": 159,
            "color": "#2563EB",
        },
        {
            "label": "Alma Flash -> Full-Flash",
            "start": 159,
            "end": 160,
            "color": "#DC2626",
        },
    ]

    fig, ax = plt.subplots(figsize=(8.3, 4.9))
    ax.set_axisbelow(True)
    ax.grid(True, color="#E5E7EB", linewidth=0.8)

    for comparison in comparisons:
        start = run_metrics_by_id[comparison["start"]]
        end = run_metrics_by_id[comparison["end"]]
        x0, y0 = start.tokens_per_post / 1000.0, start.accuracy_pct
        x1, y1 = end.tokens_per_post / 1000.0, end.accuracy_pct

        ax.scatter([x0, x1], [y0, y1], s=90, color=comparison["color"], zorder=3)
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops={
                "arrowstyle": "->",
                "color": comparison["color"],
                "linewidth": 2.0,
                "shrinkA": 5,
                "shrinkB": 5,
            },
            zorder=2,
        )

        dx = x1 - x0
        dy = y1 - y0
        xm = (x0 + x1) / 2.0
        ym = (y0 + y1) / 2.0
        ax.text(
            xm + 0.15,
            ym + 0.18,
            f"{comparison['label']}\n{dx:+.1f}k tok, {dy:+.1f} pp",
            fontsize=8.5,
            color=comparison["color"],
            va="bottom",
        )

    ax.set_xlabel("Tokens par post (k)")
    ax.set_ylabel("Accuracy VF (%)")
    ax.set_title("Rendements marginaux : le gain depend du modele et de l'architecture", fontweight="bold")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2.0))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax.set_xlim(22.5, 30.5)
    ax.set_ylim(83.0, 88.7)
    ax.text(
        0.98,
        0.05,
        "Pas de loi unique type Cobb-Douglas :\nle meme surplus de tokens peut aider, ne rien changer, ou nuire.",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.7,
        color="#374151",
    )

    fig.tight_layout()
    path = OUTPUT_DIR / "alpha_marginal_returns_pairs.png"
    fig.savefig(path, bbox_inches="tight")
    print(f"  -> {path}")
    plt.close(fig)


def main() -> None:
    print("Generation des diagnostics tokens alpha...")
    run_metrics = _load_run_metrics()
    post_metrics = _load_post_metrics()
    plot_tokens_accuracy_frontier(run_metrics)
    plot_group_binned_match_rate(post_metrics)
    plot_pairwise_marginal_returns(run_metrics)
    print("Done.")


if __name__ == "__main__":
    main()
