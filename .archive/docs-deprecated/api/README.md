# PersonAgent API Reference

PersonAgent exposes a FastAPI backend for the Electron desktop client, local
tool orchestration, memory, browser workspaces, QA tracing, and Git/workspace
operations.

Primary implementation files:

- `@backend/src/personagent/interfaces/api/main.py`
- `@backend/src/personagent/interfaces/api/routes/*.py`
- `@backend/src/personagent/interfaces/api/state_events.py`
- `@backend/src/personagent/interfaces/api/errors.py`
- `@desktop-electron/src/api/client.ts`
- `@desktop-electron/src/api/sse.ts`
- `@desktop-electron/src/api/errors.ts`

Development OpenAPI docs are available at `/docs` and `/redoc` when
`app_env == "development"`.

## Transport Contracts

### JSON

Most endpoints return JSON. The Electron client calls them through
`requestJson()` in `@desktop-electron/src/api/client.ts`, which sends
`Content-Type: application/json` for non-GET bodies and converts non-2xx
responses into `PersonAgentApiError`.

### Errors

JSON errors preserve FastAPI compatibility and add a structured envelope:

```json
{
  "detail": "Human readable message",
  "error": {
    "code": "request.validation_failed",
    "category": "request",
    "severity": "error",
    "message": "Human readable message",
    "status": 422,
    "retryable": false,
    "correlation_id": "...",
    "safe_for_model": true,
    "safe_for_telemetry": true,
    "metadata": {}
  }
}
```

SSE and WebSocket errors use:

```json
{
  "event": "error",
  "error": "Human readable message",
  "error_detail": { "code": "...", "message": "...", "status": 500 },
  "status": 500
}
```

### SSE

SSE responses use `text/event-stream`. Chat streams encode JSON as `data: ...`
blocks and end with `data: [DONE]`. State events use named
`event: state.changed` messages. QA streams emit JSON `data` blocks and
keep-alive comments.

### WebSocket

Team Mode uses `/chat/team/ws`. The desktop opens the socket, sends a
`team.run.start` payload shaped like `ChatRequest` plus team fields, receives
JSON `TeamRunEvent` messages, and can send `{ "type": "team.run.stop" }` to
cancel.

## Root And Health

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Returns app name, version, and docs path. |
| `GET` | `/health` | Checks backend health and the default LLM backend. |

## Chat API

Prefix: `/chat`

Core request body for chat endpoints:

| Field | Type | Notes |
| --- | --- | --- |
| `conversation_id` | `string | null` | Continue an existing conversation. |
| `message` | `string` | Required user message. |
| `system_prompt` | `string | null` | Optional system override. |
| `stream` | `boolean` | Defaults to `true`. |
| `temperature` | `number` | `0.0` to `2.0`. |
| `max_tokens` | `integer` | `-1` means backend default. |
| `provider` | `string` | `llama`, `nvidia`, `deepseek`, `vertex`, `kimi`, or `codex`. |
| `model` | `string` | Provider model id. |
| `prompt_mode` | `string` | `auto`, `writing`, `exploring`, or `research`. |
| `workspace_root` | `string | null` | Selected workspace for tools and context. |
| `reasoning_level` | `string | null` | `low`, `medium`, `high`, `xhigh`, or `max`. |
| `reasoning_budget_tokens` | `integer | null` | `0` to `32768`. |
| `tools_enabled` | `boolean` | Enables model tool calls. |
| `allowed_tools` | `string[] | null` | Optional tool allowlist. |
| `tool_context` | `object | null` | Tool context such as `cwd` and `allowed_roots`. |
| `max_tool_iterations` | `integer | null` | Limits model-tool loops. |
| `context_attachments` | `object[]` | Structured model-visible context. |

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/chat/teams` | Returns Team Mode configurations as `{ data: TeamConfig[] }`. |
| `GET` | `/chat/models?provider=&capability=&refresh=` | Returns provider model catalog. |
| `GET` | `/chat/auth/codex/status` | Returns Codex subscription auth status. |
| `POST` | `/chat/auth/codex/logout` | Clears Codex auth state and returns new status. |
| `GET` | `/chat/commands?workspace_root=` | Lists slash commands and skills exposed as commands. |
| `POST` | `/chat/prompt/preview` | Returns prompt sections, surfaces, token estimate, provider, and model. |
| `POST` | `/chat/completions` | Synchronous completion. Returns `conversation_id`, `message_id`, `content`, `reasoning_content`, `finish_reason`, `usage`, `model`, `provider`, and `images`. |
| `POST` | `/chat/completions/stream` | Streams chat chunks over SSE. |
| `POST` | `/chat/plan/approve` | Approves a pending plan and resumes execution. |
| `POST` | `/chat/plan/continue` | Continues after a pending plan with optional feedback. |
| `POST` | `/chat/plan/cancel` | Cancels a pending plan. |
| `POST` | `/chat/tools/approve` | Approves a pending tool call and returns JSON. |
| `POST` | `/chat/tools/approve/stream` | Approves a pending tool call and streams resumed execution over SSE. |
| `POST` | `/chat/tools/reject` | Rejects a pending tool call. |
| `POST` | `/chat/user-question/respond/stream` | Sends answers for a pending user-question approval and streams resumed execution. |
| `WS` | `/chat/team/ws` | Team Mode run socket. |

Plan decisions use `{ conversation_id, approval_id?, feedback? }`. Tool
approval decisions use `{ conversation_id, approval_id }`. User-question
responses use `{ conversation_id, approval_id, answers }`.

## Conversations API

Prefix: `/conversations`

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/conversations?limit=50&offset=0` | Lists conversations with `id`, `title`, timestamps, `message_count`, `workspace_root`, and `status`. |
| `GET` | `/conversations/{conversation_id}` | Returns title, timestamps, and serialized messages. |
| `POST` | `/conversations/{conversation_id}/fork` | Creates a new conversation from a selected prefix. Body: `{ title?, workspace_root?, messages[] }`. |
| `DELETE` | `/conversations/{conversation_id}` | Deletes a conversation. Returns `{ deleted: true }`. |
| `GET` | `/conversations/search/{query}?limit=20` | Searches conversation summaries. |

Fork messages accept `role`, `content`, `metadata`, `tool_calls`, and
`tool_call_id`.

## Sessions And Browser Workspace API

Prefix: `/sessions`

Browser viewport body fields are shared by browser-control endpoints:
`width` defaults to `1024` and `height` defaults to `720`.

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/sessions/browser/{browser_id}/view?width=&height=` | Runtime browser view without a conversation scope. |
| `POST` | `/sessions/browser/{browser_id}/navigate` | Body: viewport plus `url`. |
| `POST` | `/sessions/browser/{browser_id}/history` | Body: viewport plus `direction` (`-1` or `1`). |
| `POST` | `/sessions/browser/{browser_id}/reload` | Body: viewport. |
| `POST` | `/sessions/browser/{browser_id}/click` | Body: viewport plus `x`, `y`, `button`. |
| `POST` | `/sessions/browser/{browser_id}/key` | Body: viewport plus `text` or `key`. |
| `POST` | `/sessions/browser/{browser_id}/scroll` | Body: viewport plus `delta_x`, `delta_y`. |
| `POST` | `/sessions/browser/{browser_id}/action` | Body: viewport plus `node_id`, `action`, and action-specific fields. |
| `GET` | `/sessions/{conversation_id}/browser/{browser_id}/view?width=&height=` | Conversation-scoped browser view and persisted workspace state. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/navigate` | Conversation-scoped navigate. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/history` | Conversation-scoped history movement. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/reload` | Conversation-scoped reload. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/click` | Conversation-scoped click. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/key` | Conversation-scoped key/type action. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/scroll` | Conversation-scoped scroll. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/action` | Conversation-scoped mapped element action. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/cooperation` | Body: `{ enabled, mode }`; toggles Browser Cooperation. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/events` | Body: `{ events[] }`; ingests browser cooperation events. |
| `POST` | `/sessions/{conversation_id}/browser/{browser_id}/annotations` | Creates a Browser Workspace annotation. |
| `DELETE` | `/sessions/{conversation_id}/browser/{browser_id}/annotations/{annotation_id}` | Deletes an annotation. |
| `DELETE` | `/sessions/{conversation_id}/browser/{browser_id}/timeline` | Clears the persisted lightweight browser timeline. |
| `POST` | `/sessions/titles/verify` | Batch verifies or repairs session titles. |
| `POST` | `/sessions/titles/dedupe` | Repairs duplicate session titles. |
| `GET` | `/sessions/{conversation_id}/panel?workspace_root=` | Returns the session panel snapshot. |
| `GET` | `/sessions/{conversation_id}/project/details?type=&id=&workspace_root=` | Returns selected project detail for a session. |

Mapped browser actions are `click`, `fill`, `submit`, `select`, `press`,
`hover`, `wait`, `drag`, `drop`, `upload`, `select_text`, `scroll_to`, and
`screenshot`.

The Browser Workspace persists lightweight state only: annotations, compact
element maps, active browser identifiers, current URL/title, cooperation state,
and capped timeline events. Full HTML snapshots remain runtime data.

## Memory API

Prefix: `/memory`

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/memory/{project_slug}/index` | Returns memory index metadata. |
| `GET` | `/memory/{project_slug}/operational/status` | Returns operational memory indexing status. |
| `POST` | `/memory/{project_slug}/operational/recall` | Previews operational memory recall for a query. |
| `GET` | `/memory/{project_slug}/operational/events?limit=50` | Lists recent operational memory events. |
| `POST` | `/memory/{project_slug}/operational/reindex` | Reindexes operational memory. Body: `{ source, limit }`. |
| `GET` | `/memory/{project_slug}/{memory_name}` | Reads one structured memory file. |
| `PUT` | `/memory/{project_slug}/{memory_name}` | Updates memory description and/or content. |
| `DELETE` | `/memory/{project_slug}/{memory_name}` | Deletes one memory. |
| `POST` | `/memory/{project_slug}` | Creates a memory. Body: `{ name, description, content, memory_type, scope }`. |
| `GET` | `/memory/{project_slug}?memory_type=` | Lists memories for a project. |

`memory_name` must be snake_case and cannot contain path traversal characters.

Operational recall accepts `query`, `top_k`, optional conversation/session/workspace
filters, source and file filters, date bounds, `latest_only`, `active_only`,
`budget_tokens`, `provider`, and `model`.

## Workspace And Git API

Prefix: `/workspace`

Filesystem routes resolve paths inside allowed workspace roots.

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/workspace/files?path=&workspace_root=` | Lists files for a directory. |
| `GET` | `/workspace/mentions?q=&workspace_root=&limit=40` | Returns file/directory mention suggestions. |
| `GET` | `/workspace/file?path=&workspace_root=` | Reads a workspace file. |
| `GET` | `/workspace/projects` | Lists nearby Git workspaces. |
| `GET` | `/workspace/git-status?workspace_root=` | Returns branch, ahead/behind, dirty counts, and remote URL. |
| `GET` | `/workspace/git-commit-message?workspace_root=` | Generates a commit message from current changes. |
| `GET` | `/workspace/git-recent-actions?workspace_root=` | Returns recent commits, pushes, and PRs. |
| `GET` | `/workspace/git-pull-requests?workspace_root=` | Returns PR summaries via GitHub CLI when available. |
| `POST` | `/workspace/git-pull-requests/{number}/comments` | Creates a standardized PR comment. |
| `GET` | `/workspace/git-branches?workspace_root=` | Lists local and remote branches. |
| `POST` | `/workspace/git-branches` | Body: `{ workspace_root, name }`; creates and switches branch. |
| `POST` | `/workspace/git-worktrees` | Body: `{ workspace_root, name?, branch?, source_message_id? }`; creates isolated worktree and branch. |
| `POST` | `/workspace/git-checkout` | Body: `{ workspace_root, name, kind }`; switches branch. |
| `POST` | `/workspace/git-commit` | Body: `{ workspace_root, message?, auto_generate_message }`; stages all changes and commits. |
| `POST` | `/workspace/git-push` | Body: `{ workspace_root }`; pushes current branch. |
| `POST` | `/workspace/git-pr` | Body: `{ workspace_root }`; opens or locates a PR. |

Git endpoints publish best-effort state events after branch, status, PR, commit,
or push changes.

## Skills API

Prefix: `/skills`

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/skills?workspace_root=` | Lists installed skills. |
| `GET` | `/skills/marketplace?workspace_root=` | Lists marketplace skills and install status. |
| `POST` | `/skills/marketplace/{item_id}/install?workspace_root=` | Installs a marketplace skill. |
| `GET` | `/skills/{invocation_name}?workspace_root=` | Reads installed skill detail and content. |
| `PATCH` | `/skills/{invocation_name}/activation?workspace_root=` | Body: `{ enabled }`; toggles skill activation. |

## QA API

Prefix: `/qa`

The QA subsystem creates a session, builds a static code graph, executes ASGI
requests under tracing, then exposes graph/runtime/context views.

| Method | Path | Contract |
| --- | --- | --- |
| `POST` | `/qa/sessions` | Creates a QA session bound to a repo/workspace. |
| `POST` | `/qa/sessions/{session_id}/index` | Builds or refreshes the static code graph. |
| `POST` | `/qa/sessions/{session_id}/requests` | Executes an ASGI request under QA tracing. |
| `GET` | `/qa/sessions/{session_id}/graph` | Returns static graph plus runtime overlay. |
| `GET` | `/qa/sessions/{session_id}/events?limit=500` | Lists persisted runtime events. |
| `GET` | `/qa/sessions/{session_id}/context` | Returns compact agent-ready debugging context. |
| `GET` | `/qa/sessions/{session_id}/stream` | Streams QA runtime events over SSE. |

## State Events API

Prefix: `/events`

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/events/state` | SSE stream for cache invalidation and lightweight state changes. |

Event payload:

```json
{
  "event": "state.changed",
  "resource": "git-status",
  "scope": {},
  "version": "uuid-or-custom-version",
  "changed_at": "2026-04-29T00:00:00+00:00"
}
```

The stream sends `: connected` initially and `: heartbeat` during idle periods.

## API Maintenance Checklist

- Add new routers in `@backend/src/personagent/interfaces/api/main.py`.
- Keep Pydantic request/response models close to route modules unless reused
  across subsystems.
- Update the matching Electron client function in
  `@desktop-electron/src/api/client.ts` for UI-consumed endpoints.
- Update `@desktop-electron/src/api/errors.ts` if the error envelope changes.
- Add or update route tests under `@backend/tests/` and API client tests under
  `@desktop-electron/src/api/`.
- Update this file in the same change as any route or transport contract change.
