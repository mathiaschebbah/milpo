"""Matrice d'accord/désaccord entre les 4 modes d'ablation factorielle.

Source de vérité : BDD locale, table predictions pour les runs
- 185 : no-ASSIST  (grille=F, procedure=F)
- 187 : grille seule (grille=T, procedure=F)
- 188 : procedure seule (grille=F, procedure=T)
- 181 : ASSIST complet (grille=T, procedure=T)

Restreint à agent='visual_format' sur test only (305 posts uniques au test).
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

RUNS = {
    "no-ASSIST": 185,
    "grille seule": 187,
    "procedure seule": 188,
    "ASSIST complet": 181,
}


def fetch_matches(conn, run_id):
    rows = conn.execute(
        "SELECT ig_media_id, match FROM predictions "
        "WHERE simulation_run_id = %s AND agent = 'visual_format'",
        (run_id,),
    ).fetchall()
    return {pid: bool(m) for pid, m in rows}


def main():
    with psycopg.connect(DSN) as conn:
        per_run = {name: fetch_matches(conn, rid) for name, rid in RUNS.items()}

    common = set.intersection(*(set(m.keys()) for m in per_run.values()))
    n = len(common)
    print(f"Intersection posts : {n}")

    rows = []
    for pid in common:
        pattern = tuple(per_run[name][pid] for name in RUNS.keys())
        rows.append(pattern)

    from collections import Counter
    counter = Counter(rows)

    all_patterns = sorted(counter.keys(), key=lambda p: (-sum(p), p))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.5),
                                    gridspec_kw={"width_ratios": [1.0, 1.2]})

    # ── Panel 1 : heatmap des 16 patterns ─────────────────────────────
    labels = list(RUNS.keys())
    M = np.zeros((16, 4))
    counts = np.zeros(16, dtype=int)
    for i, pat in enumerate(all_patterns):
        M[i] = [1 if x else 0 for x in pat]
        counts[i] = counter[pat]

    im = ax1.imshow(M, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)
    ax1.set_xticks(range(4))
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax1.set_yticks(range(len(all_patterns)))
    ax1.set_yticklabels([f"#{counts[i]:>3d}" for i in range(len(all_patterns))], fontsize=8)
    ax1.set_title(f"Distribution des 16 patterns d'accord\nsur {n} posts test communs",
                  fontsize=10, fontweight="bold")

    for i in range(len(all_patterns)):
        for j in range(4):
            v = "OK" if M[i, j] else "no"
            ax1.text(j, i, v, ha="center", va="center", fontsize=9,
                     color="white" if M[i, j] > 0.5 else "black", fontweight="bold")

    # ── Panel 2 : bars horizontales sorted by count ───────────────────
    sorted_pairs = sorted(counter.items(), key=lambda x: -x[1])
    y_labels = []
    y_counts = []
    colors = []
    for pat, c in sorted_pairs:
        repr_str = " ".join("OK" if x else "no" for x in pat)
        y_labels.append(repr_str + f"  (n={c})")
        y_counts.append(c)
        n_ok = sum(pat)
        if n_ok == 4: colors.append("#10B981")          # tous ✓
        elif n_ok == 0: colors.append("#991B1B")        # tous ✗
        elif pat == (False, False, False, True): colors.append("#F59E0B")  # synergie pure
        elif pat == (True, True, True, False): colors.append("#EF4444")    # ASSIST casse
        else: colors.append("#6B7280")

    y_pos = np.arange(len(y_labels))
    ax2.barh(y_pos, y_counts, color=colors, edgecolor="white")
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(y_labels, fontsize=7.5, family="monospace")
    ax2.set_xlabel("Nombre de posts")
    ax2.invert_yaxis()
    ax2.set_title(f"Patterns ordonnés par fréquence\n(colonnes = {', '.join(labels)})",
                  fontsize=10, fontweight="bold")

    # Annotation synergie pure
    for i, (pat, c) in enumerate(sorted_pairs):
        if pat == (False, False, False, True):
            ax2.annotate(f"SYNERGIE PURE\n({c} posts)",
                         xy=(c, i), xytext=(c + 25, i - 1.5),
                         fontsize=8, color="#F59E0B", fontweight="bold",
                         arrowprops=dict(arrowstyle="->", color="#F59E0B"))

    fig.suptitle("Matrice 2⁴ des patterns d'accord — ablation factorielle Gemini 3 Flash sur test",
                 fontsize=12, fontweight="bold", y=0.99)

    plt.tight_layout()
    out = "/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures"
    fig.savefig(f"{out}/confusion_4modes.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(f"{out}/confusion_4modes.pdf", bbox_inches="tight", facecolor="white")
    print("confusion_4modes.{png,pdf} written")
    plt.close(fig)


if __name__ == "__main__":
    main()
