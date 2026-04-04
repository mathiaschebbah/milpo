-- HILPO — Migration 003 : descriptions taxonomie
-- Ajoute une colonne description aux lookups et crée la table strategies.

-- =============================================================
-- 1. DESCRIPTIONS SUR LES LOOKUPS EXISTANTS
-- =============================================================

ALTER TABLE visual_formats
    ADD COLUMN description TEXT;

ALTER TABLE categories
    ADD COLUMN description TEXT;

-- =============================================================
-- 2. TABLE STRATEGIES (remplace l'enum pour les descriptions)
-- =============================================================

CREATE TABLE strategies (
    id          SERIAL PRIMARY KEY,
    name        strategy_type NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO strategies (name) VALUES ('Organic'), ('Brand Content');
