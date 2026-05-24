# Playbook: Decompose `types/chat.ts`

**Target file:** `@desktop-electron/src/types/chat.ts`
(887 lines — 71 exports spanning 6 unrelated domains)

**Target directory:** `@desktop-electron/src/types/chat/`
(new directory; `index.ts` re-exports everything for backward
compatibility)

**Tests:**
- `@desktop-electron/src/types/chat.test.ts`

Read `_protocol.md` first.

## Why this file is hard

`chat.ts` is the type registry for the entire frontend chat system.
It contains interfaces, types, enums, constants, and utility functions
for:

1. **Model/provider types** (~70L): `ModelProvider`, `ReasoningPreset`,
   `PromptMode`, `LlmModel`, `reasoningPresets`, `reasoningTokenBudget`,
   `localModel`.
2. **Conversation types** (~80L): `ConversationSummary`,
   `ConversationStatus`, `PersistedMessage`, `ConversationDetail`,
   `ChatRequestPayload`, `ContextAttachment`, `ContextAttachmentType`,
   `GeneratedImage`.
3. **Command/skill types** (~60L): `ChatCommandInfo`, `SkillSummary`,
   `SkillDetail`, `SkillMarketplaceItem`.
4. **Team mode types** (~250L): `TeamAgent`, `TeamConfig`, `TeamVote`,
   `TeamConsensus`, `TeamRunEvent`, `TeamTraceEventUi`,
   `TeamCompactStatus`, `TeamClaimTraceUi`, `TeamCoverageTraceUi`,
   `TeamToolTraceUi`, `TeamAgentLogKind`, `TeamAgentLogUi`,
   `TeamAgentTraceUi`, `TeamBlackboardTraceUi`, `TeamRunUi`.
5. **Streaming types** (~80L): `StreamChunk` (with all variant fields).
6. **Memory types** (~80L): `MemoryTraceClassicItem`,
   `MemoryTraceOperationalItem`, plus related types.
7. **Tool block types** (~100L): `ToolBlockUi`, `ToolBlockStatus`,
   related display types.
8. **Auth types** (~40L): `CodexAuthStatus`, `ApiErrorEnvelope`.
9. **Workspace/session types** (~50L): workspace and session panel
   related types.

The problems:
1. **Single file for all domains** — finding a type requires
   scanning 887 lines.
2. **No domain grouping** — team types sit next to model types sit
   next to memory types with no logical separation.
3. **Mixed abstraction** — pure type definitions (`interface`) mixed
   with runtime values (`reasoningPresets` array, `reasoningTokenBudget`
   function, `localModel` constant).

## Public contract that must be preserved

Every type, interface, constant, and function is exported and may be
imported by any frontend file. All exports must remain available from
`types/chat` after extraction (via `index.ts` barrel).

## Status

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract team mode types | ⏳ Pending | — | |
| 2 — Extract tool block types | ⏳ Pending | — | |
| 3 — Extract model/streaming types | ⏳ Pending | — | |
| 4 — Extract memory types | ⏳ Pending | — | |

## Proposed slices (in order)

### Slice 1 — Extract team mode types to `chat/team.ts`

**What moves out (~250 lines):**

- `TeamAgent`, `TeamConfig`, `TeamVote`, `TeamConsensus`
- `TeamRunEvent` (large union-like interface)
- `TeamTraceEventUi`, `TeamCompactStatus`
- `TeamClaimTraceUi`, `TeamCoverageTraceUi`, `TeamToolTraceUi`
- `TeamAgentLogKind`, `TeamAgentLogUi`, `TeamAgentTraceUi`
- `TeamBlackboardTraceUi`, `TeamRunUi`

**Why first:** Team types are the largest single domain group
(~250L) and are self-contained — no cross-references to
other type groups except `ConversationSummary` (which stays).

**Risk:** Low. Pure type definitions.

**Tests:** 5+ cases — import verification, type compatibility.

### Slice 2 — Extract tool block types to `chat/tool-types.ts`

**What moves out (~100 lines):**

- `ToolBlockUi` interface
- `ToolBlockStatus` type
- Related tool display types

**Why now:** Tool types are referenced by the `tool-block/`
component directory — aligning types with their consumers.

**Risk:** Low.

**Tests:** 5 cases.

### Slice 3 — Extract model/streaming types to `chat/models.ts`

**What moves out (~150 lines):**

- `ModelProvider`, `ReasoningPreset`, `PromptMode`
- `reasoningPresets` array, `reasoningTokenBudget` function
- `LlmModel` interface, `localModel` constant
- `StreamChunk` interface
- `CodexAuthStatus`, `ApiErrorEnvelope`

**Risk:** Low — mostly constants and pure types. The runtime
values (`reasoningPresets`, `localModel`) are immutable.

**Tests:** 5+ cases — `reasoningTokenBudget` function behavior.

### Slice 4 — Extract memory types to `chat/memory-types.ts`

**What moves out (~80 lines):**

- `MemoryTraceClassicItem`, `MemoryTraceOperationalItem`
- Related memory trace types

After all slices, the remaining `chat/conversation.ts` contains:
- `ConversationSummary`, `ConversationStatus`, `PersistedMessage`
- `ConversationDetail`, `ChatRequestPayload`
- `ContextAttachment`, `ContextAttachmentType`, `GeneratedImage`
- `ChatCommandInfo`, `SkillSummary`, `SkillDetail`,
  `SkillMarketplaceItem`
- Workspace/session types (~200L total).

**Risk:** Low.

**Tests:** 5 cases.

## Anti-patterns specific to this file

- **Barrel re-exports are mandatory.** Every consumer does
  `import { ... } from "../../types/chat"`. The `index.ts` must
  re-export everything: `export * from "./team"`, etc.
- **Do not move runtime values to type-only files.** The
  `reasoningPresets` array and `reasoningTokenBudget` function
  are runtime code — they go in a file that can be imported
  normally (not under `TYPE_CHECKING`).
- **Do not rename types.** Renaming types in a 71-export file
  would touch dozens of consumers.

## Validation gates

```bash
cd @desktop-electron
npm run typecheck
npm test -- --testPathPattern chat.test
```
