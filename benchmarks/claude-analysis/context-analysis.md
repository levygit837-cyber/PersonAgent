# Context Analysis & Query Engine in Claude Code

## Overview

Claude Code's context architecture is a sophisticated multi-layered pipeline that assembles, prioritizes, compacts, and dispatches context to the Anthropic API. The system is designed around three core modules:

1. **Context Analysis** (`analyzeContext.ts`) — Token accounting and visualization
2. **Query Engine** (`QueryEngine.ts` + `query.ts`) — Lifecycle owner for the conversation loop
3. **System Prompt Assembly** (`constants/prompts.ts`, `utils/systemPrompt.ts`, `utils/queryContext.ts`) — Dynamic construction of the system prompt with aggressive prompt-caching optimization

The architecture follows a clear pipeline:

```
User Input → processUserInput → submitMessage()
    → fetchSystemPromptParts() [systemPrompt + userContext + systemContext]
    → getAttachmentMessages() [dynamic context injection]
    → snipCompact → microcompact → contextCollapse → autoCompact
    → prependUserContext() → API call
    → stream response → tool execution → recurse
```

---

## Context Analysis (`analyzeContext.ts`)

`analyzeContext.ts` is the **telemetry and accounting layer** for the context window. It does NOT decide what goes into context — that happens upstream in `query.ts` and `attachments.ts` — but it precisely measures what is already there.

### What It Measures

The `analyzeContextUsage()` function returns a `ContextData` object that breaks down context into categories:

| Category | Source | Notes |
|----------|--------|-------|
| System prompt | `effectiveSystemPrompt` sections | Always shown first; per-section breakdown for ant users |
| System tools | Built-in tools minus skills | Deferred via tool search when enabled |
| MCP tools | `tools.filter(t => t.isMcp)` | Can be deferred (loaded on-demand) |
| Custom agents | `agentDefinitions.activeAgents` | Only non-built-in agents counted |
| Memory files | `CLAUDE.md` files | Filtered by `filterInjectedMemoryFiles` |
| Skills | Skill frontmatter (name/desc/whenToUse) | Full content loaded only on invocation |
| Messages | Conversation history | Broken down by tool calls, results, attachments, assistant/user text |
| Reserved buffer | Autocompact or manual buffer | 13K tokens for autocompact, 3K for manual |
| Free space | Remaining window | Calculated after all above |

### Deferred Tool Accounting

A critical feature is **deferred tool tracking**. When `isToolSearchEnabled()` returns true:

- **Built-in tools**: Some are deferred (e.g., less-common tools). Only always-loaded + previously-used deferred tools count toward token usage.
- **MCP tools**: All MCP tools can be deferred. Only tools that have been actually invoked in the conversation are "loaded" and counted.

```typescript
// From analyzeContext.ts ~510
builtInToolTokens: alwaysLoadedTokens + loadedDeferredTokens,
deferredBuiltinTokens: totalDeferredTokens - loadedDeferredTokens,
```

This is a major token-saving mechanism — MCP server tool definitions can be massive, and deferring them saves thousands of tokens per turn.

### Token Counting Strategy

Claude Code uses a **three-tier fallback** for token counting:
1. **Primary**: Anthropic API token counting endpoint (`countMessagesTokensWithAPI`)
2. **Fallback**: Haiku model call for estimation (`countTokensViaHaikuFallback`)
3. **Rough estimation**: Local heuristic (`roughTokenCountEstimation`) used for message breakdowns and proportional splits

### Message Breakdown

Messages are analyzed with `approximateMessageTokens()`, which uses `microcompactMessages()` first, then categorizes each block:

- `toolCallTokens` — assistant `tool_use` blocks
- `toolResultTokens` — user `tool_result` blocks
- `attachmentTokens` — attachment messages
- `assistantMessageTokens` — text/thinking blocks
- `userMessageTokens` — user text blocks

This powers the per-tool token insights in the `/context` command.

---

## Query Engine (`query.ts` / `QueryEngine.ts`)

### QueryEngine.ts — The Orchestrator

`QueryEngine` is a class that owns **one conversation**. Each `submitMessage()` call starts a new turn within that conversation. It:

1. Fetches system prompt parts via `fetchSystemPromptParts()`
2. Processes user input (slash commands, attachments)
3. Yields a `buildSystemInitMessage()` to signal SDK consumers
4. Delegates to `query()` for the actual loop
5. Manages transcript persistence, usage tracking, and result formatting

```typescript
// QueryEngine.ts ~184
export class QueryEngine {
  private mutableMessages: Message[]
  private totalUsage: NonNullableUsage
  // ...
  async *submitMessage(prompt, options) { /* ... */ }
}
```

### query.ts — The State Machine Loop

`query.ts` contains the **heart of the conversation engine**: `queryLoop()`, an `async function*` that implements a state machine with explicit `State` transitions.

#### The Query Pipeline (per iteration)

```typescript
// query.ts ~307-728
while (true) {
  1. Start memory prefetch (async, non-blocking)
  2. Start skill discovery prefetch (async, non-blocking)
  3. Get messages after last compact boundary
  4. Apply tool result budget (content replacement for large results)
  5. SNIP compaction (HISTORY_SNIP feature)
  6. MICROCOMPACT (cached microcompact for tool result clearing)
  7. CONTEXT COLLAPSE (marble_origami feature)
  8. AUTOCOMPACT (if above threshold)
  9. Build fullSystemPrompt = appendSystemContext(systemPrompt, systemContext)
  10. API call with prependUserContext(messagesForQuery, userContext)
  11. Stream response, accumulate assistant messages + tool_use blocks
  12. If needsFollowUp: execute tools → collect attachments → recurse
  13. Else: handle stop hooks, max turns, token budget, return
}
```

#### Recovery Paths

The loop has **sophisticated error recovery**:

- **Prompt-too-long (413)**: Withheld during streaming. After stream, tries context-collapse drain first (cheap), then reactive compact (full summary). If both fail, surfaces the error.
- **Max output tokens hit**: Escalates from 8K → 64K cap, then injects a recovery meta-message asking the model to continue mid-thought.
- **Model fallback**: On `FallbackTriggeredError`, retries with fallback model, strips thinking signatures, and tombstones orphaned messages.
- **Circuit breaker**: Autocompact stops retrying after 3 consecutive failures.

#### Context Compaction Hierarchy

Multiple compaction strategies run in a specific order:

1. **Snip** (`HISTORY_SNIP`) — Removes old messages from the tail, preserves recent assistant. Fast, lossy.
2. **Microcompact** — Clears old tool results (function result clearing), keeps recent N. Cache-aware.
3. **Context Collapse** (`CONTEXT_COLLAPSE`) — Commits staged collapses, creates read-time projections.
4. **Autocompact** — Full conversation summary via a forked agent. Most expensive, most effective.

The order matters: snip and microcompact run BEFORE autocompact, so if they bring usage under threshold, autocompact is skipped — preserving granular context.

---

## System Prompt Assembly

### Priority Stack (`utils/systemPrompt.ts`)

`buildEffectiveSystemPrompt()` implements a strict priority hierarchy:

```
0. overrideSystemPrompt     (REPLACES everything, e.g., loop mode)
1. Coordinator prompt       (if coordinator mode active)
2. Agent system prompt      (if mainThreadAgentDefinition set)
   - Proactive mode: APPENDED to default
   - Normal mode: REPLACES default
3. Custom system prompt     (--system-prompt CLI flag)
4. Default system prompt    (standard Claude Code prompt)
+ appendSystemPrompt        (always added at end, unless override set)
```

```typescript
// utils/systemPrompt.ts ~41-123
export function buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt,
  overrideSystemPrompt,
}): SystemPrompt { /* ... */ }
```

### Prompt Sections (`constants/prompts.ts`)

`getSystemPrompt()` builds the default prompt as an array of sections. A critical optimization is the **dynamic boundary marker**:

```typescript
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```

Everything BEFORE this marker is **static** (cross-session cacheable with `scope: 'global'`). Everything AFTER is **dynamic** (session-specific, org-scoped or uncached).

Static sections include:
- `getSimpleIntroSection()` — "You are an interactive agent..."
- `getSimpleSystemSection()` — markdown rules, tool permission mode
- `getSimpleDoingTasksSection()` — coding style, task decomposition
- `getActionsSection()` — risky action guidelines
- `getUsingYourToolsSection()` — tool preference rules
- `getSimpleToneAndStyleSection()` — output formatting rules

Dynamic sections (post-boundary) include:
- Session-specific guidance (tool availability, agent instructions)
- Memory (`loadMemoryPrompt()`)
- Environment info (`computeSimpleEnvInfo()`)
- Language preference
- Output style config
- MCP instructions
- Scratchpad instructions
- Token budget instructions

This boundary is what enables Claude Code's **aggressive prompt caching** — the static prefix (~60-80% of the prompt) hits the global cache across all users.

### Cache Scope Splitting (`utils/api.ts`)

`splitSysPromptPrefix()` breaks the system prompt into blocks with different cache scopes:

```typescript
// utils/api.ts ~321-435
export function splitSysPromptPrefix(systemPrompt, options): SystemPromptBlock[] {
  // Global cache mode: 4 blocks
  // - Attribution header (null)
  // - System prompt prefix (null)
  // - Static content before boundary (global)
  // - Dynamic content after boundary (null)

  // Default/org mode: 3 blocks
  // - Attribution header (null)
  // - System prompt prefix (org)
  // - Everything else concatenated (org)
}
```

### Context Assembly for API Call

The final API payload is assembled in `query.ts`:

```typescript
// query.ts ~449-451, ~659-661
const fullSystemPrompt = asSystemPrompt(
  appendSystemContext(systemPrompt, systemContext)
)

// ...

deps.callModel({
  messages: prependUserContext(messagesForQuery, userContext),
  systemPrompt: fullSystemPrompt,
  // ...
})
```

Where:
- `systemPrompt` = effective system prompt (from `buildEffectiveSystemPrompt`)
- `systemContext` = `getSystemContext()` → `{ gitStatus, cacheBreaker }`
- `userContext` = `getUserContext()` → `{ claudeMd, currentDate }`

`prependUserContext()` injects the user context as a **meta user message** wrapped in `<system-reminder>` tags at the start of the message array:

```typescript
// utils/api.ts ~449-474
export function prependUserContext(messages, context): Message[] {
  return [
    createUserMessage({
      content: `<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# claudeMd\n...\n# currentDate\n...</system-reminder>\n`,
      isMeta: true,
    }),
    ...messages,
  ]
}
```

---

## Context Prioritization

### How Claude Decides What to Include/Exclude

Claude Code does **NOT** use semantic search or embedding-based retrieval for core context assembly. Instead, it uses a **rule-based, budget-aware prioritization system**:

#### 1. Tool Definition Budgeting (Deferred Loading)

The most important token-saving mechanism is **tool search / deferred loading**:

- Always-loaded tools: Core tools (Bash, FileRead, FileWrite, FileEdit, Glob, Grep, Agent, AskUserQuestion, etc.) are always in context.
- Deferred built-in tools: Less-common tools are deferred and only loaded when referenced by the model.
- Deferred MCP tools: ALL MCP tools are deferred by default. They are loaded individually when the model issues a `ToolSearchTool` call or references them.

This is controlled by `isToolSearchEnabled()` and `isDeferredTool()` checks in `analyzeContext.ts` and `toolSearch.ts`.

#### 2. File Content Prioritization

Files enter context through multiple paths with different priorities:

| Path | Priority | Mechanism |
|------|----------|-----------|
| `@-mentioned` files in user input | Highest | Directly attached as `FileAttachment` |
| `already_read_file` | High | Re-attaches files the model already read this turn |
| `edited_text_file` | High | Snippets of files the model just edited |
| Post-compact file restoration | Medium | Up to 5 recently-read files restored after compaction |
| Nested memory (`CLAUDE.md`) | Medium | Loaded from `.claude/` or `CLAUDE_CODE_MEMORY_PATH` |
| Relevant memories prefetch | Low | Async surfacing of relevant memory files (bounded by 60KB/session) |

#### 3. Attachment System (`attachments.ts`)

The attachment system is the **primary mechanism for dynamic context injection**. `getAttachmentMessages()` generates 30+ types of attachments:

- **User input attachments**: `@-mentioned files`, MCP resources, agent mentions, skill discovery
- **Thread-safe attachments**: queued commands, date changes, deferred tools delta, agent listing delta, MCP instructions delta, changed files, nested memory, dynamic skills, skill listings, plan mode reminders, todo/task reminders, teammate mailbox, critical system reminders
- **Main-thread only**: IDE selection, diagnostics, LSP diagnostics, token usage, budget, async hook responses

Attachments are **not free** — they consume message tokens. The system uses `maybe()` wrappers with timeouts (1s default) to prevent attachment generation from blocking the critical path.

#### 4. Context Collapse (Experimental)

`CONTEXT_COLLAPSE` is an experimental feature that creates **read-time projections** over conversation history. Instead of physically removing messages, it stages "collapses" (summaries of message ranges) and replays them on every `projectView()` call. This preserves granular context longer before needing a full autocompact.

---

## The Role of `agentContext.ts`

`agentContext.ts` is **NOT** involved in assembling LLM context. Instead, it provides **AsyncLocalStorage-based analytics attribution** for tracking agent identity across async operations.

```typescript
// utils/agentContext.ts ~93-110
const agentContextStorage = new AsyncLocalStorage<AgentContext>()

export function getAgentContext(): AgentContext | undefined {
  return agentContextStorage.getStore()
}

export function runWithAgentContext<T>(context: AgentContext, fn: () => T): T {
  return agentContextStorage.run(context, fn)
}
```

It supports two agent types:
- **SubagentContext**: In-process delegated tasks (Agent tool)
- **TeammateAgentContext**: Swarm teammates with team coordination

This ensures that when multiple agents run concurrently (e.g., backgrounded with ctrl+b), their analytics events don't get mixed up in shared `AppState`.

---

## How Claude Handles Large File Reads

Large files are handled at the **tool layer** (`FileReadTool`) with multiple safeguards:

### Token Budgeting

```typescript
// utils/attachments.ts ~269-277
const MAX_MEMORY_LINES = 200
const MAX_MEMORY_BYTES = 4096
```

Memory file attachments are capped at 200 lines and 4KB per file. The `readFileInRange()` utility supports `truncateOnByteLimit`.

### File Read Tool Limits

`FileReadTool` has configurable limits:
- `MAX_LINES_TO_READ` — default line cap
- `getDefaultFileReadingLimits()` — per-model token limits
- `MaxFileReadTokenExceededError` — thrown when a single read would exceed budget

### Content Replacement (`applyToolResultBudget`)

Before each API call, `query.ts` applies `applyToolResultBudget()` to messages. This replaces oversized tool results with truncated versions or stubs, controlled by `toolUseContext.contentReplacementState`.

### Post-Compact File Budget

After compaction, file restoration is strictly budgeted:

```typescript
// services/compact/compact.ts ~122-124
export const POST_COMPACT_MAX_FILES_TO_RESTORE = 5
export const POST_COMPACT_TOKEN_BUDGET = 50_000
export const POST_COMPACT_MAX_TOKENS_PER_FILE = 5_000
```

---

## Key Code Snippets

### 1. System Prompt Assembly Priority

```typescript
// utils/systemPrompt.ts
export function buildEffectiveSystemPrompt({
  mainThreadAgentDefinition,
  toolUseContext,
  customSystemPrompt,
  defaultSystemPrompt,
  appendSystemPrompt,
  overrideSystemPrompt,
}): SystemPrompt {
  if (overrideSystemPrompt) {
    return asSystemPrompt([overrideSystemPrompt])
  }
  // Coordinator mode...
  // Agent mode...
  return asSystemPrompt([
    ...(agentSystemPrompt
      ? [agentSystemPrompt]
      : customSystemPrompt
        ? [customSystemPrompt]
        : defaultSystemPrompt),
    ...(appendSystemPrompt ? [appendSystemPrompt] : []),
  ])
}
```

### 2. Prompt Cache Boundary

```typescript
// constants/prompts.ts
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY = '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'

// In getSystemPrompt():
return [
  // --- Static content (cacheable) ---
  getSimpleIntroSection(outputStyleConfig),
  getSimpleSystemSection(),
  // ...
  // === BOUNDARY MARKER - DO NOT MOVE OR REMOVE ===
  ...(shouldUseGlobalCacheScope() ? [SYSTEM_PROMPT_DYNAMIC_BOUNDARY] : []),
  // --- Dynamic content (registry-managed) ---
  ...resolvedDynamicSections,
].filter(s => s !== null)
```

### 3. Deferred Tool Token Accounting

```typescript
// analyzeContext.ts
const isDeferred = await isToolSearchEnabled(model, tools, ...)
const alwaysLoadedTools = builtInTools.filter(t => !isDeferredTool(t))
const deferredBuiltinTools = builtInTools.filter(t => isDeferredTool(t))

// Only count always-loaded + any loaded deferred tools
builtInToolTokens: alwaysLoadedTokens + loadedDeferredTokens,
deferredBuiltinTokens: totalDeferredTokens - loadedDeferredTokens,
```

### 4. Query Loop State Transition

```typescript
// query.ts
const next: State = {
  messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
  toolUseContext: toolUseContextWithQueryTracking,
  autoCompactTracking: tracking,
  turnCount: nextTurnCount,
  maxOutputTokensRecoveryCount: 0,
  hasAttemptedReactiveCompact: false,
  pendingToolUseSummary: nextPendingToolUseSummary,
  maxOutputTokensOverride: undefined,
  stopHookActive,
  transition: { reason: 'next_turn' },
}
state = next
```

### 5. Context Category Creation

```typescript
// analyzeContext.ts ~1008-1156
const cats: ContextCategory[] = []
if (systemPromptTokens > 0) {
  cats.push({ name: 'System prompt', tokens: systemPromptTokens, color: 'promptBorder' })
}
if (systemToolsTokens > 0) {
  cats.push({ name: 'System tools', tokens: systemToolsTokens, color: 'inactive' })
}
if (mcpToolTokens > 0) {
  cats.push({ name: 'MCP tools', tokens: mcpToolTokens, color: 'cyan_FOR_SUBAGENTS_ONLY' })
}
// ... memory, skills, messages, reserved, free space
```

---

## Insights for PersonAgent

### 1. Structured Context Categories

Claude Code's `analyzeContext.ts` proves that **granular token accounting** is essential for debugging context issues and building user trust. The category-based grid (system prompt, tools, MCP tools, agents, memory, skills, messages, free space) should be adopted by PersonAgent. Each category should be independently measurable.

### 2. Deferred Tool Loading is Critical for Scale

MCP tools can easily consume 20-50K tokens. Claude Code's **tool search / deferred loading** pattern (`isDeferredTool`, `loadedMcpToolNames`, `loadedDeferredTokens`) is essential for any agent framework supporting external tool servers. PersonAgent should implement a similar mechanism where tool schemas are loaded on-demand rather than all-at-once.

### 3. Static/Dynamic System Prompt Split for Caching

The `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` pattern enables **global prompt caching** across sessions. For PersonAgent, this means:
- Keep persona instructions, coding style, and tool-usage rules in a **static prefix**
- Put project-specific info, current date, git status, and dynamic instructions **after the boundary**
- This dramatically reduces cache_creation costs

### 4. Multiple Compaction Strategies with Clear Precedence

Claude Code runs **four compaction layers** in order of increasing cost:
1. Snip (fast, removes old tail)
2. Microcompact (clears old tool results)
3. Context Collapse (staged summaries, read-time projection)
4. Autocompact (full forked-agent summary)

PersonAgent should implement a similar **tiered compaction strategy** rather than a single "summarize everything" approach. Preserve granular context as long as possible.

### 5. Attachment-Based Dynamic Context Injection

Instead of stuffing everything into the system prompt, Claude Code uses **attachment messages** injected into the conversation thread. This includes:
- Changed files
- Relevant memories
- Plan mode reminders
- Todo/task reminders
- Tool deltas

This pattern is more flexible than a monolithic system prompt because attachments can be **conditionally omitted** when not relevant, and they naturally participate in compaction.

### 6. Per-Message Budget Enforcement

`applyToolResultBudget()` runs **before every API call** to enforce size limits on tool results. PersonAgent should adopt similar per-turn budget enforcement rather than hoping tool outputs stay small.

### 7. Context is NOT Semantic Search-Based

Importantly, Claude Code's core context assembly does **not** use embeddings or vector search. Context inclusion is **rule-based** (attachments, file state cache, deferred loading, compaction). The only semantic element is the experimental `EXPERIMENTAL_SKILL_SEARCH` feature for discovering skills. This suggests that for agentic coding, **structured rule-based context assembly** outperforms or is preferred over semantic retrieval for reliability and debuggability.
