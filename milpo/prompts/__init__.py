"""Prompts ASSIST centralisés.

Source de vérité des blocs de prompt utilisés en inférence MILPO :
- `alma` : percepteur multimodal (Template A du vault Obsidian)
- `classifier` : décisionneur text-only (Template B du vault Obsidian)

Les blocs sont des variables str composables. L'assemblage vers le format
OpenAI `messages` (list[dict] avec roles) vit dans `milpo.agent_common`.
"""

from milpo.prompts import alma, classifier

__all__ = ["alma", "classifier"]
