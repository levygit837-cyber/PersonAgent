-- ============================================================
-- Migration 002: Lab graph persistence
-- ============================================================

CREATE TABLE IF NOT EXISTS lab_graphs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL DEFAULT 'Untitled Lab Graph',
    graph JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lab_graphs_updated_at ON lab_graphs(updated_at DESC);

CREATE OR REPLACE FUNCTION update_lab_graph_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_lab_graph_updated_at ON lab_graphs;
CREATE TRIGGER trigger_update_lab_graph_updated_at
    BEFORE UPDATE ON lab_graphs
    FOR EACH ROW
    EXECUTE FUNCTION update_lab_graph_updated_at();
