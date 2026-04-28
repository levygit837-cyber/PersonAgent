-- ============================================================
-- Migration 007: Remove legacy canvas persistence
-- ============================================================

DROP TABLE IF EXISTS workflow_runs;
DROP TABLE IF EXISTS lab_graphs;
DROP FUNCTION IF EXISTS update_lab_graph_updated_at;
