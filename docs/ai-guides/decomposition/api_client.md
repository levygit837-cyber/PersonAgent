# Playbook: Decompose `client.ts`

**Target file:** `@desktop-electron/src/api/client.ts`
(1,231 lines)

**Target directory:** `@desktop-electron/src/api/client/`

**Tests:**
- (no dedicated test file — add tests during extraction)

Read `_protocol.md` first.

## Why this file is hard

`client.ts` is the single HTTP client that handles all API communication:

1. **Base HTTP layer** — fetch wrapper, auth headers, error handling.
2. **Chat API** — chat completion, streaming, plan/tool approval.
3. **Workspace API** — file operations, git operations.
4. **Session API** — session CRUD, panel data, memory endpoints.

All endpoints are in one file, making it hard to find and modify
specific API calls.

## Public contract that must be preserved

Every exported function is used by components and stores. Exports
must remain at the same import path (re-export from `client/index.ts`).

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract base HTTP + auth | ⏳ Pending | — | |
| 2 — Extract chat API | ⏳ Pending | — | |
| 3 — Extract workspace + session API | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract base HTTP to `client/http.ts`

**What moves out:** fetch wrapper, auth header injection, error
handling, base URL configuration.

**Risk:** Medium — all other slices depend on this.

**Tests:** 10+ cases.

### Slice 2 — Extract chat API to `client/chat-api.ts`

**What moves out:** Chat completion, streaming, plan/tool approval
endpoint functions.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Extract workspace + session API to remaining files

**What moves out:** Workspace endpoints to `client/workspace-api.ts`,
session endpoints to `client/session-api.ts`.

**Risk:** Low.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test
```
