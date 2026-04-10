-- Migration 011: Support pipeline agentique A0 (Haiku + Opus advisor)
--
-- 1. predictions.prompt_version_id nullable (l'agent classifie lui-même, pas de prompt versionné)
-- 2. Table agent_traces : traces structurées du comportement de l'agent par post
-- 3. Vue compare_runs : comparaison rapide entre runs (A0 vs B0 etc.)

-- ── 1. Rendre prompt_version_id nullable ─────────────────────────
-- L'agent n'utilise pas de prompts versionnés — il raisonne avec ses tools.
-- La FK reste (valide quand non NULL), mais la contrainte NOT NULL est levée.

ALTER TABLE predictions ALTER COLUMN prompt_version_id DROP NOT NULL;


-- ── 2. Table agent_traces ────────────────────────────────────────
-- 1 row par post classifié par l'agent. Stocke :
--   - métriques agrégées (tokens, tools, advisor, latence)
--   - classifications avec confidence
--   - trace structurée JSONB (séquence d'événements queryable)
--
-- Format de la trace JSONB :
-- [
--   {"type": "tool_call", "phase": "category", "tool": "describe_media", "input": {}, "latency_ms": 3200},
--   {"type": "tool_call", "phase": "category", "tool": "get_taxonomy", "input": {"axis": "category"}},
--   {"type": "advisor_call", "phase": "visual_format"},
--   {"type": "classification", "phase": "category", "label": "news", "confidence": "high"},
--   ...
-- ]

CREATE TABLE agent_traces (
    id                      SERIAL PRIMARY KEY,
    simulation_run_id       INT NOT NULL REFERENCES simulation_runs(id),
    ig_media_id             BIGINT NOT NULL REFERENCES posts(ig_media_id),

    -- Métriques agrégées par post
    tool_calls              INT NOT NULL DEFAULT 0,
    advisor_calls           INT NOT NULL DEFAULT 0,
    input_tokens_executor   INT NOT NULL DEFAULT 0,
    output_tokens_executor  INT NOT NULL DEFAULT 0,
    input_tokens_advisor    INT NOT NULL DEFAULT 0,
    output_tokens_advisor   INT NOT NULL DEFAULT 0,
    input_tokens_descriptor INT NOT NULL DEFAULT 0,
    output_tokens_descriptor INT NOT NULL DEFAULT 0,
    latency_ms              INT NOT NULL DEFAULT 0,

    -- Classifications avec confidence
    category_label          VARCHAR(200),
    category_confidence     VARCHAR(10) CHECK (category_confidence IN ('high', 'medium', 'low')),
    visual_format_label     VARCHAR(200),
    visual_format_confidence VARCHAR(10) CHECK (visual_format_confidence IN ('high', 'medium', 'low')),
    strategy_label          VARCHAR(200),
    strategy_confidence     VARCHAR(10) CHECK (strategy_confidence IN ('high', 'medium', 'low')),

    -- Trace structurée (séquence d'événements)
    trace                   JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (simulation_run_id, ig_media_id)
);

CREATE INDEX idx_agent_traces_run ON agent_traces(simulation_run_id);
CREATE INDEX idx_agent_traces_post ON agent_traces(ig_media_id);


-- ── 3. Vue compare_runs ──────────────────────────────────────────
-- Comparaison rapide entre tous les runs complétés.
-- Usage : SELECT * FROM compare_runs;

CREATE OR REPLACE VIEW compare_runs AS
SELECT
    r.id                            AS run_id,
    r.config ->> 'name'             AS run_name,
    COALESCE(r.config ->> 'pipeline', 'milpo_classic') AS pipeline,
    r.final_accuracy_category       AS accuracy_cat,
    r.final_accuracy_visual_format  AS accuracy_vf,
    r.final_accuracy_strategy       AS accuracy_strat,
    r.total_cost_usd                AS cost_usd,
    r.total_api_calls,
    r.started_at,
    r.finished_at,
    EXTRACT(EPOCH FROM (r.finished_at - r.started_at))::int AS duration_s
FROM simulation_runs r
WHERE r.status = 'completed'
ORDER BY r.id;


-- ── 4. Fonction compare_runs_detail ──────────────────────────────
-- Comparaison post-par-post entre deux runs sur un axe donné.
-- Usage : SELECT * FROM compare_runs_detail(7, 8, 'category');
--   → montre pour chaque post : prédiction B0, prédiction A0, qui a raison.

CREATE OR REPLACE FUNCTION compare_runs_detail(
    run_a INT,
    run_b INT,
    target_axis TEXT DEFAULT 'category'
)
RETURNS TABLE (
    ig_media_id   BIGINT,
    pred_a        VARCHAR(200),
    match_a       BOOLEAN,
    pred_b        VARCHAR(200),
    match_b       BOOLEAN,
    comparison    TEXT
) AS $$
    SELECT
        pa.ig_media_id,
        pa.predicted_value AS pred_a,
        pa.match           AS match_a,
        pb.predicted_value AS pred_b,
        pb.match           AS match_b,
        CASE
            WHEN pa.match AND NOT pb.match THEN 'run_a_better'
            WHEN NOT pa.match AND pb.match THEN 'run_b_better'
            WHEN pa.match AND pb.match     THEN 'both_correct'
            ELSE 'both_wrong'
        END AS comparison
    FROM predictions pa
    JOIN predictions pb
        ON pb.ig_media_id = pa.ig_media_id
        AND pb.agent = pa.agent
    WHERE pa.simulation_run_id = run_a
        AND pb.simulation_run_id = run_b
        AND pa.agent = target_axis::agent_type
    ORDER BY pa.ig_media_id;
$$ LANGUAGE sql STABLE;
