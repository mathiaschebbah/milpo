"""Renderer de taxonomie YAML → texte canonique pour injection dans les prompts."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# Fallback : vault Obsidian
OBSIDIAN_TAXONOMY_DIR = "/Users/mathias/Desktop/Vaults/memoire-v2/Descriptions"


def _resolve_taxonomy_dir() -> Path:
    """Résout le dossier de taxonomie : env, repo local, puis vault Obsidian."""
    for candidate in (
        os.environ.get("MILPO_TAXONOMY_DIR", ""),
        str(Path(__file__).resolve().parent.parent / "Descriptions"),
        OBSIDIAN_TAXONOMY_DIR,
    ):
        if candidate:
            p = Path(candidate)
            if p.is_dir():
                return p
    raise FileNotFoundError(
        "Dossier de taxonomie introuvable : "
        f"{os.environ.get('MILPO_TAXONOMY_DIR', '')!r}, "
        f"{Path(__file__).resolve().parent.parent / 'Descriptions'} "
        f"ni {OBSIDIAN_TAXONOMY_DIR}"
    )


def load_taxonomy_yaml(scope: str) -> list[dict]:
    """Charge toutes les fiches YAML d'un scope canonique."""
    taxonomy_dir = _resolve_taxonomy_dir() / scope.upper()
    if not taxonomy_dir.is_dir():
        raise FileNotFoundError(f"Dossier taxonomie introuvable : {taxonomy_dir}")

    classes = []
    for yaml_file in sorted(taxonomy_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "class" in data:
            classes.append(data)
    return classes


def _render_signature_line(entry: dict) -> str:
    if "signature_visuelle" in entry:
        return f"SIGNATURE_VISUELLE: {entry['signature_visuelle']}"
    if "signature" in entry:
        return f"SIGNATURE: {entry['signature']}"
    raise KeyError(f"Champ signature manquant pour la classe {entry.get('class', '?')}")


def render_taxonomy(classes: list[dict]) -> str:
    """Rend une liste de fiches taxonomiques en texte canonique pour le modèle."""
    blocks = []
    for c in classes:
        lines = [
            f"CLASS: {c['class']}",
            _render_signature_line(c),
            f"SIGNAL_OBLIGATOIRE: {c['signal_obligatoire']}",
        ]
        if "caption_signal" in c:
            patterns = c["caption_signal"].get("patterns", [])
            patterns_str = ", ".join(f'"{p}"' for p in patterns)
            lines.append(f"CAPTION_SIGNAL: chercher {patterns_str}")
        lines.append("EXCLUT:")
        for ex in c.get("exclut", []):
            lines.append(f"- {ex['class']}: {ex['reason']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_taxonomy_for_scope(scope: str) -> str:
    """Charge et rend la taxonomie d'un scope en une seule étape."""
    classes = load_taxonomy_yaml(scope)
    return render_taxonomy(classes)


# ─── Questions ASSIST ───────────────────────────────────────────────────────

OBSIDIAN_QUESTIONS_DIR = "/Users/mathias/Desktop/Vaults/memoire-v2/Questions"


def _resolve_questions_dir() -> Path:
    """Résout le dossier des questions ASSIST."""
    for candidate in (
        os.environ.get("MILPO_QUESTIONS_DIR", ""),
        str(Path(__file__).resolve().parent.parent / "Questions"),
        OBSIDIAN_QUESTIONS_DIR,
    ):
        if candidate:
            p = Path(candidate)
            if p.is_dir():
                return p
    raise FileNotFoundError("Dossier de questions ASSIST introuvable")


def load_questions_yaml(scope: str) -> list[dict]:
    """Charge les questions ASSIST d'un scope."""
    questions_dir = _resolve_questions_dir()
    yaml_file = questions_dir / f"{scope}.yaml"
    if not yaml_file.exists():
        raise FileNotFoundError(f"Questions ASSIST introuvables : {yaml_file}")
    with open(yaml_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("keys", [])


def render_questions(keys: list[dict]) -> str:
    """Rend les questions ASSIST en texte pour le prompt d'Alma."""
    blocks = []
    for k in keys:
        if k.get("type") == "free_text":
            blocks.append(f"{k['key']}\n{k['question']}\n[description courte]")
        elif k.get("type") == "integer":
            blocks.append(f"{k['key']}\n{k['question']}\n[entier]")
        else:
            values_str = " / ".join(k.get("allowed_values", []))
            blocks.append(f"{k['key']}\n{k['question']}\n[{values_str}]")
    return "\n\n".join(blocks)


def render_questions_for_scope(scope: str) -> str:
    """Charge et rend les questions ASSIST d'un scope en une seule étape."""
    keys = load_questions_yaml(scope)
    return render_questions(keys)
