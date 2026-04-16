"""ELECTRE III — surclassement multicritère des 8 configurations alpha.

Méthode créée par Bernard Roy (LAMSADE, Paris-Dauphine, 1978).
Implémente : concordance, discordance, crédibilité, distillation descendante/ascendante.

6 critères :
  g1: VF accuracy (%)         — maximiser
  g2: Category accuracy (%)   — maximiser
  g3: Strategy accuracy (%)   — maximiser
  g4: Coût par run ($)        — minimiser
  g5: Fiabilité (1 - err/390) — maximiser
  g6: Nb appels API par post  — minimiser
"""

from __future__ import annotations

import numpy as np

# ── Alternatives (8 configs alpha) ───────────────────────────────────────────

NAMES = [
    "alma flash-lite",
    "alma flash",
    "alma full-flash",
    "alma qwen",
    "simple fl ASSIST",
    "simple fl no-assist",
    "simple flash no-assist",
    "simple flash ASSIST",
]

#                    VF%    Cat%   Strat%  Cost$   Fiab          NbAppels
PERF = np.array([
    [83.8,  92.8,  96.9,  3.67,  1.000,  4],  # alma flash-lite
    [83.6,  92.8,  96.9,  4.62,  1.000,  4],  # alma flash
    [86.7,  93.3,  96.7,  7.72,  1.000,  4],  # alma full-flash
    [82.2,  93.4,  95.8,  2.33,  0.967,  4],  # alma qwen
    [84.9,  89.5,  97.4,  3.25,  1.000,  1],  # simple fl ASSIST
    [85.4,  91.8,  97.4,  3.05,  1.000,  1],  # simple fl no-assist
    [85.3,  90.5,  98.2,  4.92,  0.997,  1],  # simple flash no-assist
    [87.8,  89.6,  98.4,  5.18,  0.990,  1],  # simple flash ASSIST
], dtype=float)

N_ALT = len(NAMES)
N_CRIT = PERF.shape[1]

# ── Paramètres ELECTRE III ───────────────────────────────────────────────────

# Poids (somme = 1)
WEIGHTS = np.array([0.35, 0.20, 0.10, 0.20, 0.10, 0.05])

# Sens : +1 = maximiser, -1 = minimiser
DIRECTION = np.array([1, 1, 1, -1, 1, -1], dtype=float)

# Seuils :       VF%   Cat%  Strat%  Cost$  Fiab   NbAppels
Q = np.array([   1.0,  1.0,   0.5,  0.50,  0.005,  0])    # indifférence
P = np.array([   3.0,  3.0,   1.5,  2.00,  0.020,  2])    # préférence
V = np.array([   6.0,  6.0,   3.0,  5.00,  0.050,  4])    # veto


def concordance_index(a: int, b: int) -> float:
    """Indice de concordance globale C(a,b)."""
    c = 0.0
    for j in range(N_CRIT):
        d = DIRECTION[j] * (PERF[a, j] - PERF[b, j])
        if d >= -Q[j]:
            cj = 1.0
        elif d <= -P[j]:
            cj = 0.0
        else:
            cj = (d + P[j]) / (P[j] - Q[j])
        c += WEIGHTS[j] * cj
    return c


def discordance_index(a: int, b: int, j: int) -> float:
    """Indice de discordance D_j(a,b) pour le critère j."""
    d = DIRECTION[j] * (PERF[a, j] - PERF[b, j])
    if d >= -P[j]:
        return 0.0
    if d <= -V[j]:
        return 1.0
    return (-d - P[j]) / (V[j] - P[j])


def credibility(a: int, b: int) -> float:
    """Degré de crédibilité sigma(a,b)."""
    c = concordance_index(a, b)
    sigma = c
    for j in range(N_CRIT):
        dj = discordance_index(a, b, j)
        if dj > c:
            sigma *= (1 - dj) / (1 - c) if c < 1.0 else 0.0
    return sigma


def build_credibility_matrix() -> np.ndarray:
    """Matrice de crédibilité N×N."""
    S = np.zeros((N_ALT, N_ALT))
    for a in range(N_ALT):
        for b in range(N_ALT):
            if a != b:
                S[a, b] = credibility(a, b)
    return S


def distillation_descendante(S: np.ndarray) -> list[list[int]]:
    """Distillation descendante : du meilleur au pire."""
    remaining = set(range(N_ALT))
    ranking = []
    lambda_cut = 0.7

    while remaining:
        qualified = []
        for a in remaining:
            dominated = False
            for b in remaining:
                if a == b:
                    continue
                if S[b, a] >= lambda_cut and S[a, b] < lambda_cut:
                    dominated = True
                    break
            if not dominated:
                qualified.append(a)
        if not qualified:
            lambda_cut -= 0.1
            if lambda_cut < 0.1:
                qualified = list(remaining)
        if qualified:
            ranking.append(sorted(qualified))
            remaining -= set(qualified)
            lambda_cut = 0.7
    return ranking


def distillation_ascendante(S: np.ndarray) -> list[list[int]]:
    """Distillation ascendante : du pire au meilleur."""
    remaining = set(range(N_ALT))
    ranking = []
    lambda_cut = 0.7

    while remaining:
        dominated_set = []
        for a in remaining:
            dominates_none = True
            for b in remaining:
                if a == b:
                    continue
                if S[a, b] >= lambda_cut and S[b, a] < lambda_cut:
                    dominates_none = False
                    break
            if dominates_none:
                dominated_set.append(a)
        if not dominated_set:
            lambda_cut -= 0.1
            if lambda_cut < 0.1:
                dominated_set = list(remaining)
        if dominated_set:
            ranking.append(sorted(dominated_set))
            remaining -= set(dominated_set)
            lambda_cut = 0.7
    return ranking


def final_ranking(desc: list[list[int]], asc: list[list[int]]) -> list[tuple[float, int]]:
    """Rang final = moyenne des rangs descendant et ascendant."""
    rank_desc = {}
    for i, group in enumerate(desc):
        for alt in group:
            rank_desc[alt] = i + 1

    rank_asc = {}
    for i, group in enumerate(reversed(asc)):
        for alt in group:
            rank_asc[alt] = i + 1

    scores = []
    for a in range(N_ALT):
        avg = (rank_desc.get(a, N_ALT) + rank_asc.get(a, N_ALT)) / 2.0
        scores.append((avg, a))
    scores.sort()
    return scores


OUT = "/Users/mathias/Desktop/mémoire-v2/docs"


def plot_results(S, desc, asc, final):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # Matrice de crédibilité
    ax = axes[0]
    im = ax.imshow(S, cmap="RdYlGn", vmin=0, vmax=1, aspect="equal")
    ax.set_xticks(range(N_ALT))
    ax.set_yticks(range(N_ALT))
    short = [n.replace("flash-lite", "fl").replace("no-assist", "no-a").replace("ASSIST", "ast")
             for n in NAMES]
    ax.set_xticklabels(short, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(short, fontsize=8)
    for i in range(N_ALT):
        for j in range(N_ALT):
            ax.text(j, i, f"{S[i,j]:.2f}", ha="center", va="center", fontsize=7,
                    color="white" if S[i, j] > 0.6 else "black")
    ax.set_title("Matrice de crédibilité σ(a,b)", fontweight="bold", fontsize=12)
    ax.set_xlabel("b (surclassé)")
    ax.set_ylabel("a (surclasse)")
    plt.colorbar(im, ax=ax, shrink=0.8)

    # Classement final
    ax = axes[1]
    ranks = [r for r, _ in final]
    names_sorted = [NAMES[a] for _, a in final]
    vf_sorted = [PERF[a, 0] for _, a in final]
    colors = ["#2563eb" if r == min(ranks) else "#16a34a" if r <= 2.5 else "#f59e0b" if r <= 4 else "#aaa"
              for r in ranks]
    bars = ax.barh(range(N_ALT), [N_ALT + 1 - r for r in ranks], color=colors, edgecolor="white")
    ax.set_yticks(range(N_ALT))
    ax.set_yticklabels([f"{n}  (VF={vf:.1f}%)" for n, vf in zip(names_sorted, vf_sorted)], fontsize=9)
    ax.set_xlabel("Score ELECTRE III (rang moyen inversé)", fontsize=11)
    ax.set_title("Classement ELECTRE III", fontweight="bold", fontsize=12)
    for i, (r, a) in enumerate(final):
        ax.text(N_ALT + 1 - r + 0.1, i, f"rang {r:.1f}", va="center", fontsize=9, fontweight="bold")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.2)

    fig.suptitle("Analyse multicritère ELECTRE III — Ablation Alpha (8 configurations)",
                 fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(f"{OUT}/ablation_alpha_electre.png", dpi=200, bbox_inches="tight")
    print(f"  -> {OUT}/ablation_alpha_electre.png")
    plt.close(fig)


if __name__ == "__main__":
    print("ELECTRE III — Ablation Alpha")
    print("=" * 60)

    S = build_credibility_matrix()

    print("\nMatrice de crédibilité σ(a,b) :")
    header = "           " + "  ".join(f"{n[:8]:>8s}" for n in NAMES)
    print(header)
    for i in range(N_ALT):
        row = f"{NAMES[i]:10s} " + "  ".join(f"{S[i,j]:8.3f}" for j in range(N_ALT))
        print(row)

    desc = distillation_descendante(S)
    print("\nDistillation descendante :")
    for i, group in enumerate(desc):
        print(f"  Rang {i+1}: {', '.join(NAMES[a] for a in group)}")

    asc = distillation_ascendante(S)
    print("\nDistillation ascendante :")
    for i, group in enumerate(asc):
        print(f"  Rang {i+1} (pire): {', '.join(NAMES[a] for a in group)}")

    final = final_ranking(desc, asc)
    print("\nClassement final (rang moyen) :")
    for rank, alt in final:
        print(f"  {rank:.1f}  {NAMES[alt]:30s}  VF={PERF[alt,0]:.1f}%  ${PERF[alt,7-4]:.2f}")

    print()
    plot_results(S, desc, asc, final)
    print("Done.")
