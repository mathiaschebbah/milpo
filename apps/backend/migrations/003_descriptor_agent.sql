-- HILPO — Migration 003 : ajout du type 'descriptor' à l'enum agent_type
-- Nécessaire pour le pipeline Phase 2 (descripteur multimodal + classifieurs)

ALTER TYPE agent_type ADD VALUE IF NOT EXISTS 'descriptor';
