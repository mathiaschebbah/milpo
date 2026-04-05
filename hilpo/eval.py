"""Métriques d'évaluation pour le moteur HILPO."""

from __future__ import annotations

from collections import defaultdict


def accuracy(matches: list[bool]) -> float:
    """Taux de match simple."""
    if not matches:
        return 0.0
    return sum(matches) / len(matches)


def accuracy_by_axis(
    results: list[dict],
) -> dict[str, float]:
    """Accuracy par axe. Chaque dict : {axis, match}."""
    by_axis: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_axis[r["axis"]].append(r["match"])
    return {axis: accuracy(matches) for axis, matches in by_axis.items()}


def rolling_accuracy(matches: list[bool], window: int = 50) -> list[float]:
    """Rolling window accuracy. Les premières entrées utilisent une fenêtre croissante."""
    result: list[float] = []
    running_sum = 0
    for i, m in enumerate(matches):
        running_sum += int(m)
        start = max(0, i - window + 1)
        if i >= window:
            running_sum -= int(matches[start - 1])
        w = min(i + 1, window)
        result.append(running_sum / w)
    return result


def f1_macro(y_true: list[str], y_pred: list[str]) -> float:
    """F1 macro via sklearn."""
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def confusion_pairs(
    y_true: list[str], y_pred: list[str],
) -> dict[tuple[str, str], int]:
    """Retourne un dict (true, pred) → count pour les paires d'erreurs."""
    pairs: dict[tuple[str, str], int] = defaultdict(int)
    for t, p in zip(y_true, y_pred):
        if t != p:
            pairs[(t, p)] += 1
    return dict(sorted(pairs.items(), key=lambda x: -x[1]))
