"""dspy_baseline — DSPy MIPROv2 appliqué au problème MILPO.

Pipeline :
1. extract_features_dev.py (dans scripts/) : génère les features descripteur
   pour les posts dev annotés
2. data.py : charge (annotations + features cachées) → list[dspy.Example]
3. pipeline.py : signatures et modules DSPy (modes constrained et free)
4. optimize.py : MIPROv2 zero-shot sur le dev split → programme compilé
5. evaluate_native.py : évaluation des programmes compilés via runtime DSPy
6. import_to_db.py : extrait les instructions optimisées et les insère dans
   prompt_versions avec source='dspy_constrained' ou 'dspy_free'
7. (lancement de scripts/run_baseline.py --prompts dspy_*) : évaluation
   apples-to-apples via le runtime MILPO

Voir README.md pour la motivation, l'architecture et les caveats.
"""
