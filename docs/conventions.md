# Conventions

## Collaboration

- **AskUserQuestion intensif** : utiliser AskUserQuestion pour valider les choix, clarifier les ambiguïtés et confirmer les directions avant d'agir. Ne pas deviner, demander.
- **Français avec accents** : tout contenu en français (README, docs, commentaires, messages de commit) doit utiliser les accents corrects (é, è, à, ù, etc.). Toujours relire avant d'écrire un fichier.

## Hooks d'interaction

- **Hook PreToolUse sur git commit** ([`.claude/hooks/check-claude-md.py`](../.claude/hooks/check-claude-md.py)) : avant chaque `git commit`, l'agent analyse les changements, propose une mise à jour de CLAUDE.md via AskUserQuestion, et inclut les docs dans le commit si l'humain valide. Les commits `docs: update CLAUDE.md` passent sans blocage (évite la boucle infinie).
