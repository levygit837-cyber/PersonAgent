# Playbook: Decompose `browser-mirror.ts`

**Target file:** `@desktop-electron/src/components/chat/session-panel/browser-mirror.ts`
(1,261 lines)

**Target directory:** Stays in `session-panel/` as sub-modules.

**Tests:**
- `@desktop-electron/src/components/chat/session-panel.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`browser-mirror.ts` manages the client-side browser rendering pipeline:

1. **HTML sanitization** — cleaning and preparing HTML for safe rendering
   in the desktop app.
2. **Render cache** — caching rendered browser views for performance.
3. **View synchronization** — syncing the mirror view with backend
   browser state updates.

## Public contract that must be preserved

Exported functions and types used by `session-panel.tsx` must remain
at the same import paths (or re-exported).

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract sanitization | ⏳ Pending | — | |
| 2 — Extract render cache | ⏳ Pending | — | |
| 3 — Extract view sync | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract HTML sanitization to `browser-mirror/sanitize.ts`

**What moves out:** HTML cleaning functions, allowed tag lists,
attribute filtering.

**Risk:** Medium — security-sensitive.

**Tests:** 15+ cases — XSS prevention, allowed tags, edge cases.

### Slice 2 — Extract render cache to `browser-mirror/render-cache.ts`

**What moves out:** View caching, cache key generation, eviction.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Extract view sync to `browser-mirror/sync.ts`

**What moves out:** State synchronization with backend updates.

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern session-panel
```
