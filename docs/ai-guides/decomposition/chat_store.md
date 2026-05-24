# Playbook: Decompose `chat-store.ts`

**Target file:** `@desktop-electron/src/stores/chat-store.ts`
(3,307 lines)

**Target directory:** `@desktop-electron/src/stores/chat-store/`
(does not exist; create it with sub-modules)

**Test files:**
- `@desktop-electron/src/stores/chat-store.team.test.ts`
- `@desktop-electron/src/stores/chat-store.workspace.test.ts`

Read `_protocol.md` first.

## Why this file is hard

`chat-store.ts` is a Zustand store that owns the entire
client-side chat state machine. It manages:

1. **Conversation lifecycle** — loading, switching, new
   conversation.
2. **Message stream** — append, update, finalize, branch,
   rewind.
3. **Streaming state** — token totals, abort controller,
   active agent.
4. **Plan-mode approval flow** — pending plan, accept,
   continue, cancel.
5. **Tool approval flow** — pending tool, approve, reject.
6. **Composer state** — annotations, plan-mode toggle.
7. **Live usage / context-window estimation.**
8. **Local slash commands** (`/model`, `/effort`, `/help`).
9. **Browser tool blocks** synchronization.

The store is created by `createChatStore` and exported via
React context (so multiple panes can have isolated stores).

## Public contract that must be preserved

Every method on `ChatState` is referenced by at least one
component. Do not rename. Do not change signatures.

The exported helpers:

- `createChatStore`
- `defaultChatStore`
- `ChatStoreProvider`, `ChatStoreContext`
- `useChatStore`
- `getDefaultChatStore`
- `ChatStoreApi` type

All must remain exported from `chat-store.ts` after extraction
(re-export from sub-modules).

## Proposed slices (in order)

Zustand makes per-slice extraction natural via the **slice
pattern**: each slice is a function `(set, get) => ({...})`
that returns its own actions, and the store is composed by
spreading slices together. We'll use that pattern.

### Slice 1 — Extract pure helpers + constants to `chat-store/internal.ts`

**What moves out** (lines 55–67, 825–1100):

- `thinkingStates`, `textFlushBuffers` Maps
- `STREAM_TEXT_FLUSH_MS`, `MAX_TEAM_AGENT_LOGS`, `liveTokenTotals`
- `TextFlushBuffer` type
- Pure helpers:
  - `getEffectiveWorkspaceRoot`
  - `setConversationStatus`
  - `inferConversationStatus`
  - `conversationForkMessages`
  - `previousUserMessageIndex`
  - `contextAttachmentsFromMessage`
  - `isContextAttachment`
  - `setAgentMessageActionState`
  - `worktreeSlug`
- Slash-command helpers:
  - `localSlashCommands`
  - `modelProviders`, `reasoningPresetValues`
  - `handleLocalSlashCommand`
  - `parseLocalSlashCommand`
  - `appendLocalCommandResult`
  - `applyModelCommand`
  - `applyEffortCommand`
  - `normalizeProvider`
  - `inferProviderForModel`
  - `commandHelpText`

**Why first:** Pure functions and module-level state. No store
dependencies (they receive `set` / `get` as arguments).

**Risk:** Negligible.

**Tests:** `chat-store/internal.test.ts` (new) — 15+ cases
covering the slash-command parser, conversation status
inference, and worktree slug generation. Existing tests cover
the rest via integration.

### Slice 2 — Extract `composerSlice` to `chat-store/composer-slice.ts`

**What moves out:**

- State: `composerAnnotations`, `composerPlanMode`
- Actions: `addComposerAnnotation`, `removeComposerAnnotation`,
  `clearComposerAnnotations`, `setComposerPlanMode`

**Slice signature:**

```ts
export const createComposerSlice = (set: ChatSet, get: ChatGet) => ({
  composerAnnotations: [],
  composerPlanMode: false,
  addComposerAnnotation: (annotation: ComposerAnnotation) =>
    set((state) => ({ /* ... */ })),
  /* ... */
});
```

**Why now:** Composer state is self-contained — no other slice
reads it during updates. Smallest, cheapest slice to validate
the slice pattern.

**Risk:** Negligible.

**Tests:** Existing tests cover; add `chat-store/composer-slice.test.ts`
with 5+ cases.

### Slice 3 — Extract `conversationSlice` to `chat-store/conversation-slice.ts`

**What moves out:**

- State: `conversationId`, `conversationTitle`, `messages`,
  `conversationStatuses`, `loadingConversationId`, `error`
- Actions: `loadConversation`, `startNewConversation`,
  `regenerateAgentMessage`, `rewindUserMessage`,
  `branchAgentMessage`, `clearError`

**Collaborators:**

- `composerSlice` (uses `clearComposerAnnotations`)
- `streamingSlice` (uses `stopStreaming`, `isStreaming`)

**Slices that depend on each other** receive the full `get()`
function and call into siblings via `get().xxx`.

**Risk:** Medium. Conversation loading is async and touches
several other slices. Land after slice 2 so the slice pattern
is proven.

**Tests:** Existing tests (`chat-store.workspace.test.ts`)
cover the workspace-sync branches. Add ~10 new cases for the
conversation-lifecycle paths.

### Slice 4 — Extract `streamingSlice` to `chat-store/streaming-slice.ts`

**What moves out:**

- State: `isStreaming`, `isFinalizing`, `activeAgentId`,
  `activeController`, `liveSessionUsage`, `liveSubAgentIds`,
  `latestTodoSnapshot`, `contextTokenEstimate`,
  `contextWindowEstimate`, `browserToolBlocks`
- Actions: `sendMessage`, `stopStreaming`

**This is the biggest slice** — `sendMessage` is several
hundred lines because it owns the entire token-by-token stream
handling.

**Collaborators:**

- `conversationSlice` (writes new messages)
- `composerSlice` (clears annotations on send)
- `planApprovalSlice` (sets pending plan when received)
- `toolApprovalSlice` (sets pending tool when received)
- Module-level state: `liveTokenTotals`, `thinkingStates`,
  `textFlushBuffers`

**Risk:** High. The streaming code is performance-sensitive
(rate-limited UI updates via `textFlushBuffers`) and stateful
(`thinkingStates` per agent). Pin the observable behavior
with tests before extracting.

**Tests:** Existing team-chat test (`chat-store.team.test.ts`)
covers the streaming path. Add ~15 new cases for individual
chunk-type handlers (text chunk, reasoning chunk, tool chunk,
finish reason, error).

### Slice 5 — Extract `planApprovalSlice` to
`chat-store/plan-approval-slice.ts`

**What moves out:**

- State: `pendingPlanApproval`, `isProcessingPlanDecision`
- Actions: `approvePendingPlan`, `continuePendingPlan`,
  `cancelPendingPlan`

**Risk:** Low. Plan approval is self-contained.

**Tests:** Add ~8 cases.

### Slice 6 — Extract `toolApprovalSlice` to
`chat-store/tool-approval-slice.ts`

**What moves out:**

- State: `pendingToolApproval`, `nextStepSuggestion`
- Actions: `approvePendingTool`, `rejectPendingTool`

**Risk:** Low.

**Tests:** Add ~6 cases.

### Slice 7 — Extract `feedbackSlice`

**What moves out:**

- Actions: `setAgentFeedback`, `setReasoningBlockExpanded`

**Risk:** Negligible.

### Slice 8 — Compose the store in `chat-store.ts`

After all slices are extracted, the main file becomes:

```ts
export function createChatStore(options: CreateChatStoreOptions = {}): ChatStoreApi {
  return createStore<ChatState>((set, get) => ({
    workspaceRoot: options.initialWorkspaceRoot,
    setWorkspaceRoot: (root) => set({ workspaceRoot: root?.trim() || undefined }),
    ...createComposerSlice(set, get),
    ...createConversationSlice(set, get, options),
    ...createStreamingSlice(set, get, options),
    ...createPlanApprovalSlice(set, get),
    ...createToolApprovalSlice(set, get),
    ...createFeedbackSlice(set, get),
  }));
}
```

Plus the existing `ChatStoreProvider` / `useChatStore` exports.

**Target line count:** under 250 lines.

## Pre-condition tests

```bash
cd @desktop-electron
npm run typecheck
npm test -- chat-store
```

The team-chat and workspace tests are the primary safety net.
Run them after every slice.

## Anti-patterns specific to Zustand decomposition

- **Do not call `set()` from inside a sibling slice's action
  unless you receive `set` as an argument.** Each slice's
  factory has access to `set`/`get`; sibling slices invoke
  shared utilities by calling through `get()` to retrieve the
  current state and then calling their own actions.
- **Do not duplicate state across slices.** If two slices both
  need `conversationId`, exactly one owns it and the other
  reads via `get().conversationId`.
- **Do not introduce middleware during extraction.** If the
  original store uses `devtools` or `persist`, the new store
  must use the same middleware in the same order. Adding
  `immer` or `subscribeWithSelector` is a behavior change —
  separate PR.
- **Do not change action signatures.** Components type their
  prop access through `useChatStore((s) => s.foo)` — changing
  `foo`'s signature is a breaking change everywhere.
- **Do not split a transactional update across slices.** If an
  action sets `isStreaming: false` and clears `activeController`
  in the same `set()` call, keep them in the same slice. Two
  separate `set()` calls create an intermediate render where
  one is updated and the other isn't.

## Validation gates

```bash
cd @desktop-electron
npm run lint
npm test
```

Frontend test count must not decrease.

## Frontend slice-pattern reference

For the canonical slice pattern in Zustand, see
[zustand docs §slicing-the-store](https://github.com/pmndrs/zustand/blob/main/docs/guides/slices-pattern.md).
Our implementation deviates only in passing `options` through
to the slices that need it (e.g., `syncWorkspaceSelection`).
