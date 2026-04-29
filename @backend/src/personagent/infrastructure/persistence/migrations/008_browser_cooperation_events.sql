CREATE TABLE IF NOT EXISTS browser_cooperation_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id VARCHAR(120) NOT NULL,
    browser_workspace_id UUID NOT NULL REFERENCES browser_workspaces(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    browser_id VARCHAR(120) NOT NULL,
    tab_id VARCHAR(160),
    page_id VARCHAR(160),
    source VARCHAR(30) NOT NULL DEFAULT 'user',
    kind VARCHAR(80) NOT NULL,
    url TEXT,
    target JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    importance VARCHAR(30) NOT NULL DEFAULT 'low',
    semantic_label TEXT,
    sequence INTEGER NOT NULL DEFAULT 0,
    occurred_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_browser_cooperation_workspace_event UNIQUE (browser_workspace_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_browser_cooperation_workspace_sequence
    ON browser_cooperation_events(browser_workspace_id, sequence);

CREATE INDEX IF NOT EXISTS idx_browser_cooperation_conversation_created
    ON browser_cooperation_events(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_browser_cooperation_workspace_kind
    ON browser_cooperation_events(browser_workspace_id, kind);
