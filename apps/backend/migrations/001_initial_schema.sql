-- HILPO — Schéma initial
-- v1 — 2026-04-04

-- =============================================================
-- ENUMS
-- =============================================================

CREATE TYPE media_type AS ENUM ('IMAGE', 'CAROUSEL_ALBUM', 'VIDEO');
CREATE TYPE media_product_type AS ENUM ('FEED', 'REELS', 'STORY');
CREATE TYPE media_item_type AS ENUM ('IMAGE', 'VIDEO');
CREATE TYPE strategy_type AS ENUM ('Organic', 'Brand Content');
CREATE TYPE prompt_status AS ENUM ('draft', 'active', 'retired');
CREATE TYPE agent_type AS ENUM ('router', 'category', 'visual_format', 'strategy');
CREATE TYPE api_call_type AS ENUM ('classification', 'rewrite', 'evaluation');
CREATE TYPE split_type AS ENUM ('dev', 'test');

-- =============================================================
-- DONNÉES BRUTES (import CSV)
-- =============================================================

CREATE TABLE posts (
    ig_media_id       BIGINT PRIMARY KEY,
    shortcode         VARCHAR(50),
    ig_user_id        BIGINT NOT NULL,
    caption           TEXT,
    timestamp         TIMESTAMPTZ NOT NULL,
    media_type        media_type NOT NULL,
    media_product_type media_product_type NOT NULL,
    followed_post     BOOLEAN NOT NULL DEFAULT FALSE,
    suspected         BOOLEAN NOT NULL DEFAULT FALSE,
    authors_checked   BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at       TIMESTAMPTZ NOT NULL,
    boosted_post      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_posts_timestamp ON posts (timestamp DESC);
CREATE INDEX idx_posts_media_type ON posts (media_type);

CREATE TABLE post_media (
    ig_media_id       BIGINT PRIMARY KEY,
    parent_ig_media_id BIGINT NOT NULL REFERENCES posts(ig_media_id),
    media_order       SMALLINT NOT NULL,
    media_type        media_item_type NOT NULL,
    width             INTEGER,
    height            INTEGER,
    duration          REAL,
    media_url         TEXT,
    thumbnail_url     TEXT,

    UNIQUE (parent_ig_media_id, media_order)
);

CREATE INDEX idx_post_media_parent ON post_media (parent_ig_media_id);

-- =============================================================
-- LOOKUPS (catégories et formats)
-- =============================================================

CREATE TABLE categories (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE visual_formats (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

-- =============================================================
-- CATÉGORISATION HEURISTIQUE V0 (import CSV)
-- =============================================================

CREATE TABLE heuristic_labels (
    ig_media_id    BIGINT PRIMARY KEY REFERENCES posts(ig_media_id),
    category_id    INTEGER REFERENCES categories(id),
    subcategory    VARCHAR(200),
    strategy       strategy_type,
    visual_format_id INTEGER REFERENCES visual_formats(id)
);

-- =============================================================
-- ÉCHANTILLON ET SPLITS
-- =============================================================

CREATE TABLE sample_posts (
    ig_media_id BIGINT PRIMARY KEY REFERENCES posts(ig_media_id),
    split       split_type,
    seed        SMALLINT NOT NULL DEFAULT 42
);

-- =============================================================
-- ANNOTATIONS HUMAINES
-- =============================================================

CREATE TABLE annotations (
    id              SERIAL PRIMARY KEY,
    ig_media_id     BIGINT NOT NULL REFERENCES posts(ig_media_id),
    category_id     INTEGER REFERENCES categories(id),
    visual_format_id INTEGER REFERENCES visual_formats(id),
    strategy        strategy_type,
    annotator       VARCHAR(50) NOT NULL DEFAULT 'mathias',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (ig_media_id, annotator)
);

-- =============================================================
-- PROMPTS VERSIONNÉS
-- =============================================================

CREATE TABLE prompt_versions (
    id          SERIAL PRIMARY KEY,
    agent       agent_type NOT NULL,
    scope       media_product_type,         -- NULL = tous types, sinon FEED/REELS/STORY
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    status      prompt_status NOT NULL DEFAULT 'draft',
    parent_id   INTEGER REFERENCES prompt_versions(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Métriques au moment de l'évaluation
    accuracy    REAL,
    eval_sample_size INTEGER
);

-- Un seul prompt actif par agent × scope
CREATE UNIQUE INDEX idx_prompt_active
    ON prompt_versions (agent, scope) WHERE status = 'active';

CREATE INDEX idx_prompt_agent_scope ON prompt_versions (agent, scope);

-- =============================================================
-- PRÉDICTIONS DU MODÈLE
-- =============================================================

CREATE TABLE predictions (
    id               SERIAL PRIMARY KEY,
    ig_media_id      BIGINT NOT NULL REFERENCES posts(ig_media_id),
    agent            agent_type NOT NULL,
    prompt_version_id INTEGER NOT NULL REFERENCES prompt_versions(id),
    predicted_value  VARCHAR(200) NOT NULL,     -- valeur prédite (nom de catégorie, format, strategy...)
    raw_response     JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Match auto-calculé après annotation
    match            BOOLEAN
);

CREATE INDEX idx_predictions_prompt ON predictions (prompt_version_id);
CREATE INDEX idx_predictions_post ON predictions (ig_media_id);
CREATE INDEX idx_predictions_agent ON predictions (agent);

-- =============================================================
-- REWRITE LOGS
-- =============================================================

CREATE TABLE rewrite_logs (
    id                  SERIAL PRIMARY KEY,
    prompt_before_id    INTEGER NOT NULL REFERENCES prompt_versions(id),
    prompt_after_id     INTEGER NOT NULL REFERENCES prompt_versions(id),
    error_batch         JSONB NOT NULL,
    rewriter_reasoning  TEXT,
    accepted            BOOLEAN,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- TRAÇABILITÉ API
-- =============================================================

CREATE TABLE api_calls (
    id                SERIAL PRIMARY KEY,
    call_type         api_call_type NOT NULL,
    agent             agent_type,
    model_name        VARCHAR(100) NOT NULL,
    prompt_version_id INTEGER REFERENCES prompt_versions(id),
    ig_media_id       BIGINT REFERENCES posts(ig_media_id),
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          REAL,
    latency_ms        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_calls_type ON api_calls (call_type);

-- =============================================================
-- VUE : métriques par version de prompt
-- =============================================================

CREATE VIEW prompt_metrics AS
SELECT
    pv.id AS prompt_version_id,
    pv.agent,
    pv.scope,
    pv.version,
    pv.status,
    pv.created_at,
    COUNT(p.id) AS total_predictions,
    AVG(p.match::int) AS accuracy
FROM prompt_versions pv
LEFT JOIN predictions p ON p.prompt_version_id = pv.id
GROUP BY pv.id, pv.agent, pv.scope, pv.version, pv.status, pv.created_at
ORDER BY pv.agent, pv.scope, pv.version;
