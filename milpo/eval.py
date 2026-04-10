"""Métriques d'évaluation pour le moteur MILPO."""

from __future__ import annotations


def accuracy(matches: list[bool]) -> float:
    """Taux de match simple."""
    if not matches:
        return 0.0
    return sum(matches) / len(matches)
