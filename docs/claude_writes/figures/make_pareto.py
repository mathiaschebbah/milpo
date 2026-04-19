"""Figures Pareto cout/accuracy pour alpha et test.

Source : BDD locale. Lit simulation_runs + predictions pour restreindre
aux ensembles disjoints alpha only / test only quand pertinent.

Produit 3 fichiers :
- pareto_alpha.png : 8 configs alpha (runs 158,159,160,161,164,165,167,171)
- pareto_test.png  : 8 configs test (runs 172,176,177,178,181,182,183,185)
- pareto_disjoint.png : alpha only & test only côte à côte
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
    158: "alma flash-lite",
    159: "alma flash",
    160: "alma full-flash",
    161: "alma qwen",
    164: "simple fl-lite\nASSIST",
    165: "simple fl-lite\nno-ASSIST",
    167: "simple flash\nno-ASSIST",
    171: "simple flash\nASSIST",
    172: "alma flash-lite",
    176: "simple fl-lite\nASSIST",
    177: "simple fl-lite\nno-ASSIST",
    178: "alma qwen",
    181: "simple flash\nASSIST",
    182: "alma flash",
    183: "alma full-flash",
    185: "simple flash\nno-ASSIST",
}

NORMALIZED_COST = {
    185: 5.21,   # normalisé cache-off (estimé à partir du ratio tokens avec 167)
}


def fetch_runs(conn, ids):
    q = (
        "SELECT id, final_accuracy_visual_format, total_cost_usd "
        "FROM simulation_runs WHERE id = ANY(%s)"
    )
    rows = conn.execute(q, (list(ids),)).fetchall()
    return {r[0]: (float(r[1]) * 100, float(r[2])) for r in rows}


def fetch_n_posts(conn, ids):
    q = (
        "SELECT simulation_run_id, COUNT(DISTINCT ig_media_id) "
        "FROM predictions WHERE simulation_run_id = ANY(%s) AND agent='visual_format' "
        "GROUP BY simulation_run_id"
    )
    rows = conn.execute(q, (list(ids),)).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def compute_pareto(points):
    """Pareto sur (coût croissant, accuracy maximale).
    points : list of tuples (id, cost, accuracy)
    Returns : sorted Pareto frontier and set of Pareto ids.
    """
    sorted_pts = sorted(points, key=lambda p: (p[1], -p[2]))
    pareto = []
    max_acc_so_far = -1
    for rid, c, a in sorted_pts:
        if a > max_acc_so_far:
            pareto.append((rid, c, a))
            max_acc_so_far = a
    ids = {p[0] for p in pareto}
    return pareto, ids


def draw_pareto_panel(ax, pts_by_id, pareto_ids, title, x_axis="Coût ($)", cost_normalized=None):
    ax.set_axisbelow(True)
    ax.grid(True, color="#E5E7EB", linewidth=0.5, alpha=0.7)

    # Pareto frontier line
    pareto_list = sorted([(rid, pts_by_id[rid][1], pts_by_id[rid][0])
                            for rid in pareto_ids],
                           key=lambda p: p[1])
    px = [p[1] for p in pareto_list]
    py = [p[2] for p in pareto_list]
    ax.plot(px, py, linestyle="--", color="#DC2626", linewidth=2.0, alpha=0.6)

    for rid, (acc, cost) in pts_by_id.items():
        effective_cost = (cost_normalized or {}).get(rid, cost)
        is_pareto = rid in pareto_ids
        marker = "o" if is_pareto else "X"
        size = 200 if is_pareto else 130
        face = "#2563EB" if is_pareto else "#9CA3AF"
        edge = "#1E40AF" if is_pareto else "#6B7280"
        ax.scatter(effective_cost, acc, s=size, marker=marker,
                     facecolor=face, edgecolor=edge, linewidth=1.3, zorder=5)
        lbl = LABELS.get(rid, str(rid))
        txt = ax.annotate(f"{lbl}\n(run {rid})",
                            xy=(effective_cost, acc),
                            xytext=(8, 6), textcoords="offset points",
                            fontsize=7.5,
                            color="#1E40AF" if is_pareto else "#4B5563",
                            fontweight="bold" if is_pareto else "normal")
        txt.set_path_effects([pe.withStroke(linewidth=3, foreground="white")])

    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel(x_axis, fontsize=10.5)
    ax.set_ylabel("Accuracy Visual Format (%)", fontsize=10.5)


def main():
    alpha_ids = [158, 159, 160, 161, 164, 165, 167, 171]
    test_ids = [172, 176, 177, 178, 181, 182, 183, 185]

    with psycopg.connect(DSN) as conn:
        all_runs = fetch_runs(conn, alpha_ids + test_ids)
        n_posts = fetch_n_posts(conn, alpha_ids + test_ids)

    # ── Figure : Pareto alpha & test, coût total ─────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    pts_alpha = {rid: all_runs[rid] for rid in alpha_ids}
    points = [(rid, v[1], v[0]) for rid, v in pts_alpha.items()]
    _, pareto_a = compute_pareto(points)
    draw_pareto_panel(axes[0], pts_alpha, pareto_a,
                        "Alpha (390 posts, runs 158-171)",
                        x_axis="Coût total du run ($)")

    pts_test = {rid: all_runs[rid] for rid in test_ids}
    points = [(rid, NORMALIZED_COST.get(rid, v[1]), v[0]) for rid, v in pts_test.items()]
    _, pareto_t = compute_pareto(points)
    # Adjust costs for display using normalized costs where defined
    pts_test_adj = {rid: (v[0], NORMALIZED_COST.get(rid, v[1])) for rid, v in pts_test.items()}
    draw_pareto_panel(axes[1], pts_test_adj, pareto_t,
                        "Test (405 posts, runs 172-185)\n[run 185 normalisé cache-off]",
                        x_axis="Coût total du run ($) — 185 normalisé",
                        cost_normalized=None)

    fig.suptitle("Frontière de Pareto coût × performance — 8 configurations × 2 datasets",
                  fontsize=13, fontweight="bold", y=1.00)
    plt.tight_layout()
    out = "/Users/mathias/Desktop/mémoire-v2/docs/claude_writes/figures"
    fig.savefig(f"{out}/pareto.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(f"{out}/pareto.pdf", bbox_inches="tight", facecolor="white")
    print("pareto.{png,pdf} written")
    print("Pareto alpha :", sorted(pareto_a))
    print("Pareto test  :", sorted(pareto_t))
    plt.close(fig)


if __name__ == "__main__":
    main()
