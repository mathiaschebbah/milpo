#!/usr/bin/env python3
"""Stop hook — rappelle à l'agent de vérifier CLAUDE.md avant de terminer."""

import json
import sys

def main():
    message = """Avant de terminer, tu DOIS maintenir la documentation du projet.

**Étape 1 — Analyse automatique :**
Revois ce qui a été fait pendant cette session (fichiers créés/modifiés, décisions prises, stack changée, schéma évolué, phase avancée, conventions établies, données ajoutées).

**Étape 2 — Confirmation humaine :**
Utilise AskUserQuestion (multiSelect: true) pour présenter les changements détectés. Les options doivent décrire concrètement ce qui a changé (ex: "Stack: modèle confirmé → Qwen 3.5", "Phase 1: statut → en cours"). Inclure toujours l'option "Rien à mettre à jour".

**Étape 3 — Si l'utilisateur confirme des changements :**
1. Mettre à jour les fichiers concernés dans `docs/`
2. Incrémenter la version dans `CLAUDE.md` (patch: 1.0 → 1.1 pour ajouts, minor: 1.1 → 2.0 pour changements structurels)
3. Ajouter une ligne au changelog dans `CLAUDE.md`
4. Git commit avec message : `docs: update CLAUDE.md v{version} — {résumé des changements}`

**Si "Rien à mettre à jour"** : ne rien faire, terminer normalement."""

    result = {
        "decision": "block",
        "reason": message
    }

    print(json.dumps(result))

if __name__ == "__main__":
    main()
