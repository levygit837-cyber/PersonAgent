-- ============================================================
-- Migration 003: Task tools persistence
-- ============================================================

CREATE TABLE IF NOT EXISTS task_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id VARCHAR(100),
    workspace_root TEXT,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    priority VARCHAR(30) NOT NULL DEFAULT 'normal',
    output TEXT NOT NULL DEFAULT '',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_records_conversation_id ON task_records(conversation_id);
CREATE INDEX IF NOT EXISTS idx_task_records_status ON task_records(status);
CREATE INDEX IF NOT EXISTS idx_task_records_updated_at ON task_records(updated_at DESC);

CREATE OR REPLACE FUNCTION update_task_records_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_task_records_updated_at ON task_records;
CREATE TRIGGER trigger_update_task_records_updated_at
    BEFORE UPDATE ON task_records
    FOR EACH ROW
    EXECUTE FUNCTION update_task_records_updated_at();
