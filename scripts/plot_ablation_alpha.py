"""Génère les graphiques d'analyse de l'ablation alpha pour le mémoire.

Produit 4 figures dans docs/ :
1. Frontière de Pareto coût-performance (VF%)
2. Comparaison architectures à modèle constant
3. Impact ASSIST (avec vs sans) à modèle constant
4. Tableau récapitulatif complet (3 axes)
"""

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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATABASE_DSN = os.environ.get("HILPO_DATABASE_DSN", "postgresql://hilpo:hilpo@localhost:5433/hilpo")
OUTPUT_DIR = PROJECT_ROOT / "docs"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "savefig.dpi": 300,
})

# ── Données alpha (labels + résumé numérique) ───────────────────────────────


@dataclass(frozen=True)
class RunSpec:
    run_id: int
    mode_label: str
    tier_label: str
    assist_label: str
    vf_pct: float
    cat_pct: float
    strat_pct: float
    cost_usd: float
    cpp_cents: float
    n_posts: int
    errors: int

    @property
    def accuracy_pct(self) -> float:
        return self.vf_pct


RUNS = [
    # (run_id, mode, tier, assist, vf%, cat%, strat%, cost_usd, cpp_cents, n_posts, errors)
    (158, "Alma",   "Flash-Lite",  "ASSIST",    83.8, 92.8, 96.9, 3.67, 0.94, 390, 0),
    (159, "Alma",   "Flash",       "ASSIST",    83.6, 92.8, 96.9, 4.62, 1.18, 390, 0),
    (160, "Alma",   "Full-Flash",  "ASSIST",    86.7, 93.3, 96.7, 7.72, 1.98, 390, 0),
    (161, "Alma",   "Qwen",        "ASSIST",    82.2, 93.4, 95.8, 2.33, 0.62, 377, 13),
    (164, "Simple", "Flash-Lite",  "ASSIST",    84.9, 89.5, 97.4, 3.25, 0.83, 390, 0),
    (165, "Simple", "Flash-Lite",  "no-assist", 85.4, 91.8, 97.4, 3.05, 0.78, 390, 0),
    (167, "Simple", "Flash",       "no-assist", 85.3, 90.5, 98.2, 4.92, 1.27, 389, 1),
    (171, "Simple", "Flash",       "ASSIST",    87.8, 89.6, 98.4, 5.18, 1.34, 386, 4),
]

RUN_SPECS = [RunSpec(*run) for run in RUNS]
RUN_SPECS_BY_ID = {run.run_id: run for run in RUN_SPECS}
ALPHA_RUN_IDS = tuple(run.run_id for run in RUN_SPECS)

PARETO_LABEL_POSITIONS = {
    158: {"offset": (10, 2), "ha": "left", "va": "bottom"},
    159: {"offset": (10, -2), "ha": "left", "va": "top"},
    160: {"offset": (8, 4), "ha": "left", "va": "bottom"},
    161: {"offset": (10, -6), "ha": "left", "va": "top"},
    164: {"offset": (-10, -2), "ha": "right", "va": "top"},
    165: {"offset": (10, 14), "ha": "left", "va": "bottom"},
    167: {"offset": (12, 0), "ha": "left", "va": "center"},
    171: {"offset": (10, 10), "ha": "left", "va": "bottom"},
}


@dataclass(frozen=True)
class ParetoPoint:
    run_id: int
    cost_usd: float
    n_predictions: int
    n_correct: int

    @property
    def accuracy_pct(self) -> float:
        return 100.0 * self.n_correct / self.n_predictions


def _assist_label_text(label: str) -> str:
    return "Sans ASSIST" if label == "no-assist" else label


def _display_name(run: RunSpec, *, include_assist: bool = True, width: int | None = None) -> str:
    parts = [run.mode_label, run.tier_label]
    if include_assist and run.assist_label != "ASSIST":
        parts.append(_assist_label_text(run.assist_label))

    text = " ".join(parts)
    if width is None:
        return text
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def _load_pareto_points() -> list[ParetoPoint]:
    query = """
        SELECT
            r.id,
            r.total_cost_usd,
            (
                SELECT count(*)
                FROM predictions p
                WHERE p.simulation_run_id = r.id
                  AND p.agent = 'visual_format'
            ) AS n_predictions,
            (
                SELECT count(*)
                FROM predictions p
                WHERE p.simulation_run_id = r.id
                  AND p.agent = 'visual_format'
                  AND p.match
            ) AS n_correct
        FROM simulation_runs r
        WHERE r.id = ANY(%s)
        ORDER BY r.total_cost_usd
    """

    with psycopg.connect(DATABASE_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (list(ALPHA_RUN_IDS),))
            rows = cur.fetchall()

    points = [
        ParetoPoint(
            run_id=run_id,
            cost_usd=float(cost_usd),
            n_predictions=int(n_predictions),
            n_correct=int(n_correct),
        )
        for run_id, cost_usd, n_predictions, n_correct in rows
    ]

    if len(points) != len(ALPHA_RUN_IDS):
        raise RuntimeError(
            f"Pareto alpha incomplet: {len(points)} runs charges, {len(ALPHA_RUN_IDS)} attendus."
        )

    return points


def _compute_pareto_frontier(runs) -> list:
    frontier = []

    for candidate in runs:
        dominated = False
        for other in runs:
            if other.run_id == candidate.run_id:
                continue

            same_or_lower_cost = other.cost_usd <= candidate.cost_usd
            same_or_higher_acc = other.accuracy_pct >= candidate.accuracy_pct
            strictly_better = (
                other.cost_usd < candidate.cost_usd
                or other.accuracy_pct > candidate.accuracy_pct
            )
            if same_or_lower_cost and same_or_higher_acc and strictly_better:
                dominated = True
                break

        if not dominated:
            frontier.append(candidate)

    return sorted(frontier, key=lambda run: run.cost_usd)


def _pareto_label(run_id: int) -> str:
    display_name = _display_name(RUN_SPECS_BY_ID[run_id], width=18)
    return f"{display_name}\n(run {run_id})"


# ── Figure 1 : Frontière de Pareto ──────────────────────────────────────────

def plot_pareto():
    points = _load_pareto_points()
    pareto_points = _compute_pareto_frontier(points)
    pareto_ids = {point.run_id for point in pareto_points}

    fig, ax = plt.subplots(figsize=(7.8, 4.8))
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E5E7EB", linewidth=0.75)

    for point in points:
        is_pareto = point.run_id in pareto_ids
        x_val = point.cost_usd
        y_val = point.accuracy_pct

        if is_pareto:
            ax.scatter(
                x_val,
                y_val,
                s=150,
                marker="o",
                facecolor="#2563EB",
                edgecolor="#1E3A8A",
                linewidth=1.0,
                zorder=3,
            )
        else:
            ax.scatter(
                x_val,
                y_val,
                s=120,
                marker="x",
                color="#9CA3AF",
                linewidths=2.0,
                zorder=3,
            )

        label_style = PARETO_LABEL_POSITIONS[point.run_id]
        label_color = "#2563EB" if is_pareto else "#6B7280"
        annotation = ax.annotate(
            _pareto_label(point.run_id),
            xy=(x_val, y_val),
            xytext=label_style["offset"],
            textcoords="offset points",
            ha=label_style["ha"],
            va=label_style["va"],
            fontsize=8.0,
            color=label_color,
            fontweight="bold" if is_pareto else "normal",
            zorder=4,
        )
        annotation.set_path_effects([pe.withStroke(linewidth=3.5, foreground="white")])

    ax.plot(
        [point.cost_usd for point in pareto_points],
        [point.accuracy_pct for point in pareto_points],
        color="#DC2626",
        linestyle=(0, (4, 2)),
        linewidth=2.0,
        zorder=2,
    )

    ax.set_xlabel("Coût total du run (USD)", fontsize=11)
    ax.set_ylabel("Accuracy VF (%)", fontsize=11)
    ax.set_title("Frontière de Pareto coût-performance (alpha, n = 390)", fontsize=12, fontweight="bold")

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="o", linestyle="", color="#2563EB",
               markerfacecolor="#2563EB", markeredgecolor="#1E3A8A",
               markersize=8.5, label="Pareto-optimal"),
        Line2D([0], [0], marker="x", linestyle="", color="#9CA3AF",
               markersize=8.5, markeredgewidth=2, label="Dominé"),
        Line2D([0], [0], linestyle=(0, (4, 2)), color="#DC2626", linewidth=2,
               label="Frontière de Pareto"),
    ]
    ax.legend(
        handles=legend_elements,
        loc="lower right",
        fontsize=9,
        frameon=True,
        framealpha=0.95,
        edgecolor="#D1D5DB",
        facecolor="white",
    )

    ax.set_xlim(2.0, 8.35)
    ax.set_ylim(81.4, 88.8)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "ablation_alpha_pareto.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUTPUT_DIR / 'ablation_alpha_pareto.png'}")
    plt.close(fig)


# ── Figure 2 : Architecture (alma vs simple) à modèle constant ──────────────

def plot_architecture_comparison():
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    # Flash-lite
    ax = axes[0]
    flash_lite_ids = [158, 164, 165]
    configs = [
        (
            _display_name(RUN_SPECS_BY_ID[run_id], include_assist=True, width=14),
            RUN_SPECS_BY_ID[run_id].vf_pct,
            RUN_SPECS_BY_ID[run_id].cpp_cents,
            "#2563eb" if run_id == 158 else "#16a34a" if run_id == 164 else "#f59e0b",
        )
        for run_id in flash_lite_ids
    ]
    x = np.arange(len(configs))
    bars = ax.bar(x, [c[1] for c in configs], color=[c[3] for c in configs], width=0.6, edgecolor="white")
    for bar, c in zip(bars, configs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
                f"{c[1]}%\n{c[2]}¢", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([c[0] for c in configs], fontsize=9)
    ax.set_ylim(80, 89)
    ax.set_ylabel("VF Accuracy (%)")
    ax.set_title("Flash-Lite (tier économique)", fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", alpha=0.3)

    # Flash
    ax = axes[1]
    flash_ids = [159, 171, 167]
    configs = [
        (
            _display_name(RUN_SPECS_BY_ID[run_id], include_assist=True, width=14),
            RUN_SPECS_BY_ID[run_id].vf_pct,
            RUN_SPECS_BY_ID[run_id].cpp_cents,
            "#2563eb" if run_id == 159 else "#16a34a" if run_id == 171 else "#f59e0b",
        )
        for run_id in flash_ids
    ]
    x = np.arange(len(configs))
    bars = ax.bar(x, [c[1] for c in configs], color=[c[3] for c in configs], width=0.6, edgecolor="white")
    for bar, c in zip(bars, configs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
                f"{c[1]}%\n{c[2]}¢", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([c[0] for c in configs], fontsize=9)
    ax.set_ylim(80, 89)
    ax.set_title("Flash (tier intermédiaire)", fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Impact de l'architecture à modèle constant", fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "ablation_alpha_architecture.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUTPUT_DIR / 'ablation_alpha_architecture.png'}")
    plt.close(fig)


# ── Figure 3 : Impact ASSIST ────────────────────────────────────────────────

def plot_assist_impact():
    fig, ax = plt.subplots(figsize=(9, 5.5))

    pairs = [
        (
            _display_name(RUN_SPECS_BY_ID[164], include_assist=False),
            RUN_SPECS_BY_ID[164].vf_pct,
            RUN_SPECS_BY_ID[165].vf_pct,
        ),
        (
            _display_name(RUN_SPECS_BY_ID[171], include_assist=False),
            RUN_SPECS_BY_ID[171].vf_pct,
            RUN_SPECS_BY_ID[167].vf_pct,
        ),
    ]
    x = np.arange(len(pairs))
    w = 0.3
    bars_assist = ax.bar(x - w/2, [p[1] for p in pairs], w, label="Avec ASSIST", color="#16a34a", edgecolor="white")
    bars_no = ax.bar(x + w/2, [p[2] for p in pairs], w, label="Sans ASSIST", color="#f59e0b", edgecolor="white")

    for bar in bars_assist:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
                f"{bar.get_height()}%", ha="center", fontsize=10, fontweight="bold")
    for bar in bars_no:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.15,
                f"{bar.get_height()}%", ha="center", fontsize=10, fontweight="bold")

    # Delta annotations
    ax.annotate("-0.5pp", xy=(0, 85.6), fontsize=10, color="#dc2626", ha="center", fontweight="bold")
    ax.annotate("+2.5pp", xy=(1, 88.1), fontsize=10, color="#16a34a", ha="center", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([p[0] for p in pairs], fontsize=11)
    ax.set_ylim(82, 90)
    ax.set_ylabel("VF Accuracy (%)", fontsize=12)
    ax.set_title("Impact des questions ASSIST selon le tier modèle", fontsize=14, fontweight="bold")
    ax.legend(fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(axis="y", alpha=0.3)

    ax.text(0.5, 0.02,
            "Flash-lite : capacité insuffisante pour exploiter ASSIST\n"
            "Flash : ASSIST apporte +2.5pp — le modèle exploite les questions d'observation",
            transform=ax.transAxes, ha="center", fontsize=9, style="italic", color="#666")

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "ablation_alpha_assist_impact.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUTPUT_DIR / 'ablation_alpha_assist_impact.png'}")
    plt.close(fig)


# ── Figure 4 : Tableau récapitulatif 3 axes ─────────────────────────────────

def plot_summary_table():
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.axis("off")

    headers = ["Run", "Architecture", "Modèle", "ASSIST", "VF%", "Cat%", "Strat%", "¢/post", "Posts", "Pareto"]

    sorted_runs = sorted(RUN_SPECS, key=lambda run: run.cpp_cents)
    pareto_ids = {run.run_id for run in _compute_pareto_frontier(RUN_SPECS)}

    cell_text = []
    cell_colors = []
    for run in sorted_runs:
        is_pareto = run.run_id in pareto_ids
        row = [
            str(run.run_id),
            run.mode_label,
            run.tier_label,
            _assist_label_text(run.assist_label),
            f"{run.vf_pct:.1f}%",
            f"{run.cat_pct:.1f}%",
            f"{run.strat_pct:.1f}%",
            f"{run.cpp_cents:.2f}",
            str(run.n_posts),
            "★" if is_pareto else "",
        ]
        cell_text.append(row)
        if is_pareto:
            cell_colors.append(["#f0fdf4"] * len(headers))
        else:
            cell_colors.append(["white"] * len(headers))

    table = ax.table(
        cellText=cell_text,
        colLabels=headers,
        cellColours=cell_colors,
        colColours=["#1e3a5f"] * len(headers),
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)

    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_text_props(color="white", fontweight="bold")
        cell.set_edgecolor("#ddd")

    ax.set_title("Ablation Alpha — Résultats complets (8 configurations × 390 posts)",
                 fontsize=13, fontweight="bold", pad=20)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "ablation_alpha_summary.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUTPUT_DIR / 'ablation_alpha_summary.png'}")
    plt.close(fig)


if __name__ == "__main__":
    print("Génération des figures d'ablation alpha...")
    plot_pareto()
    plot_architecture_comparison()
    plot_assist_impact()
    plot_summary_table()
    print("Done.")
