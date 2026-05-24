# Playbook: Decompose `file-viewer-panel.tsx`

**Target file:** `@desktop-electron/src/components/chat/file-viewer-panel.tsx`
(1,079 lines)

**Target directory:** `@desktop-electron/src/components/chat/file-viewer-panel/`

**Tests:**
- `@desktop-electron/src/components/chat/file-viewer-panel.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`FileViewerPanel` handles the complete file viewing experience:

1. **File tree navigation** — directory tree with expand/collapse.
2. **File content display** — syntax-highlighted code and markdown rendering.
3. **Data fetching** — loading file content from the workspace API.

## Public contract that must be preserved

Props interface must remain identical.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract file tree | ⏳ Pending | — | |
| 2 — Extract content display | ⏳ Pending | — | |
| 3 — Extract data hooks | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract file tree to `file-viewer-panel/file-tree.tsx`

**What moves out:** Directory tree component, expand/collapse logic.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 2 — Extract content to `file-viewer-panel/file-content.tsx`

**What moves out:** Code display, syntax highlighting, markdown rendering.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Extract hooks to `file-viewer-panel/hooks/`

**What moves out:** `useFileData` hook for fetching and caching file content.

**Risk:** Low.

**Tests:** 5+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern file-viewer-panel
```
