-- 004_rewrite_log_extensions.sql
-- Étend rewrite_logs pour la simulation prequential (Phase 3)

ALTER TABLE rewrite_logs
  ADD COLUMN simulation_run_id INTEGER REFERENCES simulation_runs(id),
  ADD COLUMN target_agent agent_type NOT NULL DEFAULT 'visual_format',
  ADD COLUMN target_scope media_product_type,
  ADD COLUMN incumbent_accuracy REAL,
  ADD COLUMN candidate_accuracy REAL,
  ADD COLUMN eval_sample_size INTEGER,
  ADD COLUMN iteration INTEGER;

ALTER TABLE rewrite_logs ALTER COLUMN target_agent DROP DEFAULT;

CREATE INDEX idx_rewrite_logs_simulation ON rewrite_logs (simulation_run_id);
