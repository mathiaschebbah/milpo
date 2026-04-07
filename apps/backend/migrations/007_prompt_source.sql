-- 007_prompt_source.sql
-- Ajoute une colonne `source` à prompt_versions pour distinguer les prompts
-- produits par différentes méthodes d'optimisation (humain, MILPO, DSPy...).
--
-- Permet à plusieurs sources d'avoir un prompt actif en parallèle dans le même
-- slot (agent, scope), ce qui ouvre la voie aux comparaisons baseline (DSPy
-- MIPROv2, APE, PromptWizard, etc.) à côté de la pipeline MILPO.
--
-- Sources prévues :
--   * 'human_v0'        — prompts seedés par migration 006 (default rétro-compatible)
--   * 'dspy_constrained' — DSPy MIPROv2 avec descriptions taxonomiques fixes
--   * 'dspy_free'       — DSPy MIPROv2 sans contrainte
--   * 'milpo'           — réservé pour les prompts issus de la boucle MILPO Phase 3
--
-- Migration purement schéma : aucun appel LLM, aucune donnée touchée hormis le
-- backfill explicite des rows existantes en 'human_v0'. Réversible via une 008
-- inverse (DROP COLUMN + recréation de l'index original).

BEGIN;

-- 1. Ajout de la colonne avec default rétro-compatible
ALTER TABLE prompt_versions
    ADD COLUMN source VARCHAR(30) NOT NULL DEFAULT 'human_v0';

-- 2. Backfill explicite (le DEFAULT couvre les nouveaux INSERT, pas forcément
--    les rows existantes selon la version PostgreSQL — on est explicite)
UPDATE prompt_versions SET source = 'human_v0' WHERE source IS NULL OR source = '';

-- 3. Reconstruction de l'index unique pour scoper par source
--    Avant : un seul prompt actif par (agent, scope)
--    Après : un seul prompt actif par (agent, scope, source)
DROP INDEX IF EXISTS idx_prompt_active;
CREATE UNIQUE INDEX idx_prompt_active
    ON prompt_versions (agent, scope, source) WHERE status = 'active';

-- 4. Mise à jour de la vue prompt_metrics pour inclure source dans le GROUP BY
--    Permet de comparer accuracy par (agent, scope, source) côte à côte
DROP VIEW IF EXISTS prompt_metrics;

CREATE VIEW prompt_metrics AS
SELECT
    pv.id AS prompt_version_id,
    pv.agent,
    pv.scope,
    pv.source,
    pv.version,
    pv.status,
    pv.created_at,
    p.simulation_run_id,
    COUNT(p.id) AS total_predictions,
    AVG(p.match::int) AS accuracy
FROM prompt_versions pv
LEFT JOIN predictions p ON p.prompt_version_id = pv.id
GROUP BY pv.id, pv.agent, pv.scope, pv.source, pv.version, pv.status, pv.created_at, p.simulation_run_id
ORDER BY pv.agent, pv.scope, pv.source, pv.version;

COMMIT;
