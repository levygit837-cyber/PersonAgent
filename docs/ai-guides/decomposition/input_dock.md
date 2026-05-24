# Playbook: Decompose `input-dock.tsx`

**Target file:** `@desktop-electron/src/components/chat/input-dock.tsx`
(1,976 lines)

**Target directory:** `@desktop-electron/src/components/chat/input-dock/`

**Tests:**
- `@desktop-electron/src/components/chat/input-dock.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`InputDock` is a complex React component that owns:

1. **Rich text composer** — contenteditable area with formatting.
2. **@-mention annotations** — file, skill, and context annotations.
3. **Toolbar** — action buttons (send, plan mode, model selector).
4. **Slash commands** — `/model`, `/effort`, `/help` command handling.
5. **Drag & drop** — file attachment via drag and drop.

Multiple `useState`, `useRef`, and `useEffect` hooks manage
tightly coupled state.

## Public contract that must be preserved

`InputDock` is rendered by `chat-workspace.tsx`. The props interface
must remain identical.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract helpers + constants | ⏳ Pending | — | |
| 2 — Extract composer sub-component | ⏳ Pending | — | |
| 3 — Extract toolbar sub-component | ⏳ Pending | — | |
| 4 — Extract annotation sub-component | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract helpers to `input-dock/helpers.ts`

**What moves out:** Pure helper functions, constants, type definitions.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 2 — Extract composer to `input-dock/composer.tsx`

**What moves out:** Rich text editing area, input handling hooks.

**Risk:** Medium — complex DOM interaction.

**Tests:** 10+ cases.

### Slice 3 — Extract toolbar to `input-dock/toolbar.tsx`

**What moves out:** Action buttons bar, model selector, plan toggle.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 4 — Extract annotations to `input-dock/annotations.tsx`

**What moves out:** @-mention UI, annotation rendering, autocomplete.

**Risk:** Medium.

**Tests:** 10+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern input-dock
```
