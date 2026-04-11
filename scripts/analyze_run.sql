-- Analyse complète d'un run baseline.
-- Usage :
--   PGPASSWORD=hilpo psql -h localhost -p 5433 -U hilpo -d hilpo \
--     -v run_id=69 -v prev_run_id=68 -f scripts/analyze_run.sql

\pset border 2
\pset format aligned

\echo ========================================
\echo 1. STATUT DU RUN
\echo ========================================

SELECT id, status, finished_at,
       final_accuracy_category AS cat,
       final_accuracy_visual_format AS vf,
       final_accuracy_strategy AS strat
FROM simulation_runs
WHERE id IN (:run_id, :prev_run_id)
ORDER BY id;

\echo ========================================
\echo 2. COMPARAISON ACCURACY GLOBALE (run vs prev)
\echo ========================================

WITH r AS (
  SELECT p.simulation_run_id,
         p.agent::text AS agent,
         ROUND(100.0 * SUM(CASE WHEN p.predicted_value = COALESCE(vf.name, cat.name, a.strategy::text) THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS acc,
         COUNT(*) AS n
  FROM predictions p
  JOIN annotations a ON a.ig_media_id = p.ig_media_id
  LEFT JOIN visual_formats vf ON vf.id = a.visual_format_id AND p.agent = 'visual_format'
  LEFT JOIN categories cat ON cat.id = a.category_id AND p.agent = 'category'
  WHERE p.simulation_run_id IN (:run_id, :prev_run_id)
    AND p.agent IN ('visual_format', 'category', 'strategy')
  GROUP BY 1, 2
)
SELECT agent,
       MAX(CASE WHEN simulation_run_id = :prev_run_id THEN acc END) AS prev_acc,
       MAX(CASE WHEN simulation_run_id = :run_id THEN acc END) AS curr_acc,
       MAX(CASE WHEN simulation_run_id = :run_id THEN acc END)
       - MAX(CASE WHEN simulation_run_id = :prev_run_id THEN acc END) AS delta
FROM r GROUP BY agent ORDER BY agent;

\echo ========================================
\echo 3. TOP 15 CONFUSIONS — run courant
\echo ========================================

SELECT vf_true.name AS truth, vf_pred.name AS predicted, COUNT(*) AS n
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
JOIN visual_formats vf_pred ON vf_pred.name = p.predicted_value
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format' AND vf_true.name <> vf_pred.name
GROUP BY vf_true.name, vf_pred.name
ORDER BY n DESC LIMIT 15;

\echo ========================================
\echo 4. CLASSES CIBLÉES — recall prev vs curr
\echo ========================================

WITH per_class AS (
  SELECT p.simulation_run_id, vf.name AS truth, COUNT(*) AS n_total,
         SUM(CASE WHEN p.predicted_value = vf.name THEN 1 ELSE 0 END) AS n_correct
  FROM predictions p
  JOIN annotations a ON a.ig_media_id = p.ig_media_id
  JOIN visual_formats vf ON vf.id = a.visual_format_id
  WHERE p.simulation_run_id IN (:run_id, :prev_run_id) AND p.agent = 'visual_format'
  GROUP BY 1, 2
)
SELECT truth,
       MAX(CASE WHEN simulation_run_id = :prev_run_id THEN n_total END) AS n,
       MAX(CASE WHEN simulation_run_id = :prev_run_id THEN n_correct END) AS prev_correct,
       MAX(CASE WHEN simulation_run_id = :run_id THEN n_correct END) AS curr_correct,
       ROUND(100.0 * MAX(CASE WHEN simulation_run_id = :prev_run_id THEN n_correct END)::numeric
             / NULLIF(MAX(CASE WHEN simulation_run_id = :prev_run_id THEN n_total END), 0), 1) AS prev_pct,
       ROUND(100.0 * MAX(CASE WHEN simulation_run_id = :run_id THEN n_correct END)::numeric
             / NULLIF(MAX(CASE WHEN simulation_run_id = :run_id THEN n_total END), 0), 1) AS curr_pct
FROM per_class
WHERE truth IN (
  'post_news', 'post_mood',
  'post_en_savoir_plus', 'post_en_savoir_plus_selection',
  'post_interview', 'post_selection',
  'post_serie_mood_texte', 'post_article', 'post_quote',
  'post_wrap_up', 'post_classement', 'post_chiffre',
  'reel_news', 'reel_mood', 'reel_interview', 'reel_wrap_up'
)
GROUP BY truth ORDER BY truth;

\echo ========================================
\echo 5. CAS CRITIQUE : post_news vs post_mood (cible principale run 69)
\echo ========================================

\echo  -- FPs : posts prédits post_news mais réellement autre
SELECT vf_true.name AS truth, COUNT(*) AS n
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format'
  AND p.predicted_value = 'post_news' AND vf_true.name <> 'post_news'
GROUP BY vf_true.name ORDER BY n DESC LIMIT 10;

\echo  -- FNs : posts réellement post_news mais prédits autre chose
SELECT p.predicted_value AS predicted, COUNT(*) AS n
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf ON vf.id = a.visual_format_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format'
  AND vf.name = 'post_news' AND p.predicted_value <> 'post_news'
GROUP BY p.predicted_value ORDER BY n DESC LIMIT 10;

\echo ========================================
\echo 6. IMPACT DATE — post_news par période de publication
\echo ========================================

SELECT
  CASE WHEN po.timestamp < '2024-01-01' THEN 'ancien (< 2024)' ELSE 'récent (>= 2024)' END AS periode,
  COUNT(*) AS n_total,
  SUM(CASE WHEN p.predicted_value = vf.name THEN 1 ELSE 0 END) AS n_correct,
  ROUND(100.0 * SUM(CASE WHEN p.predicted_value = vf.name THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS recall
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf ON vf.id = a.visual_format_id
JOIN posts po ON po.ig_media_id = p.ig_media_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format' AND vf.name = 'post_news'
GROUP BY 1 ORDER BY 1;

\echo ========================================
\echo 7. ACCURACY PAR ÉPOQUE (cut 2024-01-01)
\echo ========================================

SELECT
  CASE WHEN po.timestamp >= '2024-01-01' THEN '>= 2024' ELSE '< 2024' END AS era,
  COUNT(*) AS n_total,
  SUM(CASE WHEN p.predicted_value = vf.name THEN 1 ELSE 0 END) AS n_correct,
  ROUND(100.0 * SUM(CASE WHEN p.predicted_value = vf.name THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS acc
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf ON vf.id = a.visual_format_id
JOIN posts po ON po.ig_media_id = p.ig_media_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format'
GROUP BY 1 ORDER BY 1;

\echo ========================================
\echo 8. TOP 10 CONFUSIONS — uniquement < 2024
\echo ========================================

SELECT vf_true.name AS truth, vf_pred.name AS predicted, COUNT(*) AS n
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
JOIN visual_formats vf_pred ON vf_pred.name = p.predicted_value
JOIN posts po ON po.ig_media_id = p.ig_media_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format'
  AND vf_true.name <> vf_pred.name AND po.timestamp < '2024-01-01'
GROUP BY vf_true.name, vf_pred.name ORDER BY n DESC LIMIT 10;

\echo ========================================
\echo 9. TOP 10 CONFUSIONS — uniquement >= 2024
\echo ========================================

SELECT vf_true.name AS truth, vf_pred.name AS predicted, COUNT(*) AS n
FROM predictions p
JOIN annotations a ON a.ig_media_id = p.ig_media_id
JOIN visual_formats vf_true ON vf_true.id = a.visual_format_id
JOIN visual_formats vf_pred ON vf_pred.name = p.predicted_value
JOIN posts po ON po.ig_media_id = p.ig_media_id
WHERE p.simulation_run_id = :run_id AND p.agent = 'visual_format'
  AND vf_true.name <> vf_pred.name AND po.timestamp >= '2024-01-01'
GROUP BY vf_true.name, vf_pred.name ORDER BY n DESC LIMIT 10;

\echo ========================================
\echo 10. DEUX SCORES — global vs >= 2024 sur les 3 axes
\echo ========================================

WITH eval AS (
  SELECT p.agent::text AS axis,
         p.predicted_value,
         vf.name AS vf_truth, cat.name AS cat_truth, a.strategy::text AS strat_truth,
         po.timestamp
  FROM predictions p
  JOIN annotations a ON a.ig_media_id = p.ig_media_id
  JOIN posts po ON po.ig_media_id = p.ig_media_id
  LEFT JOIN visual_formats vf ON vf.id = a.visual_format_id AND p.agent = 'visual_format'
  LEFT JOIN categories cat ON cat.id = a.category_id AND p.agent = 'category'
  WHERE p.simulation_run_id = :run_id
    AND p.agent IN ('visual_format', 'category', 'strategy')
)
SELECT axis,
       COUNT(*) FILTER (WHERE predicted_value = COALESCE(vf_truth, cat_truth, strat_truth)) AS correct_all,
       COUNT(*) AS total_all,
       ROUND(100.0 * COUNT(*) FILTER (WHERE predicted_value = COALESCE(vf_truth, cat_truth, strat_truth))::numeric / COUNT(*), 1) AS acc_all,
       COUNT(*) FILTER (WHERE predicted_value = COALESCE(vf_truth, cat_truth, strat_truth) AND timestamp >= '2024-01-01') AS correct_2024,
       COUNT(*) FILTER (WHERE timestamp >= '2024-01-01') AS total_2024,
       ROUND(100.0 * COUNT(*) FILTER (WHERE predicted_value = COALESCE(vf_truth, cat_truth, strat_truth) AND timestamp >= '2024-01-01')::numeric
             / NULLIF(COUNT(*) FILTER (WHERE timestamp >= '2024-01-01'), 0), 1) AS acc_2024
FROM eval GROUP BY axis ORDER BY axis;
