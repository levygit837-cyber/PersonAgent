# Main Orchestration in Claude Code

## Overview

Claude Code's main orchestration is built around a **React-based TUI (Terminal UI)** using Ink, with the core conversation loop implemented as an **async generator** that handles message preparation, API streaming, tool execution, and context management. The architecture cleanly separates:

- **`main.tsx`** — CLI entry point, argument parsing, initialization
- **`screens/REPL.tsx`** — Interactive React component managing UI state and user input
- **`QueryEngine.ts`** — Headless/SDK wrapper around the query loop
- **`query.ts`** — The core `query()` async generator (main execution loop)
- **`state/AppStateStore.ts`** — Centralized immutable application state
- **`context.ts`** — System and user context preparation (git status, CLAUDE.md, date)

---

## Execution Loop

### High-Level Flow

```
User Input (REPL.tsx)
    ↓
handlePromptSubmit() → processUserInput()  (slash commands, attachments)
    ↓
onQuery() / QueryEngine.submitMessage()
    ↓
query() async generator (query.ts)
    ↓
  Loop (while true):
    1. Prepare messages (snip → microcompact → collapse → autocompact)
    2. Call model API with streaming (deps.callModel)
    3. Stream assistant message + tool_use blocks
    4. Execute tools (StreamingToolExecutor or runTools)
    5. Yield results back to consumer
    6. Continue if tool_use blocks exist, else return
```

### The Core `query()` Loop

Located in `query.ts` (~line 219), `query()` is an `AsyncGenerator` that yields `StreamEvent | Message | TombstoneMessage | ToolUseSummaryMessage` and returns a `Terminal` reason.

```typescript
export async function* query(params: QueryParams): AsyncGenerator<...> {
  const terminal = yield* queryLoop(params, consumedCommandUuids)
  // Notify completed command UUIDs
  for (const uuid of consumedCommandUuids) {
    notifyCommandLifecycle(uuid, 'completed')
  }
  return terminal
}
```

Inside `queryLoop()` (`query.ts:241`), the loop runs `while (true)` with mutable `State` carried across iterations:

```typescript
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  maxOutputTokensOverride: number | undefined
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  stopHookActive: boolean | undefined
  turnCount: number
  transition: Continue | undefined  // Why the previous iteration continued
}
```

Each iteration:
1. **Pre-API Preparation** — Messages are filtered, compacted, and context is built
2. **Streaming API Call** — `deps.callModel()` streams assistant responses
3. **Post-Streaming Handling** — Error recovery (max_output_tokens, prompt-too-long), stop hooks
4. **Tool Execution** — Tools are executed, results appended to messages
5. **Continue Decision** — If `needsFollowUp` (tool_use blocks detected), loop continues

---

## Message Preparation

Before every API call, messages undergo a **pipeline of compaction and context preparation**:

### 1. Boundary Filtering
```typescript
let messagesForQuery = [...getMessagesAfterCompactBoundary(messages)]
```
Only messages after the most recent compact boundary are sent to the API. Pre-boundary history lives in the full transcript but is not transmitted.

### 2. Tool Result Budgeting
```typescript
messagesForQuery = await applyToolResultBudget(
  messagesForQuery,
  toolUseContext.contentReplacementState,
  persistReplacements ? ... : undefined,
  new Set(toolsWithInfiniteMaxResultSize),
)
```
Enforces per-message size limits on aggregate tool results, with content replacement for oversized results.

### 3. History Snip (`HISTORY_SNIP`)
```typescript
const snipResult = snipModule!.snipCompactIfNeeded(messagesForQuery)
messagesForQuery = snipResult.messages
snipTokensFreed = snipResult.tokensFreed
```
Truncates old history to free tokens when context window pressure is high.

### 4. Microcompact
```typescript
const microcompactResult = await deps.microcompact(messagesForQuery, toolUseContext, querySource)
messagesForQuery = microcompactResult.messages
```
Lightweight compaction that runs before autocompact.

### 5. Context Collapse (`CONTEXT_COLLAPSE`)
```typescript
const collapseResult = await contextCollapse.applyCollapsesIfNeeded(messagesForQuery, toolUseContext, querySource)
messagesForQuery = collapseResult.messages
```
Projects a collapsed view of context — read-time projection over full history. Collapsed messages live in a separate store, not the REPL array.

### 6. Autocompact
```typescript
const { compactionResult, consecutiveFailures } = await deps.autocompact(
  messagesForQuery, toolUseContext, cacheSafeParams, querySource, tracking, snipTokensFreed
)
```
If token count exceeds threshold, automatically summarizes old history into a compact summary message. This is the **heavyweight** compaction step.

### 7. Context Prepending
```typescript
const fullSystemPrompt = asSystemPrompt(appendSystemContext(systemPrompt, systemContext))
```
The final system prompt has system context appended. Messages are prepended with user context:
```typescript
messages: prependUserContext(messagesForQuery, userContext)
```

---

## Streaming Architecture

### API Streaming

The actual API call happens in `services/api/claude.ts` via `queryModelWithStreaming`. The `query.ts` loop consumes it as an async iterable:

```typescript
for await (const message of deps.callModel({
  messages: prependUserContext(messagesForQuery, userContext),
  systemPrompt: fullSystemPrompt,
  thinkingConfig: toolUseContext.options.thinkingConfig,
  tools: toolUseContext.options.tools,
  signal: toolUseContext.abortController.signal,
  options: { model: currentModel, ... }
})) {
  // Handle streamed message (assistant text, thinking, tool_use, etc.)
  yield yieldMessage
}
```

### Stream Events

The streaming loop handles:
- **`message_start`** — Reset current message usage tracking
- **`content_block_start/delta/stop`** — Accumulate text/thinking/tool_use blocks
- **`message_delta`** — Capture stop_reason, usage updates
- **`message_stop`** — Accumulate total usage

### Withheld Errors

Certain recoverable errors are **withheld from yielding** until recovery is attempted:
- `prompt_too_long` → tried by context collapse drain, then reactive compact
- `max_output_tokens` → escalated to 64k tokens, then multi-turn recovery
- Media size errors → reactive compact strip-retry

```typescript
let withheld = false
if (feature('CONTEXT_COLLAPSE') && contextCollapse?.isWithheldPromptTooLong(message, ...)) {
  withheld = true
}
if (reactiveCompact?.isWithheldPromptTooLong(message)) {
  withheld = true
}
if (!withheld) {
  yield yieldMessage
}
```

---

## Tool Call Integration

### Tool Detection During Streaming

As assistant messages stream in, `tool_use` blocks are detected:

```typescript
if (message.type === 'assistant') {
  assistantMessages.push(message)
  const msgToolUseBlocks = message.message.content.filter(c => c.type === 'tool_use')
  if (msgToolUseBlocks.length > 0) {
    toolUseBlocks.push(...msgToolUseBlocks)
    needsFollowUp = true  // Signal to continue the loop
  }
}
```

### Streaming Tool Execution

When `config.gates.streamingToolExecution` is enabled, `StreamingToolExecutor` handles tools **as they stream in**:

```typescript
const streamingToolExecutor = new StreamingToolExecutor(tools, canUseTool, toolUseContext)
// During streaming:
for (const toolBlock of msgToolUseBlocks) {
  streamingToolExecutor.addTool(toolBlock, message)
}
// Yield completed results immediately:
for (const result of streamingToolExecutor.getCompletedResults()) {
  if (result.message) {
    yield result.message
    toolResults.push(...)
  }
}
```

### Concurrency Model

`StreamingToolExecutor` (`services/tools/StreamingToolExecutor.ts`) implements a **concurrency-safe queue**:

- **Concurrency-safe tools** (e.g., Read, WebFetch) → execute in parallel with each other
- **Non-concurrent tools** (e.g., Bash, Edit) → execute exclusively (alone)
- Tools maintain FIFO order within their concurrency class

```typescript
private canExecuteTool(isConcurrencySafe: boolean): boolean {
  const executingTools = this.tools.filter(t => t.status === 'executing')
  return (
    executingTools.length === 0 ||
    (isConcurrencySafe && executingTools.every(t => t.isConcurrencySafe))
  )
}
```

### Batch Tool Execution (Fallback)

When streaming tool execution is disabled:
```typescript
const toolUpdates = runTools(toolUseBlocks, assistantMessages, canUseTool, toolUseContext)
for await (const update of toolUpdates) {
  if (update.message) {
    yield update.message
    toolResults.push(...)
  }
}
```

---

## State Management

### AppStateStore

`AppStateStore.ts` defines a single, comprehensive `AppState` type (~450 lines) tracked as **deeply immutable** state via a custom store (`Store<AppState>`).

Key state domains:

| Domain | Description |
|--------|-------------|
| `settings` | User settings JSON |
| `tasks` | Map of task ID → TaskState (background agents, teammates) |
| `agentNameRegistry` | Map of agent name → AgentId for routing |
| `toolPermissionContext` | Permission mode, always-allow rules, denials |
| `mcp` | MCP server connections, tools, commands, resources |
| `plugins` | Enabled/disabled plugins, errors, installation status |
| `speculation` | Prompt suggestion speculation state |
| `inbox` | Cross-agent message inbox |
| `todos` | Per-agent todo lists |
| `initialMessage` | Pending initial message from CLI args |
| `fastMode` / `effortValue` / `advisorModel` | Model behavior modifiers |
| `replBridge*` | Always-on bridge connection state |

### State Updates

State is updated via `setAppState(prev => ({ ...prev, ...updates }))`. The REPL reads state via `useAppState(selector)` hooks.

### QueryGuard

REPL uses a `QueryGuard` state machine (instead of booleans) to track query lifecycle:
```typescript
const queryGuard = React.useRef(new QueryGuard()).current
const isQueryActive = React.useSyncExternalStore(queryGuard.subscribe, queryGuard.getSnapshot)
```

- `reserve()` → `tryStart()` → `end()` / `cancelReservation()`
- Prevents desync between React state and refs
- Guards against concurrent `onQuery` calls by enqueuing instead

---

## Key Code Snippets

### Query Loop Entry (query.ts:241)
```typescript
async function* queryLoop(params: QueryParams, consumedCommandUuids: string[]) {
  const { systemPrompt, userContext, systemContext, canUseTool, ... } = params
  let state: State = {
    messages: params.messages,
    toolUseContext: params.toolUseContext,
    maxOutputTokensOverride: params.maxOutputTokensOverride,
    autoCompactTracking: undefined,
    ...
  }

  while (true) {
    let { toolUseContext } = state
    const { messages, autoCompactTracking, ... } = state

    // 1. PREPARE MESSAGES
    let messagesForQuery = [...getMessagesAfterCompactBoundary(messages)]
    messagesForQuery = await applyToolResultBudget(...)
    // snip, microcompact, collapse, autocompact...

    // 2. STREAM API RESPONSE
    for await (const message of deps.callModel({ ... })) {
      // Handle streaming fallback, withheld errors, backfill inputs
      yield yieldMessage
      if (message.type === 'assistant') {
        assistantMessages.push(message)
        const toolUses = message.message.content.filter(c => c.type === 'tool_use')
        if (toolUses.length > 0) needsFollowUp = true
      }
    }

    // 3. HANDLE ABORT / ERRORS / RECOVERY
    if (toolUseContext.abortController.signal.aborted) { ... }
    if (!needsFollowUp) {
      // Handle stop hooks, max_output_tokens recovery, token budget
      return { reason: 'completed' }
    }

    // 4. EXECUTE TOOLS
    const toolUpdates = streamingToolExecutor
      ? streamingToolExecutor.getRemainingResults()
      : runTools(toolUseBlocks, assistantMessages, canUseTool, toolUseContext)
    for await (const update of toolUpdates) {
      if (update.message) yield update.message
    }

    // 5. CONTINUE LOOP
    state = {
      messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
      toolUseContext: updatedToolUseContext,
      ...
    }
  }
}
```

### REPL Query Integration (REPL.tsx:2793)
```typescript
for await (const event of query({
  messages: messagesIncludingNewMessages,
  systemPrompt,
  userContext,
  systemContext,
  canUseTool,
  toolUseContext,
  querySource: getQuerySourceForREPL()
})) {
  onQueryEvent(event)
}
```

### Context Preparation (context.ts)
```typescript
export const getSystemContext = memoize(async () => {
  const gitStatus = await getGitStatus()  // Cached, includes branch, status, recent commits
  return { ...(gitStatus && { gitStatus }) }
})

export const getUserContext = memoize(async () => {
  const claudeMd = await getClaudeMds(filterInjectedMemoryFiles(await getMemoryFiles()))
  return { ...(claudeMd && { claudeMd }), currentDate: `Today's date is ${getLocalISODate()}.` }
})
```

---

## Insights for PersonAgent

### 1. Generator-Based Loop Architecture
Claude Code's core loop is an **async generator**, not a callback/promise chain. This allows:
- Unified handling of streaming events, messages, and control flow
- Clean cancellation via generator `.return()`
- Consumer (REPL) processes events incrementally without blocking

**Takeaway:** Consider using async generators for the main agent loop instead of event emitters or callbacks.

### 2. Layered Compaction Strategy
They use **four layers** of context management:
- **Snip** — cheap truncation
- **Microcompact** — lightweight summary
- **Context Collapse** — granular read-time projection
- **Autocompact** — heavy summarization with API call

**Takeaway:** Don't rely on a single compaction mechanism. Layer cheap mechanisms first, escalate to expensive ones only when needed.

### 3. Streaming Tool Execution
Tools execute **concurrently with streaming**, not after the full response arrives. `StreamingToolExecutor` manages:
- Parallel execution of safe tools
- Exclusive execution of dangerous tools
- Immediate yielding of results

**Takeaway:** For latency-sensitive agents, start tool execution as soon as tool_use blocks arrive, don't wait for the full assistant message.

### 4. Withheld Error Recovery
Recoverable errors (prompt-too-long, max_output_tokens) are **not immediately surfaced**. The loop attempts recovery (compaction, escalation) and only surfaces the error if recovery fails.

**Takeaway:** Build error recovery into the loop itself, not as a separate retry layer.

### 5. QueryGuard State Machine
Instead of `isLoading` boolean + ref, they use a **state machine with generations** to handle races between concurrent queries, cancellations, and resubmissions.

**Takeaway:** Use generational counters or state machines for concurrent request management instead of simple booleans.

### 6. Immutable State with Functional Updates
`AppState` is deep-immutable, updated via `(prev) => ({ ...prev, ... })`. This enables:
- Predictable change detection
- Time-travel debugging potential
- Safe concurrent reads

**Takeaway:** Keep orchestration state immutable and update functionally.

### 7. Separation of Concerns
- `main.tsx` → CLI/bootstrap only
- `REPL.tsx` → UI/rendering only
- `QueryEngine.ts` → SDK/headless wrapper
- `query.ts` → Pure logic loop (no React, no UI)

**Takeaway:** Separate the core agent loop from UI and entry point concerns. The same `query()` generator powers both interactive and headless modes.
