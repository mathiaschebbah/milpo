"""Diagramme architecture ASSIST : Alma (4 calls) vs Simple (1 call).

Schématise les blocs d'entrée (persona, contexte, YAML taxonomies, grille
d'observation, procédures par axe), les appels LLM, et les sorties.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.spines.bottom": False,
    "savefig.dpi": 300,
})

# Palette
BLUE = "#2563EB"
BLUE_LIGHT = "#DBEAFE"
GREEN = "#059669"
GREEN_LIGHT = "#D1FAE5"
AMBER = "#D97706"
AMBER_LIGHT = "#FEF3C7"
PURPLE = "#7C3AED"
PURPLE_LIGHT = "#EDE9FE"
GREY = "#6B7280"
GREY_LIGHT = "#F3F4F6"
RED = "#DC2626"

def box(ax, x, y, w, h, color_face, color_edge, text, fontsize=8, text_color="black", bold=False):
    patch = FancyBboxPatch((x, y), w, h,
                            boxstyle="round,pad=0.02,rounding_size=0.02",
                            facecolor=color_face, edgecolor=color_edge,
                            linewidth=1.0)
    ax.add_patch(patch)
    weight = "bold" if bold else "normal"
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, color=text_color, fontweight=weight,
            wrap=True)

def arrow(ax, x1, y1, x2, y2, color=GREY, style="-|>", linestyle="-"):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                         arrowstyle=style, mutation_scale=12,
                         color=color, linewidth=1.0, linestyle=linestyle)
    ax.add_patch(a)


def draw_alma(ax):
    ax.set_title("Architecture Alma — 4 appels LLM\n(percepteur multimodal + 3 classifieurs text-only)",
                  fontsize=11, fontweight="bold", pad=12)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13)
    ax.axis("off")

    # Input assets
    box(ax, 0.2, 11.5, 4.4, 1.3, GREY_LIGHT, GREY,
        "INPUTS\nImages (1..20) + Caption + Date",
        fontsize=9, bold=True)

    # Alma descriptor call
    box(ax, 0.2, 9.0, 4.4, 2.2, BLUE_LIGHT, BLUE,
        "Appel 1 : Alma descripteur (multimodal)\n"
        "— Persona + Contexte\n"
        "— Grille d'observation YAML (14-11 clés FEED/REELS)\n"
        "— Images + Caption\n"
        "→ Description textuelle structurée key:value",
        fontsize=7.5)

    # Description output
    box(ax, 0.2, 7.2, 4.4, 1.5, GREEN_LIGHT, GREEN,
        "Description textuelle\n"
        "OVERLAY_SLIDE_1: texte actualité\n"
        "CHIFFRE_DOMINANT: non\n"
        "CAPTION_APPEL_ACTION: oui\n...",
        fontsize=7)

    # 3 classifiers
    box(ax, 0.2, 4.5, 1.35, 2.2, PURPLE_LIGHT, PURPLE,
        "Appel 2\nClassifier VF\n(text-only)\n"
        "+ Taxonomie FEED/REELS\n(40 ou 17 classes)\n"
        "+ Procédure VF",
        fontsize=6.5)
    box(ax, 1.75, 4.5, 1.35, 2.2, PURPLE_LIGHT, PURPLE,
        "Appel 3\nClassifier CAT\n(text-only)\n"
        "+ Taxonomie CAT\n(15 classes)\n"
        "+ Procédure CAT",
        fontsize=6.5)
    box(ax, 3.3, 4.5, 1.35, 2.2, PURPLE_LIGHT, PURPLE,
        "Appel 4\nClassifier STRAT\n(text-only)\n"
        "+ Taxonomie STRAT\n(2 classes)\n"
        "+ Procédure STRAT",
        fontsize=6.5)

    # Outputs
    box(ax, 0.2, 2.2, 1.35, 1.5, AMBER_LIGHT, AMBER,
        "Label VF\n+ reasoning\n+ confidence",
        fontsize=7)
    box(ax, 1.75, 2.2, 1.35, 1.5, AMBER_LIGHT, AMBER,
        "Label CAT\n+ reasoning\n+ confidence",
        fontsize=7)
    box(ax, 3.3, 2.2, 1.35, 1.5, AMBER_LIGHT, AMBER,
        "Label STRAT\n+ reasoning\n+ confidence",
        fontsize=7)

    box(ax, 0.2, 0.2, 4.4, 1.4, "white", "black",
        "3 labels par post\nstockés en BDD (predictions + api_calls)",
        fontsize=8, bold=True)

    # Arrows
    arrow(ax, 2.4, 11.5, 2.4, 11.2, GREY)  # input -> alma
    arrow(ax, 2.4, 9.0, 2.4, 8.7, BLUE)    # alma -> desc
    arrow(ax, 2.4, 7.2, 0.85, 6.7, GREEN)  # desc -> cls VF
    arrow(ax, 2.4, 7.2, 2.42, 6.7, GREEN)  # desc -> cls CAT
    arrow(ax, 2.4, 7.2, 3.98, 6.7, GREEN)  # desc -> cls STRAT
    arrow(ax, 0.85, 4.5, 0.85, 3.7, PURPLE)
    arrow(ax, 2.42, 4.5, 2.42, 3.7, PURPLE)
    arrow(ax, 3.98, 4.5, 3.98, 3.7, PURPLE)
    arrow(ax, 2.4, 2.2, 2.4, 1.6, AMBER)

    # Legend / note
    box(ax, 5.2, 7.0, 4.6, 4.5, "#FAFAFA", GREY,
        "CARACTÉRISTIQUES DE ALMA\n\n"
        "• Percepteur / classifieurs séparés\n"
        "  (division du travail)\n\n"
        "• La grille ASSIST guide Alma\n"
        "  dans l'observation structurée\n\n"
        "• Les classifieurs sont text-only :\n"
        "  ils ne voient pas les images\n\n"
        "• 4 appels LLM par post\n  (1 multimodal + 3 text)\n\n"
        "• Parallélisation possible\n  des 3 classifieurs",
        fontsize=7.5)


def draw_simple(ax):
    ax.set_title("Architecture Simple — 1 appel LLM\n(classifieur multimodal all-in-one)",
                  fontsize=11, fontweight="bold", pad=12)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13)
    ax.axis("off")

    # Inputs
    box(ax, 0.2, 11.5, 4.4, 1.3, GREY_LIGHT, GREY,
        "INPUTS\nImages (1..20) + Caption + Date",
        fontsize=9, bold=True)

    # System block
    box(ax, 0.2, 9.7, 4.4, 1.6, BLUE_LIGHT, BLUE,
        "SYSTEM\nPersona Alma + Contexte tâche 3 axes\n"
        "+ Règles de sortie (reasoning + label enum)",
        fontsize=7.5)

    # User block - détaillé
    box(ax, 0.2, 4.0, 4.4, 5.5, AMBER_LIGHT, AMBER,
        "USER MESSAGE\n\n"
        "[optionnel] Grille d'observation ASSIST\n(14 clés FEED ou 11 REELS)\n\n"
        "Taxonomie VF : 40 classes FEED ou 17 REELS\n"
        "(CLASS / SIGNATURE_VISUELLE /\nSIGNAL_OBLIGATOIRE / EXCLUT)\n\n"
        "Taxonomie CAT : 15 classes\n(CLASS / SIGNATURE / SIGNAL_OBLIGATOIRE)\n\n"
        "Taxonomie STRAT : 2 classes\n\n"
        "[optionnel] Procédures par axe\n(format > thème / sujet / intention)\n\n"
        "+ Images multimodales\n"
        "+ Date + Caption",
        fontsize=6.8)

    # LLM call
    box(ax, 0.2, 2.2, 4.4, 1.4, PURPLE_LIGHT, PURPLE,
        "Appel LLM unique\n(tool call structuré 3 labels)",
        fontsize=8, bold=True)

    # Output
    box(ax, 0.2, 0.2, 4.4, 1.6, AMBER_LIGHT, AMBER,
        "3 labels simultanés\nVF + CAT + STRAT\n+ reasoning unique + confidence",
        fontsize=8)

    # Arrows
    arrow(ax, 2.4, 11.5, 2.4, 11.3, GREY)
    arrow(ax, 2.4, 9.7, 2.4, 9.5, BLUE)
    arrow(ax, 2.4, 4.0, 2.4, 3.6, AMBER)
    arrow(ax, 2.4, 2.2, 2.4, 1.8, PURPLE)

    # Legend
    box(ax, 5.2, 5.5, 4.6, 6.0, "#FAFAFA", GREY,
        "CARACTÉRISTIQUES DE SIMPLE\n\n"
        "• 1 seul appel multimodal\n  qui produit 3 labels d'un coup\n\n"
        "• Le modèle accède aux images\n  PENDANT la décision\n  (pas de perte descriptive)\n\n"
        "• Grille & procédures injectées\n  directement dans le prompt\n\n"
        "• Coût = prompt partagé + 1 output\n  Beaucoup moins de tokens\n  que 4 appels Alma\n\n"
        "• Ablation factorielle :\n"
        "  --no-grille + --no-procedure\n"
        "  permet d'isoler chaque composant",
        fontsize=7.5)


def main():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 10))
    draw_alma(ax1)
    draw_simple(ax2)
    fig.suptitle("Deux architectures MILPO pour la classification multimodale 3-axes",
                 fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout()
    fig.savefig("/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures/architecture.png",
                 dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig("/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures/architecture.pdf",
                 bbox_inches="tight", facecolor="white")
    print("architecture.{png,pdf} written")
    plt.close(fig)


if __name__ == "__main__":
    main()
