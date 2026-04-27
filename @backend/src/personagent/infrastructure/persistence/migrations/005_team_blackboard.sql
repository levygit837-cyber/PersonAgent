-- ============================================================
-- Migration 005: Team Mode blackboard persistence
-- ============================================================

ALTER TABLE team_runs
    ADD COLUMN IF NOT EXISTS run_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS blackboard_snapshot JSONB;

CREATE UNIQUE INDEX IF NOT EXISTS idx_team_runs_run_id ON team_runs(run_id) WHERE run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS team_blackboard_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id VARCHAR(100) NOT NULL,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    sequence INTEGER NOT NULL,
    phase VARCHAR(40) NOT NULL,
    round INTEGER,
    agent_id VARCHAR(100),
    event_type VARCHAR(60) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_team_blackboard_events_run_id_sequence
    ON team_blackboard_events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_team_blackboard_events_conversation_id
    ON team_blackboard_events(conversation_id);
