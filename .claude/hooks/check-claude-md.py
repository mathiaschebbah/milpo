#!/usr/bin/env python3
"""PostToolUse hook — rappelle de mettre à jour CLAUDE.md après un git commit."""

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

    message = """**Rappel : vérifie si CLAUDE.md et docs/ doivent être mis à jour.**

1. **Audit avec sub-agent** : lance un sub-agent Explore en background pour comparer les fichiers `docs/` avec l'état actuel du code et du projet. Le sub-agent doit vérifier :
   - `docs/architecture.md` vs le code réel (apps/backend/, apps/frontend/, hilpo/)
   - `docs/schema.md` vs le schéma BDD actuel (tables, colonnes, contraintes)
   - `docs/phases.md` vs l'avancement réel (annotations, phases implémentées)
   - `docs/stack.md` vs les dépendances réelles (pyproject.toml, package.json)
   - `docs/data.md` vs les données en BDD (nombre de posts, formats, splits)
   - `docs/evaluation.md` vs le protocole décrit (métriques, ablations, baselines)
   - `docs/conventions.md` vs les hooks et skills réellement configurés
   Signaler les incohérences trouvées.
2. Revois ce qui a été fait dans ce commit (fichiers créés/modifiés, décisions prises).
3. Utilise AskUserQuestion pour présenter les changements détectés + incohérences. Toujours proposer "Rien à mettre à jour".
4. Si confirmé : mets à jour les docs/ concernés, incrémente la version CLAUDE.md, ajoute au changelog, commit séparé avec `docs: update CLAUDE.md`."""

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }))


if __name__ == "__main__":
    main()
