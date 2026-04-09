#!/usr/bin/env python3
"""PostToolUse hook — rappelle de mettre à jour CLAUDE.md après un git commit.

Depuis v3.3 : ne demande plus d'auditer docs/ (les docs narratives ont été
supprimées car elles dérivaient). Le hook se contente de rappeler que
CLAUDE.md (index + changelog) doit rester à jour quand le commit est
structurellement significatif (nouvelle migration, refactor, reset de doc,
changement de protocole, etc.).
"""

import json
import sys


def main():
    input_data = json.load(sys.stdin)
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # Ne s'active que sur git commit
    if tool_name != "Bash" or not ("git" in command and "commit" in command):
        print(json.dumps({}))
        return

    # Si c'est déjà un commit docs: update CLAUDE.md, pas besoin de rappeler
    if "docs: update CLAUDE.md" in command:
        print(json.dumps({}))
        return

    message = """**Rappel CLAUDE.md (post-commit).**

Philosophie v3.3 : la source de vérité est le code + la BDD, pas des résumés narratifs. docs/ est volontairement minimal. Ne régénère PAS de doc narrative pour « documenter » ce commit.

Vérifie si ce commit justifie une entrée changelog dans CLAUDE.md :

- ✅ OUI si : nouvelle migration BDD, refactor structurel, changement de protocole / de stack, reset de doc, décision projet importante, pivot de positionnement.
- ❌ NON si : fix de bug mineur, tweak de prompt, changement d'UI, itération normale.

Si OUI :
1. Incrémente la version CLAUDE.md (patch : +0.1).
2. Ajoute une ligne au changelog qui explique le *pourquoi* (pas juste le *quoi*).
3. Commit séparé `docs: update CLAUDE.md vX.Y — <résumé court>`.

Si NON : ne fais rien, continue le travail en cours.

**Ne touche pas aux fichiers supprimés en v3.3** (architecture.md, stack.md, schema.md, data.md, phases.md, planning.md, conventions.md, agent_perspective.md, prompts_v0.md). S'ils doivent exister à nouveau, demande à Mathias d'abord via AskUserQuestion."""

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
