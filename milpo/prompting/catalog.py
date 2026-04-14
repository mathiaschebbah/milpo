"""Labels de classification MILPO chargés depuis les YAML du vault.

Les prompts vivent désormais 100% dans `milpo.prompts` (code) + YAML vault
(taxonomie + questions). Ce module ne sert plus qu'à exposer la liste des
labels par axe pour un scope donné, consommée par `build_classifier_tool`
pour injecter l'enum.
"""

from __future__ import annotations

from milpo.taxonomy_renderer import load_taxonomy_yaml


def build_labels(conn, scope: str) -> dict[str, list[str]]:
    del conn
    return {
        "category": [c["class"] for c in load_taxonomy_yaml("CATEGORY")],
        "visual_format": [f["class"] for f in load_taxonomy_yaml(scope)],
        "strategy": [s["class"] for s in load_taxonomy_yaml("STRATEGY")],
    }
