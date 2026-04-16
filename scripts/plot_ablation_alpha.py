"""Génère les graphiques d'analyse de l'ablation alpha pour le mémoire.

Produit 4 figures dans docs/ :
1. Frontière de Pareto coût-performance (VF%)
2. Comparaison architectures à modèle constant
3. Impact ASSIST (avec vs sans) à modèle constant
4. Tableau récapitulatif complet (3 axes)
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
})

# ── Données alpha (extraites de la BDD) ─────────────────────────────────────

RUNS = [
    # (run_id, mode, tier, assist, vf%, cat%, strat%, cost_usd, cpp_cents, n_posts, errors)
    (158, "alma",   "flash-lite",  "ASSIST",    83.8, 92.8, 96.9, 3.67, 0.94, 390, 0),
    (159, "alma",   "flash",       "ASSIST",    83.6, 92.8, 96.9, 4.62, 1.18, 390, 0),
    (160, "alma",   "full-flash",  "ASSIST",    86.7, 93.3, 96.7, 7.72, 1.98, 390, 0),
    (161, "alma",   "qwen",        "ASSIST",    82.2, 93.4, 95.8, 2.33, 0.62, 377, 13),
    (164, "simple", "flash-lite",  "ASSIST",    84.9, 89.5, 97.4, 3.25, 0.83, 390, 0),
    (165, "simple", "flash-lite",  "no-assist", 85.4, 91.8, 97.4, 3.05, 0.78, 390, 0),
    (167, "simple", "flash",       "no-assist", 85.3, 90.5, 98.2, 4.92, 1.27, 389, 1),
    (171, "simple", "flash",       "ASSIST",    87.8, 89.6, 98.4, 5.18, 1.34, 386, 4),
]

COLORS = {
    ("alma", "ASSIST"):       "#2563eb",
    ("simple", "ASSIST"):     "#16a34a",
    ("simple", "no-assist"):  "#f59e0b",
}

MARKERS = {
    "flash-lite": "o",
    "flash": "s",
    "full-flash": "D",
    "qwen": "^",
}

OUT = "/Users/mathias/Desktop/mémoire-v2/docs"


def _label(r):
    mode, tier, assist = r[1], r[2], r[3]
    s = f"{mode} {tier}"
    if assist == "no-assist":
        s += " (no-assist)"
    return s


# ── Figure 1 : Frontière de Pareto ──────────────────────────────────────────

def plot_pareto():
    fig, ax = plt.subplots(figsize=(10, 7))

    pareto_ids = {161, 165, 171}
    pareto_points = [(r[7], r[4]) for r in RUNS if r[0] in pareto_ids]
    pareto_points.sort()

    for r in RUNS:
        rid = r[0]
        is_pareto = rid in pareto_ids
        x_val, y_val = r[8], r[4]

        x_val = r[7]  # cost total ($)

        if is_pareto:
            ax.scatter(x_val, y_val, c="#2563eb", marker="o", s=180, zorder=5,
                       edgecolors="#2563eb", linewidths=1.5)
        else:
            ax.scatter(x_val, y_val, c="#aaa", marker="x", s=120, zorder=5,
                       linewidths=2)

        label = f"{_label(r)}\n(run {rid})"
        offset_x, offset_y = 0.04, 0.0
        ha = "left"
        if rid == 165:
            offset_y = -0.5
        elif rid == 164:
            offset_y = 0.4
        elif rid == 167:
            offset_y = -0.5
        elif rid == 160:
            offset_x = -0.04
            ha = "right"
        elif rid == 161:
            offset_y = -0.5
        elif rid == 171:
            offset_y = 0.4

        color = "#2563eb" if is_pareto else "#888"
        ax.annotate(label, (x_val, y_val),
                    xytext=(x_val + offset_x, y_val + offset_y),
                    fontsize=8, color=color,
                    fontweight="bold" if is_pareto else "normal")

    px, py = zip(*pareto_points)
    ax.plot(px, py, color="#e74c3c", linestyle="--", linewidth=2,
            alpha=0.7, zorder=2)

    ax.set_xlabel("Coût par run ($)", fontsize=13)
    ax.set_ylabel("Visual Format Accuracy (%)", fontsize=13)
    ax.set_title("Frontière coût-performance", fontsize=15, fontweight="bold")

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2563eb",
               markeredgecolor="#2563eb", markersize=11, label="Pareto-optimal"),
        Line2D([0], [0], marker="x", color="#aaa", markersize=10,
               linewidth=0, markeredgewidth=2, label="Dominé"),
        Line2D([0], [0], linestyle="--", color="#e74c3c", linewidth=2,
               alpha=0.7, label="Frontière efficiente"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=10,
              framealpha=0.9, edgecolor="#ddd")

    ax.set_ylim(80, 90)
    ax.set_xlim(0, 9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f"))
    ax.grid(True, alpha=0.2)

    fig.tight_layout()
    fig.savefig(f"{OUT}/ablation_alpha_pareto.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUT}/ablation_alpha_pareto.png")
    plt.close(fig)


# ── Figure 2 : Architecture (alma vs simple) à modèle constant ──────────────

def plot_architecture_comparison():
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    # Flash-lite
    ax = axes[0]
    configs = [
        ("alma\nflash-lite", 83.8, 0.94, "#2563eb"),
        ("simple ASSIST\nflash-lite", 84.9, 0.83, "#16a34a"),
        ("simple no-assist\nflash-lite", 85.4, 0.78, "#f59e0b"),
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
    configs = [
        ("alma\nflash", 83.6, 1.18, "#2563eb"),
        ("simple ASSIST\nflash", 87.8, 1.34, "#16a34a"),
        ("simple no-assist\nflash", 85.3, 1.27, "#f59e0b"),
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
    fig.savefig(f"{OUT}/ablation_alpha_architecture.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUT}/ablation_alpha_architecture.png")
    plt.close(fig)


# ── Figure 3 : Impact ASSIST ────────────────────────────────────────────────

def plot_assist_impact():
    fig, ax = plt.subplots(figsize=(9, 5.5))

    pairs = [
        ("simple flash-lite", 84.9, 85.4),
        ("simple flash", 87.8, 85.3),
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
    fig.savefig(f"{OUT}/ablation_alpha_assist_impact.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUT}/ablation_alpha_assist_impact.png")
    plt.close(fig)


# ── Figure 4 : Tableau récapitulatif 3 axes ─────────────────────────────────

def plot_summary_table():
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.axis("off")

    headers = ["Run", "Architecture", "Modèle", "ASSIST", "VF%", "Cat%", "Strat%", "¢/post", "Posts", "Pareto"]

    sorted_runs = sorted(RUNS, key=lambda r: r[8])

    pareto_ids = {161, 165, 171}

    cell_text = []
    cell_colors = []
    for r in sorted_runs:
        is_pareto = r[0] in pareto_ids
        row = [
            str(r[0]),
            r[1],
            r[2],
            r[3],
            f"{r[4]:.1f}%",
            f"{r[5]:.1f}%",
            f"{r[6]:.1f}%",
            f"{r[8]:.2f}",
            str(r[9]),
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
    fig.savefig(f"{OUT}/ablation_alpha_summary.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUT}/ablation_alpha_summary.png")
    plt.close(fig)


if __name__ == "__main__":
    print("Génération des figures d'ablation alpha...")
    plot_pareto()
    plot_architecture_comparison()
    plot_assist_impact()
    plot_summary_table()
    print("Done.")
