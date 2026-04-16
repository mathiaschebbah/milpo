#!/usr/bin/env python3
"""Plot factorial returns for the alpha ablation runs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
import numpy as np

from plot_ablation_alpha import RUN_SPECS_BY_ID


OUTPUT_DIR = Path("/Users/mathias/Desktop/mémoire-v2/docs/assets")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Georgia", "Times New Roman"],
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "#FAFAFA",
        "savefig.dpi": 300,
        "axes.linewidth": 0.8,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
    }
)

BLUE = "#2563EB"
BLUE_DARK = "#1E40AF"
GREEN = "#059669"
AMBER = "#D97706"
RED = "#DC2626"
SLATE = "#475569"


def _vf(run_id: int) -> float:
    return RUN_SPECS_BY_ID[run_id].vf_pct


def _cost(run_id: int) -> float:
    return RUN_SPECS_BY_ID[run_id].cost_usd


def _annotate_segment(ax, x0, y0, x1, y1, text, color, *, dy=0.55, dx=0.0) -> None:
    xm = (x0 + x1) / 2 + dx
    ym = (y0 + y1) / 2 + dy
    txt = ax.text(
        xm,
        ym,
        text,
        color=color,
        fontsize=8.8,
        fontweight="bold",
        ha="center",
        va="bottom",
    )
    txt.set_path_effects([pe.withStroke(linewidth=2.8, foreground="white")])


def plot_factorial_returns() -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.8))

    # Panel 1: returns of model investment at constant architecture family
    ax1.set_axisbelow(True)
    ax1.grid(True, color="#E5E7EB", linewidth=0.6, alpha=0.8)

    alma_runs = [161, 158, 159, 160]
    simple_no_assist_runs = [165, 167]
    simple_assist_runs = [164, 171]

    for run_ids, color, marker, label in (
        (alma_runs, BLUE, "o", "Alma"),
        (simple_no_assist_runs, AMBER, "s", "Simple sans ASSIST"),
        (simple_assist_runs, GREEN, "D", "Simple + ASSIST"),
    ):
        xs = [_cost(run_id) for run_id in run_ids]
        ys = [_vf(run_id) for run_id in run_ids]
        ax1.plot(
            xs,
            ys,
            color=color,
            linewidth=2.1,
            marker=marker,
            markersize=6.5,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label=label,
            zorder=3,
        )

    for run_id, dx, dy, ha in (
        (161, 0.04, -0.55, "left"),
        (158, 0.04, 0.18, "left"),
        (159, 0.04, -0.42, "left"),
        (160, 0.05, 0.20, "left"),
        (165, -0.04, 0.18, "right"),
        (167, 0.05, -0.18, "left"),
        (164, 0.05, -0.48, "left"),
        (171, 0.05, 0.18, "left"),
    ):
        txt = ax1.text(
            _cost(run_id) + dx,
            _vf(run_id) + dy,
            f"{run_id}",
            fontsize=8.0,
            color=SLATE,
            ha=ha,
            va="center",
        )
        txt.set_path_effects([pe.withStroke(linewidth=2.5, foreground="white")])

    _annotate_segment(ax1, _cost(161), _vf(161), _cost(158), _vf(158), "+1.6 pp", BLUE, dy=0.50)
    _annotate_segment(ax1, _cost(158), _vf(158), _cost(159), _vf(159), "-0.3 pp", BLUE, dy=-0.85)
    _annotate_segment(ax1, _cost(159), _vf(159), _cost(160), _vf(160), "+3.1 pp", BLUE, dy=0.55)
    _annotate_segment(ax1, _cost(165), _vf(165), _cost(167), _vf(167), "~0 pp", AMBER, dy=0.42)
    _annotate_segment(ax1, _cost(164), _vf(164), _cost(171), _vf(171), "+3.0 pp", GREEN, dy=0.48)

    ax1.set_xlabel("M (investissement modele, USD / run)", fontsize=11)
    ax1.set_ylabel("Accuracy Visual Format (%)", fontsize=11)
    ax1.set_title("Rendements factoriels de M\n(a architecture constante)", fontsize=12.5, fontweight="bold")
    ax1.set_xlim(2.0, 8.2)
    ax1.set_ylim(81.4, 88.9)
    ax1.xaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax1.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax1.legend(loc="lower right", fontsize=8.8, frameon=True, edgecolor="#D1D5DB")

    # Panel 2: returns of architecture/orchestration at constant model family
    ax2.set_axisbelow(True)
    ax2.grid(True, color="#E5E7EB", linewidth=0.6, alpha=0.8)

    architecture_levels = ["Simple\nsans ASSIST", "Simple\n+ ASSIST", "Alma\n2 etages"]
    x = np.arange(len(architecture_levels))

    flash_lite_runs = [165, 164, 158]
    flash_runs = [167, 171, 160]

    for run_ids, color, marker, label in (
        (flash_lite_runs, BLUE, "o", "Modele = Flash-Lite"),
        (flash_runs, RED, "s", "Modele = Flash"),
    ):
        ys = [_vf(run_id) for run_id in run_ids]
        ax2.plot(
            x,
            ys,
            color=color,
            linewidth=2.2,
            marker=marker,
            markersize=6.5,
            markeredgecolor="white",
            markeredgewidth=0.9,
            label=label,
            zorder=3,
        )

    for xi, run_id, dy, color in (
        (0, 165, 0.18, BLUE),
        (1, 164, -0.55, BLUE),
        (2, 158, -0.42, BLUE),
        (0, 167, -0.28, RED),
        (1, 171, 0.18, RED),
        (2, 160, 0.20, RED),
    ):
        txt = ax2.text(
            xi,
            _vf(run_id) + dy,
            f"{_vf(run_id):.1f}%",
            fontsize=8.0,
            color=color,
            ha="center",
            va="center",
        )
        txt.set_path_effects([pe.withStroke(linewidth=2.5, foreground="white")])

    _annotate_segment(ax2, x[0], _vf(165), x[1], _vf(164), "-0.5 pp", BLUE, dy=0.55, dx=-0.03)
    _annotate_segment(ax2, x[1], _vf(164), x[2], _vf(158), "-1.0 pp", BLUE, dy=-1.05, dx=0.03)
    _annotate_segment(ax2, x[0], _vf(167), x[1], _vf(171), "+2.5 pp", RED, dy=0.62, dx=-0.02)
    _annotate_segment(ax2, x[1], _vf(171), x[2], _vf(160), "-1.2 pp", RED, dy=0.55, dx=0.03)

    ax2.set_xticks(x)
    ax2.set_xticklabels(architecture_levels, fontsize=9.5)
    ax2.set_xlabel("A (profondeur d'orchestration)", fontsize=11)
    ax2.set_title("Rendements factoriels de A\n(a modele constant)", fontsize=12.5, fontweight="bold")
    ax2.set_ylim(81.4, 88.9)
    ax2.yaxis.set_major_locator(mticker.MultipleLocator(1.0))
    ax2.legend(loc="lower right", fontsize=8.8, frameon=True, edgecolor="#D1D5DB")

    ax2.text(
        0.98,
        0.04,
        "Le rendement de A depend du tier modele :\nnegatif a Flash-Lite, positif puis decroissant a Flash.",
        transform=ax2.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.6,
        color=SLATE,
    )

    fig.suptitle(
        "Ablation alpha (8 runs) — rendements factoriels de A et M",
        fontsize=14.2,
        fontweight="bold",
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    png_path = OUTPUT_DIR / "alpha_factorial_returns.png"
    pdf_path = OUTPUT_DIR / "alpha_factorial_returns.pdf"
    fig.savefig(png_path, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    print(f"  -> {png_path}")
    print(f"  -> {pdf_path}")
    plt.close(fig)


if __name__ == "__main__":
    plot_factorial_returns()
