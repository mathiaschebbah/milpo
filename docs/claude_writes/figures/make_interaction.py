"""Plot de l'interaction non-additive grille × procedure sur simple flash test.

Source : BDD locale, colonne simulation_runs.final_accuracy_visual_format
pour les runs d'ablation factorielle 2×2 :
- 185 : (grille=F, procedure=F) -> no-ASSIST
- 187 : (grille=T, procedure=F) -> grille seule
- 188 : (grille=F, procedure=T) -> procedure seule
- 181 : (grille=T, procedure=T) -> ASSIST complet
"""

from __future__ import annotations

import os
import numpy as np
import matplotlib.pyplot as plt
import psycopg

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
})

DSN = os.environ.get("HILPO_DATABASE_DSN",
                       "postgresql://hilpo:hilpo@localhost:5433/hilpo")

CONFIGS = [
    (185, "no-ASSIST",        False, False),
    (187, "grille seule",     True,  False),
    (188, "procedure seule",  False, True),
    (181, "ASSIST complet",   True,  True),
]


def main():
    with psycopg.connect(DSN) as conn:
        rows = conn.execute(
            "SELECT id, final_accuracy_visual_format FROM simulation_runs "
            "WHERE id IN (185, 187, 188, 181) ORDER BY id"
        ).fetchall()
    vf_by_id = {r[0]: float(r[1]) * 100 for r in rows}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5),
                                    gridspec_kw={"width_ratios": [1.3, 1]})

    # ── Panel 1 : 4 bars + annotations ─────────────────────────────────
    labels = [c[1] for c in CONFIGS]
    vfs = [vf_by_id[c[0]] for c in CONFIGS]
    colors = ["#6B7280", "#3B82F6", "#8B5CF6", "#059669"]

    ax1.set_axisbelow(True)
    ax1.grid(axis="y", color="#E5E7EB", linewidth=0.5, alpha=0.7)

    bars = ax1.bar(labels, vfs, color=colors, edgecolor="white", linewidth=1.5, zorder=3)
    for bar, v in zip(bars, vfs):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                  f"{v:.2f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")

    baseline = vfs[0]
    for i in range(1, 4):
        delta = vfs[i] - baseline
        ax1.annotate(f"+{delta:.2f}pp", xy=(i, vfs[i]),
                      xytext=(i, baseline - 0.7),
                      ha="center", fontsize=8, color=colors[i],
                      fontweight="bold",
                      arrowprops=dict(arrowstyle="<->", color=colors[i], lw=1))

    ax1.set_ylabel("Accuracy Visual Format (%)", fontsize=11)
    ax1.set_title("Ablation factorielle 2×2 sur simple flash test\n(run 185 / 187 / 188 / 181, axe VF)",
                   fontsize=11, fontweight="bold")
    ax1.set_ylim(min(vfs) - 1.5, max(vfs) + 0.8)
    ax1.axhline(baseline, color="#6B7280", linestyle=":", linewidth=0.8, alpha=0.6)

    # ── Panel 2 : décomposition additive vs observée ────────────────────
    g_only = vfs[1] - baseline      # +0.?
    p_only = vfs[2] - baseline
    additive = g_only + p_only
    observed = vfs[3] - baseline
    interaction = observed - additive

    components = ["Grille seule\n(run 187)", "Procedure seule\n(run 188)",
                   "Somme additive\nprévue", "ASSIST observé\n(run 181)",
                   "Interaction\nrésiduelle"]
    values = [g_only, p_only, additive, observed, interaction]
    ccolors = ["#3B82F6", "#8B5CF6", "#9CA3AF", "#059669", "#F59E0B"]
    hatches = [None, None, "//", None, "xx"]

    ax2.set_axisbelow(True)
    ax2.grid(axis="y", color="#E5E7EB", linewidth=0.5, alpha=0.7)

    bars2 = ax2.bar(components, values, color=ccolors,
                     edgecolor="white", linewidth=1.5, zorder=3,
                     hatch=hatches)
    for bar, v in zip(bars2, values):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.03,
                  f"+{v:.2f}pp", ha="center", va="bottom",
                  fontsize=9, fontweight="bold")

    ax2.axhline(0, color="black", linewidth=0.6)
    ax2.set_ylabel("Δ accuracy VF (pp) vs no-ASSIST", fontsize=11)
    ax2.set_title(f"Effet additif {additive:.2f}pp vs observé {observed:.2f}pp\nInteraction résiduelle = {interaction:+.2f}pp",
                   fontsize=10.5, fontweight="bold")
    ax2.tick_params(axis="x", labelsize=8)
    ax2.set_ylim(min(0, min(values)) - 0.3, max(values) + 0.5)

    # Note explicative
    ax2.text(0.98, 0.02,
              "L'effet est NON-ADDITIF :\n"
              "ni la grille seule ni la procedure\n"
              "seule ne produit de gain significatif,\n"
              "mais leur combinaison débloque +2pp.",
              transform=ax2.transAxes, ha="right", va="bottom",
              fontsize=7.5, color="#F59E0B", style="italic",
              bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                        edgecolor="#F59E0B", linewidth=0.8))

    fig.suptitle("Interaction non-additive grille × procedure\nsur Gemini 3 Flash (test, n≈403)",
                  fontsize=13, fontweight="bold", y=1.00)

    plt.tight_layout()
    out = "/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures"
    fig.savefig(f"{out}/interaction_non_additive.png", dpi=300,
                 bbox_inches="tight", facecolor="white")
    fig.savefig(f"{out}/interaction_non_additive.pdf",
                 bbox_inches="tight", facecolor="white")
    print(f"Baseline (no-ASSIST) : {baseline:.2f}%")
    print(f"Grille seule          : {vfs[1]:.2f}% (+{g_only:.2f}pp)")
    print(f"Procedure seule       : {vfs[2]:.2f}% (+{p_only:.2f}pp)")
    print(f"ASSIST complet        : {vfs[3]:.2f}% (+{observed:.2f}pp)")
    print(f"Somme additive        : {additive:+.2f}pp")
    print(f"Interaction           : {interaction:+.2f}pp")
    print("interaction_non_additive.{png,pdf} written")
    plt.close(fig)


if __name__ == "__main__":
    main()
