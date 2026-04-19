"""Accuracy VF en fonction du rendement moyen (pp / centime) — alpha et test.

r(a) = (VF - 80) / (coût par post en centimes)

Source : BDD locale. Calculs sur final_accuracy_visual_format et total_cost_usd
rapportés au nombre de posts classifiés (DISTINCT ig_media_id dans predictions).
"""

from __future__ import annotations

import os
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
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

LABELS = {
    158: "alma flash-lite",   159: "alma flash",         160: "alma full-flash",
    161: "alma qwen",          164: "simple fl-lite ASSIST",
    165: "simple fl-lite\nno-ASSIST", 167: "simple flash\nno-ASSIST",
    171: "simple flash\nASSIST",
    172: "alma flash-lite",   176: "simple fl-lite\nASSIST",
    177: "simple fl-lite\nno-ASSIST", 178: "alma qwen",
    181: "simple flash\nASSIST", 182: "alma flash",
    183: "alma full-flash",   185: "simple flash\nno-ASSIST",
}

# Normalisation cache-off pour le run 185 (estimé via tokens vs run 167)
NORM_COST = {185: 5.21}


def fetch(conn, ids):
    rows = conn.execute(
        "SELECT sr.id, sr.final_accuracy_visual_format, sr.total_cost_usd, "
        "(SELECT COUNT(DISTINCT ig_media_id) FROM predictions "
        " WHERE simulation_run_id=sr.id AND agent='visual_format') AS n "
        "FROM simulation_runs sr WHERE sr.id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    return [(r[0], float(r[1])*100, NORM_COST.get(r[0], float(r[2])), int(r[3]))
              for r in rows]


def draw(ax, data, title):
    ax.set_axisbelow(True)
    ax.grid(True, color="#E5E7EB", linewidth=0.5, alpha=0.7)

    enriched = []
    for rid, vf, cost, n in data:
        cpp = 100 * cost / n if n > 0 else 0
        q = max(vf - 80, 0.001)
        r = q / cpp if cpp > 0 else 0
        enriched.append((rid, vf, cost, n, cpp, r))

    # Pareto : max r ET max vf
    pareto = set()
    for a in enriched:
        dominated = False
        for b in enriched:
            if b[0] == a[0]: continue
            if b[5] >= a[5] and b[1] >= a[1] and (b[5] > a[5] or b[1] > a[1]):
                dominated = True
                break
        if not dominated: pareto.add(a[0])

    # trace pareto line sorted by r
    pts = sorted([(e[5], e[1]) for e in enriched if e[0] in pareto])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if len(pts) >= 2:
        ax.plot(xs, ys, linestyle="--", color="#DC2626", linewidth=2.0, alpha=0.6)

    for rid, vf, cost, n, cpp, r in enriched:
        is_par = rid in pareto
        marker = "o" if is_par else "X"
        size = 200 if is_par else 130
        face = "#2563EB" if is_par else "#9CA3AF"
        edge = "#1E40AF" if is_par else "#6B7280"
        ax.scatter(r, vf, s=size, marker=marker,
                     facecolor=face, edgecolor=edge, linewidth=1.2, zorder=5)
        txt = ax.annotate(f"{LABELS.get(rid, rid)}\n({rid})",
                           xy=(r, vf),
                           xytext=(8, 6), textcoords="offset points",
                           fontsize=7.5,
                           color="#1E40AF" if is_par else "#4B5563",
                           fontweight="bold" if is_par else "normal")
        txt.set_path_effects([pe.withStroke(linewidth=3, foreground="white")])

    ax.set_xlabel(r"Rendement moyen $r = (VF - 80) / \mathrm{coût/post}$  (pp par centime)",
                    fontsize=10)
    ax.set_ylabel("Accuracy Visual Format (%)", fontsize=10.5)
    ax.set_title(title, fontsize=11, fontweight="bold")


def main():
    alpha_ids = [158, 159, 160, 161, 164, 165, 167, 171]
    test_ids = [172, 176, 177, 178, 181, 182, 183, 185]

    with psycopg.connect(DSN) as conn:
        a_data = fetch(conn, alpha_ids)
        t_data = fetch(conn, test_ids)

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    draw(axes[0], a_data, "Alpha — accuracy vs efficience (r)")
    draw(axes[1], t_data, "Test — accuracy vs efficience (r)\n[185 coût normalisé cache-off]")
    fig.suptitle("Frontière efficience × performance — duale du Pareto coût/accuracy",
                  fontsize=13, fontweight="bold", y=1.00)
    plt.tight_layout()
    out = "/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures"
    fig.savefig(f"{out}/efficiency.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(f"{out}/efficiency.pdf", bbox_inches="tight", facecolor="white")
    print("efficiency.{png,pdf} written")
    plt.close(fig)


if __name__ == "__main__":
    main()
