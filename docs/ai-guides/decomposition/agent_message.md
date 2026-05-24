# Playbook: Decompose `agent-message.tsx`

**Target file:** `@desktop-electron/src/components/chat/agent-message.tsx`
(1,419 lines)

**Target directory:** `@desktop-electron/src/components/chat/agent-message/`

**Tests:**
- `@desktop-electron/src/components/chat/agent-message.test.tsx`

Read `_protocol.md` first.

## Why this file is hard

`AgentMessage` renders the AI assistant's response with:

1. **Content blocks** — markdown, code, lists, tables.
2. **Action buttons** — copy, retry, branch, feedback.
3. **Thinking/reasoning display** — collapsible reasoning blocks.
4. **Tool result display** — inline tool output rendering.

## Public contract that must be preserved

`AgentMessage` is rendered by the chat message list. Props interface
must remain identical.

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract content blocks | ⏳ Pending | — | |
| 2 — Extract actions | ⏳ Pending | — | |
| 3 — Extract thinking block | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract content blocks to `agent-message/content-blocks.tsx`

**What moves out:** Message block rendering logic.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 2 — Extract actions to `agent-message/actions.tsx`

**What moves out:** Copy, retry, branch, feedback buttons.

**Risk:** Low.

**Tests:** 10+ cases.

### Slice 3 — Extract thinking block to `agent-message/thinking-block.tsx`

**What moves out:** Collapsible reasoning display.

**Risk:** Low.

**Tests:** 5+ cases.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern agent-message
```
