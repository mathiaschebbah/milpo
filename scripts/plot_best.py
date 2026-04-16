"""Figure principale du mémoire : Pareto + rendements marginaux pairés.

Deux panneaux côte à côte :
- Gauche : frontière de Pareto coût-performance avec 8 configs, 3 Pareto-optimaux
- Droite : rendements marginaux entre paires Pareto adjacentes (¢/pp)

Style académique publication-ready, demi-page A4 landscape.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.gridspec import GridSpec

# ── Style ────────────────────────────────────────────────────────────────────

plt.rcParams.update({
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
})

# ── Palette ──────────────────────────────────────────────────────────────────

BLUE = "#2563EB"
BLUE_DARK = "#1E40AF"
GREY = "#9CA3AF"
RED = "#DC2626"
GREEN = "#059669"
AMBER = "#D97706"
SLATE = "#475569"

# ── Données alpha ────────────────────────────────────────────────────────────

# (run_id, label, vf%, cost_usd, is_pareto, architecture, assist)
RUNS = [
    (161, "alma qwen",                82.2, 2.33, True,  "alma",   True),
    (165, "simple flash-lite\nsans ASSIST", 85.4, 3.05, True,  "simple", False),
    (164, "simple flash-lite\nASSIST",      84.9, 3.25, False, "simple", True),
    (158, "alma flash-lite",          83.8, 3.67, False, "alma",   True),
    (159, "alma flash",               83.6, 4.62, False, "alma",   True),
    (167, "simple flash\nsans ASSIST",      85.3, 4.92, False, "simple", False),
    (171, "simple flash\nASSIST",           87.8, 5.18, True,  "simple", True),
    (160, "alma full-flash",          86.7, 7.72, False, "alma",   True),
]

PARETO = [(r[3], r[2]) for r in RUNS if r[4]]  # (cost, vf%)
PARETO.sort()

OUT = "/Users/mathias/Desktop/mémoire-v2/docs"


def main():
    fig = plt.figure(figsize=(14, 6.2))
    gs = GridSpec(1, 2, width_ratios=[2.2, 1], wspace=0.35, left=0.07, right=0.96,
                  top=0.88, bottom=0.12)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    # ── Panel 1 : Pareto frontier ────────────────────────────────────────

    ax1.set_axisbelow(True)
    ax1.grid(True, color="#E5E7EB", linewidth=0.5, alpha=0.7)

    # Pareto frontier line
    px, py = zip(*PARETO)
    ax1.plot(px, py, color=RED, linestyle="--", linewidth=2.0, alpha=0.6, zorder=2)

    # Dominated region shading
    ax1.fill_between(
        [px[0] - 0.5] + list(px) + [px[-1] + 3],
        [py[0]] + list(py) + [py[-1]],
        [80] * (len(px) + 2),
        alpha=0.04, color=RED, zorder=1,
    )

    # Plot each point
    for run_id, label, vf, cost, is_pareto, arch, assist in RUNS:
        if is_pareto:
            ax1.scatter(cost, vf, s=200, marker="o", facecolor=BLUE,
                       edgecolor=BLUE_DARK, linewidth=1.2, zorder=5)
        else:
            ax1.scatter(cost, vf, s=130, marker="X", color=GREY,
                       linewidths=1.5, zorder=4)

    # Labels with smart positioning
    label_config = {
        161: {"offset": (-12, -14), "ha": "right"},
        165: {"offset": (10, 8), "ha": "left"},
        164: {"offset": (10, -2), "ha": "left"},
        158: {"offset": (10, 2), "ha": "left"},
        159: {"offset": (10, -6), "ha": "left"},
        167: {"offset": (10, -8), "ha": "left"},
        171: {"offset": (8, 10), "ha": "left"},
        160: {"offset": (-10, 4), "ha": "right"},
    }

    for run_id, label, vf, cost, is_pareto, arch, assist in RUNS:
        cfg = label_config[run_id]
        color = BLUE_DARK if is_pareto else SLATE
        weight = "bold" if is_pareto else "normal"
        size = 8.5 if is_pareto else 7.5

        txt = ax1.annotate(
            f"{label}\n({run_id})",
            xy=(cost, vf),
            xytext=cfg["offset"],
            textcoords="offset points",
            ha=cfg["ha"], va="center",
            fontsize=size, color=color, fontweight=weight,
            linespacing=0.9,
        )
        txt.set_path_effects([pe.withStroke(linewidth=3, foreground="white")])

    # Marginal return annotations on the frontier
    for i in range(len(PARETO) - 1):
        x0, y0 = PARETO[i]
        x1, y1 = PARETO[i + 1]
        delta_cost = x1 - x0
        delta_vf = y1 - y0
        marginal = delta_cost / delta_vf if delta_vf > 0 else float("inf")

        mid_x = (x0 + x1) / 2
        mid_y = (y0 + y1) / 2

        ax1.annotate(
            f"${marginal:.2f}/pp",
            xy=(mid_x, mid_y),
            xytext=(0, -18),
            textcoords="offset points",
            ha="center", va="top",
            fontsize=8, color=RED, fontweight="bold",
            fontstyle="italic",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                     edgecolor=RED, alpha=0.9, linewidth=0.8),
        )

    ax1.set_xlabel("Coût total du run (USD)", fontsize=11.5, labelpad=8)
    ax1.set_ylabel("Accuracy Visual Format (%)", fontsize=11.5, labelpad=8)
    ax1.set_title("Frontière de Pareto coût-performance", fontsize=13,
                  fontweight="bold", pad=12)

    ax1.set_xlim(1.5, 8.5)
    ax1.set_ylim(81, 89)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BLUE,
               markeredgecolor=BLUE_DARK, markersize=10, label="Pareto-optimal"),
        Line2D([0], [0], marker="X", color=GREY, markersize=9,
               linewidth=0, markeredgewidth=1.5, label="Dominé"),
        Line2D([0], [0], linestyle="--", color=RED, linewidth=2,
               alpha=0.6, label="Frontière efficiente"),
    ]
    ax1.legend(handles=legend_elements, loc="lower right", fontsize=9,
              framealpha=0.95, edgecolor="#ddd", fancybox=False)

    # ── Panel 2 : Rendements marginaux ───────────────────────────────────

    ax2.set_axisbelow(True)
    ax2.grid(axis="x", color="#E5E7EB", linewidth=0.5, alpha=0.7)

    transitions = []
    for i in range(len(PARETO) - 1):
        x0, y0 = PARETO[i]
        x1, y1 = PARETO[i + 1]
        delta_cost = x1 - x0
        delta_vf = y1 - y0
        marginal = delta_cost / delta_vf
        transitions.append({
            "label": f"{RUNS[[r[3] for r in RUNS].index(x0)][1].split(chr(10))[0]}\n-> {RUNS[[r[3] for r in RUNS].index(x1)][1].split(chr(10))[0]}",
            "delta_vf": delta_vf,
            "delta_cost": delta_cost,
            "marginal": marginal,
        })

    # Simpler labels
    bar_labels = [
        "alma qwen\n-> simple fl-lite",
        "simple fl-lite\n-> simple flash",
    ]
    marginals = [t["marginal"] for t in transitions]
    delta_vfs = [t["delta_vf"] for t in transitions]
    delta_costs = [t["delta_cost"] for t in transitions]

    y_pos = np.arange(len(transitions))
    colors = [GREEN, AMBER]

    bars = ax2.barh(y_pos, marginals, height=0.5, color=colors, edgecolor="white",
                    linewidth=1.5, zorder=3)

    for i, (bar, m, dv, dc) in enumerate(zip(bars, marginals, delta_vfs, delta_costs)):
        ax2.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"${m:.2f}/pp\n+{dv:.1f}pp pour +${dc:.2f}",
                va="center", ha="left", fontsize=8.5, color=colors[i],
                fontweight="bold", linespacing=1.3)

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(bar_labels, fontsize=9)
    ax2.set_xlabel("Coût marginal par point ($/pp)", fontsize=11, labelpad=8)
    ax2.set_title("Rendements marginaux\ndécroissants", fontsize=13,
                  fontweight="bold", pad=12)
    ax2.set_xlim(0, 1.4)
    ax2.invert_yaxis()

    # Annotation ratio
    ratio = marginals[1] / marginals[0]
    ax2.annotate(
        f"×{ratio:.1f}",
        xy=(0.6, 0.5), fontsize=22, fontweight="bold",
        color=SLATE, ha="center", va="center",
        xycoords="axes fraction", alpha=0.15,
    )

    # ── Global title ─────────────────────────────────────────────────────

    fig.suptitle(
        "Ablation factorielle — 8 configurations, 390 posts (alpha)",
        fontsize=14.5, fontweight="bold", y=0.97, color="#1E293B",
    )

    fig.savefig(f"{OUT}/ablation_alpha_main.png", dpi=300, bbox_inches="tight",
               facecolor="white")
    fig.savefig(f"{OUT}/ablation_alpha_main.pdf", bbox_inches="tight",
               facecolor="white")
    print(f"  -> {OUT}/ablation_alpha_main.png")
    print(f"  -> {OUT}/ablation_alpha_main.pdf")
    plt.close(fig)


if __name__ == "__main__":
    main()
