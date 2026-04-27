-- ============================================================
-- Migration 006: Team Mode V3 workspace memory snapshots
-- ============================================================

ALTER TABLE team_runs
    ADD COLUMN IF NOT EXISTS workspace_id TEXT;

ALTER TABLE team_blackboard_events
    ADD COLUMN IF NOT EXISTS workspace_id TEXT;

CREATE TABLE IF NOT EXISTS team_memory_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id TEXT NOT NULL UNIQUE,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run_id VARCHAR(100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_team_runs_workspace_id
    ON team_runs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_team_blackboard_events_workspace_id
    ON team_blackboard_events(workspace_id);
CREATE INDEX IF NOT EXISTS idx_team_memory_snapshots_updated_at
    ON team_memory_snapshots(updated_at DESC);
