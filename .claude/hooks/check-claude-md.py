#!/usr/bin/env python3
"""PreToolUse hook — vérifie si CLAUDE.md doit être mis à jour avant un git commit."""

import json
import sys


def main():
    input_data = json.load(sys.stdin)
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Ne s'active que sur git commit (gère git -C /path commit)
    if tool_name != "Bash" or not ("git" in command and "commit" in command):
        print(json.dumps({}))
        return

    # Si c'est déjà un commit docs: update CLAUDE.md, laisser passer
    if "docs: update CLAUDE.md" in command:
        print(json.dumps({}))
        return

    message = """**Avant de commiter, vérifie si CLAUDE.md doit être mis à jour.**

**Étape 1 — Analyse :**
Revois ce qui a été fait (fichiers créés/modifiés, décisions prises, stack changée, schéma évolué, phase avancée).

**Étape 2 — Confirmation humaine :**
Utilise AskUserQuestion (multiSelect: true) pour présenter les changements détectés. Inclure toujours "Rien à mettre à jour".

**Étape 3 — Si changements confirmés :**
1. Mettre à jour les fichiers dans `docs/`
2. Incrémenter la version dans `CLAUDE.md`
3. Ajouter une ligne au changelog
4. Inclure CLAUDE.md + docs/ dans CE commit (git add avant de commiter)

**Si "Rien à mettre à jour"** : commiter normalement."""

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
