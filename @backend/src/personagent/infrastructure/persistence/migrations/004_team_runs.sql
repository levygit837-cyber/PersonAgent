-- ============================================================
-- Migration 004: Team Mode run persistence
-- ============================================================

CREATE TABLE IF NOT EXISTS team_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    team_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    trace_events JSONB NOT NULL DEFAULT '[]'::jsonb,
    final_output TEXT,
    consensus JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_team_runs_conversation_id ON team_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_team_runs_status ON team_runs(status);
CREATE INDEX IF NOT EXISTS idx_team_runs_created_at ON team_runs(created_at DESC);
