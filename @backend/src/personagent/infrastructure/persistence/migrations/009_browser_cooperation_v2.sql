ALTER TABLE browser_cooperation_events
    ADD COLUMN IF NOT EXISTS channel VARCHAR(40) NOT NULL DEFAULT 'event',
    ADD COLUMN IF NOT EXISTS trace_role VARCHAR(30) NOT NULL DEFAULT 'user',
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(30) NOT NULL DEFAULT 'raw',
    ADD COLUMN IF NOT EXISTS raw_kind VARCHAR(120),
    ADD COLUMN IF NOT EXISTS coordinates JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS trace_effect VARCHAR(80),
    ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(120);

CREATE INDEX IF NOT EXISTS idx_browser_cooperation_workspace_correlation
    ON browser_cooperation_events(browser_workspace_id, correlation_id);
