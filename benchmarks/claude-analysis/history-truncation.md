# History & Truncation in Claude Code

## Overview

Claude Code does **not** use a simple FIFO or token-count-based truncation for conversation history. Instead, it employs a **multi-layered, defense-in-depth strategy** that operates at different granularities: per-tool-result limits, per-message aggregate budgets, time-based clearing, cache-editing APIs, message snipping, context collapse, proactive summarization (auto-compact), and reactive compaction on API errors. The system is designed to **preserve prompt cache prefixes** wherever possible, since cache misses are expensive.

> **Critical distinction:** `history.ts` is **not** the LLM conversation history — it is the user's **shell-style prompt history** (Up-arrow / Ctrl+R recall). The actual conversation state lives in the REPL's `messages` array, managed through `messages.ts`, `query.ts`, and the compaction services.

---

## History Structure

### 1. Prompt History (`history.ts`)

This file manages the **user's command/prompt history** across sessions, stored in a global JSONL file (`~/.claude/history.jsonl`).

- **Format:** Each entry is a `LogEntry` with `display` text, `pastedContents` (inline or hash-referenced), `timestamp`, `project`, and `sessionId`.
- **Capacity:** `MAX_HISTORY_ITEMS = 100` entries per project, read **newest-first**.
- **Pasted content:** Small pastes (`≤1024 chars`) stored inline; larger pastes hashed and stored in a paste store.
- **Scope:** Shared across all projects; current-session entries are yielded before other sessions' entries.
- **Undo support:** `removeLastFromHistory()` supports undoing the most recent add (used for auto-restore-on-interrupt).

```ts
const MAX_HISTORY_ITEMS = 100
const MAX_PASTED_CONTENT_LENGTH = 1024
```

### 2. Conversation Message History (`utils/messages.ts`)

The actual LLM-facing conversation is an array of `Message` objects with these primary types:

| Type | Role | Content Blocks |
|------|------|----------------|
| `user` | `user` | `text`, `image`, `document`, `tool_result` |
| `assistant` | `assistant` | `text`, `thinking`, `redacted_thinking`, `tool_use` |
| `attachment` | — | Injected metadata (skill listings, tool deltas, etc.) |
| `progress` | — | Streaming progress updates (filtered from API) |
| `system` | — | `compact_boundary`, `microcompact_boundary`, `api_error`, etc. |

Key message properties:
- `uuid`: Unique per message (used for REPL rendering and dedup)
- `message.id`: API-level ID; consecutive assistant fragments share this ID and are merged by `normalizeMessagesForAPI`
- `isMeta`: Synthetic messages hidden from normal transcript view
- `isCompactSummary`: Marks user messages containing a compaction summary
- `toolUseResult`: Native tool output object (used for UI rendering, separate from API-facing `tool_result` blocks)

### 3. API Normalization (`normalizeMessagesForAPI`)

Before sending to the API, messages are normalized:
- **Virtual messages stripped** (`isVirtual`)
- **Consecutive user messages merged** (Bedrock compatibility)
- **Progress & non-local system messages filtered**
- **Attachments reordered** to bubble up until they hit a tool result or assistant message
- **Tool reference blocks** stripped if tool search is disabled
- **Error-triggered block stripping:** If a PDF/image was too large, the problematic block is removed from the preceding meta user message to prevent re-sending it

---

## Truncation Strategy

Claude Code uses **no simple FIFO dropping**. The strategy is a cascading pipeline, from cheapest/least-lossy to most expensive/most-lossy:

```
Per-Tool Result Limit
        ↓
Per-Message Aggregate Budget
        ↓
Microcompact (cache editing or time-based clearing)
        ↓
History Snip
        ↓
Context Collapse (experimental)
        ↓
Auto-Compact (proactive summarization)
        ↓
Reactive Compact (on prompt-too-long API error)
        ↓
Manual /compact (user-initiated)
```

### Layer 1: Per-Tool Result Persistence (`utils/toolResultStorage.ts`)

When an individual tool result exceeds a size threshold, it is **persisted to disk** and replaced with a preview.

- **Default threshold:** `DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000`
- **Per-tool override:** Tools declare `maxResultSizeChars`; clamped by the default unless a GrowthBook flag overrides it.
- **Image skip:** Image blocks are never persisted — they are sent as-is.
- **Empty result guard:** Empty tool results are replaced with `({toolName} completed with no output)` to prevent model stop-sequence issues.

```ts
export const DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000
```

### Layer 2: Per-Message Aggregate Budget (`utils/toolResultStorage.ts`)

Even if each tool result is under its individual limit, N parallel tools can collectively produce an oversized user message. The system enforces a **per-message aggregate budget**:

- **Limit:** `MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000` (overridable via GrowthBook `tengu_hawthorn_window`)
- **Strategy:** Within each API-level user message, the **largest fresh (never-before-seen) tool results** are selected for replacement until the total is under budget.
- **State tracking:** `ContentReplacementState` maintains:
  - `seenIds: Set<string>` — tool_use_ids whose fate is frozen
  - `replacements: Map<string, string>` — exact replacement strings for re-application
- **Prompt cache stability:** Previously replaced results are re-applied byte-identically. Previously unreplaced results are never replaced later (would break cache).

```ts
export const MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000
```

### Layer 3: Microcompact (`services/compact/microCompact.ts`)

Microcompact operates at the tool-result level without full summarization. Two variants exist:

**A. Cached Microcompact** (`feature('CACHED_MICROCOMPACT')`)
- Uses Anthropic's **cache editing API** (`cache_reference`, `cache_edits`)
- Tracks tool results per user message and decides which to delete based on count thresholds (GrowthBook-configurable)
- **Does not mutate local messages** — edits are added at the API layer
- Preserves the cache prefix; only deletes old tool results

**B. Time-Based Microcompact**
- Fires when the time gap since the last assistant message exceeds a threshold (configurable, e.g., 5 minutes)
- **Content-clears** all but the most recent N compactable tool results
- Mutates message content directly: replaces cleared results with `[Old tool result content cleared]`
- Resets cached-MC state because the cache is now cold

Compactable tools: `Read`, `Bash`/`Shell`, `Grep`, `Glob`, `WebSearch`, `WebFetch`, `FileEdit`, `FileWrite`.

### Layer 4: History Snip (`feature('HISTORY_SNIP')`)

- Removes old messages from the **tail** of the conversation while preserving a recent window.
- Operates before autocompact so that if snipping brings token count under threshold, the more expensive compaction is skipped.
- Yields a `SystemMicrocompactBoundaryMessage` when snipping occurs.

### Layer 5: Context Collapse (`feature('CONTEXT_COLLAPSE')`)

- Experimental system that **archives old message groups** into a collapse store.
- Produces a read-time projection over the REPL's full history.
- Runs before autocompact; if collapse is sufficient, autocompact is a no-op.
- Has its own recovery path for prompt-too-long: `recoverFromOverflow()` drains staged collapses.

### Layer 6: Auto-Compact (`services/compact/autoCompact.ts`)

**Proactive compaction** triggered when estimated token usage exceeds a threshold.

- **Threshold:** `effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS` where `AUTOCOMPACT_BUFFER_TOKENS = 13_000`
- **Model-aware:** Uses the current model's context window size, minus output token reservation (`MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000`)
- **Can be disabled** via `DISABLE_AUTO_COMPACT` env var or user config (`autoCompactEnabled`)
- **Circuit breaker:** Stops after 3 consecutive failures to prevent API hammering
- **Recursion guards:** Skipped for `session_memory`, `compact`, and `marble_origami` (ctx-agent) query sources

```ts
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000
export const MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
```

**Auto-compact execution flow:**
1. Check `shouldAutoCompact()` — token count vs threshold
2. Try **session memory compaction** first (cheaper, no API call)
3. Fall back to **`compactConversation()`** — forks an agent to summarize the conversation

### Layer 7: Reactive Compact (`feature('REACTIVE_COMPACT')`)

**Reactive compaction** triggered only when the API returns a **prompt-too-long (413)** error.

- The error is **withheld** from the user during streaming.
- First tries draining **context collapse** staged commits (cheaper).
- Then invokes `reactiveCompactOnPromptTooLong()` which peels oldest API-round groups from the head and re-summarizes.
- Has a retry loop that progressively drops more groups.
- Can also recover from **media-size errors** (image/PDF too large) by stripping media and retrying.

### Layer 8: Manual `/compact`

User-initiated via the `/compact` slash command.

- Tries **session memory compaction** first if no custom instructions
- Then runs **microcompact** to reduce tokens before summarization
- Then calls **`compactConversation()`** with full system prompt context
- Can include **custom instructions** to guide the summary (e.g., "focus on test output")
- Also supports **partial compact** (`/compact from` or `/compact up_to`) around a selected message

---

## Compaction Mechanism

### Full Compaction (`compactConversation` in `services/compact/compact.ts`)

1. **Pre-compact hooks** execute (`executePreCompactHooks`)
2. **Strip images** from messages before sending to the summarizer (images are unnecessary for summarization and can cause PTL)
3. **Strip reinjected attachments** (skill_discovery, skill_listing)
4. **Fork an agent** with the conversation + a compact prompt (`getCompactPrompt`)
5. **PTL retry loop:** If the compact request itself hits prompt-too-long, drop oldest API-round groups via `truncateHeadForPTLRetry` and retry (up to 3 times)
6. **Generate summary** — the model produces an `<analysis>` block (stripped later) and a `<summary>` block
7. **Post-compact cleanup:**
   - Clear read-file state cache
   - Generate file attachments to restore recently-read files (up to 5, 50k tokens budget)
   - Re-inject skill attachments, plan attachments, deferred tool deltas, agent listings, MCP instructions
   - Run session-start hooks
8. **Create boundary marker** (`SystemCompactBoundaryMessage`) + summary user message (`isCompactSummary: true`)
9. **Resulting messages:** `[boundary, summary, messagesToKeep?, attachments, hookResults]`

### Summary Prompt Design (`services/compact/prompt.ts`)

The compact prompt is extremely detailed and structured:

```
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

[Detailed instructions to analyze chronologically]

Your summary should include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections (with full code snippets)
4. Errors and fixes
5. Problem Solving
6. All user messages (non-tool-result)
7. Pending Tasks
8. Current Work
9. Optional Next Step (with verbatim quotes)
```

The summary is formatted by stripping `<analysis>` tags and keeping `<summary>` content.

### Partial Compaction (`partialCompactConversation`)

- **`from` direction:** Summarize messages *after* the pivot; keep earlier messages. Preserves prompt cache for kept prefix.
- **`up_to` direction:** Summarize messages *before* the pivot; keep later messages. Invalidates cache prefix since summary precedes kept messages.

### Session Memory Compaction (`services/compact/sessionMemoryCompact.ts`)

An experimental optimization that **bypasses the summarization API call** entirely:

- Uses a pre-extracted **session memory file** (written continuously during the session) as the summary
- Calculates how many recent messages to keep based on:
  - `minTokens = 10_000`
  - `minTextBlockMessages = 5`
  - `maxTokens = 40_000`
- Adjusts the keep-index to preserve API invariants (no splitting tool_use/tool_result pairs or thinking blocks)
- Falls back to legacy compact if session memory is empty, missing, or would exceed the autocompact threshold

---

## Tool Result Storage

### Disk Persistence

Large tool results are saved to:
```
projectDir/sessionId/tool-results/{toolUseId}.{json|txt}
```

- **Skip if already exists** (idempotent, handles microcompact replays)
- **Preview generation:** First 2000 bytes, truncated at a newline boundary when possible
- **Wrapped in:** `<persisted-output>` tags with file path and preview

```ts
export const TOOL_RESULTS_SUBDIR = 'tool-results'
export const PREVIEW_SIZE_BYTES = 2000
export const PERSISTED_OUTPUT_TAG = '<persisted-output>'
```

### Content Replacement State

The state object that tracks budget decisions across turns:

```ts
export type ContentReplacementState = {
  seenIds: Set<string>        // tool_use_ids whose fate is decided
  replacements: Map<string, string>  // exact replacement string for re-apply
}
```

- **Fork sharing:** Subagents clone parent's state for cache-sharing forks (e.g., `agentSummary`)
- **Resume reconstruction:** On session resume, state is reconstructed from `ContentReplacementRecord[]` stored in the transcript
- **Inherited gap-fill:** For fork-subagent resumes, parent's live replacements fill gaps not covered by sidechain records

---

## Transcript Search (`utils/transcriptSearch.ts`)

Transcript search is **not a persistent index** — it is a runtime text extractor for the `/` search command.

### Key Design Decisions:

- **WeakMap cache:** `searchTextCache` maps `RenderableMessage → lowercase search text`. Messages are append-only/immutable so cache hits are always valid.
- **Lowercased at cache time:** Avoids re-lowercasing ~1.5MB on every keystroke (fixed a backspace hang).
- **Duck-types tool results:** Instead of indexing the model-facing `tool_result.content` (which contains system reminders, `<persisted-output>` wrappers, etc.), it extracts searchable text from the native tool output shape:
  - `Bash`: `{stdout, stderr}`
  - `Grep`: `{content, filenames}`
  - `Read`: `{file: {content}}`
- **Strips `<system-reminder>` tags:** These are Claude context, not user-visible.
- **Phantom avoidance:** Under-counting is preferred over phantom matches (e.g., `/malware` matching a security reminder).

### Searchable Text by Message Type:

| Message Type | Indexed Content |
|--------------|-----------------|
| `user` (string) | Raw text (unless interrupt sentinel) |
| `user` (blocks) | Text blocks + duck-typed tool result text |
| `assistant` | Text blocks + `toolUseSearchText` from `tool_use` inputs |
| `attachment` | `relevant_memories` content, queued commands |
| `collapsed_read_search` | Relevant memories |

---

## What Happens When the Context Window is Full?

The response depends on which layer triggers first:

1. **Normal operation:** Per-tool and per-message budgets keep individual turns manageable.
2. **Token threshold crossed:** Auto-compact proactively summarizes old messages before the API is called.
3. **API returns 413 (prompt too long):**
   - The error is **withheld** from the user during streaming.
   - First, **context collapse drain** is attempted (if enabled).
   - Then, **reactive compact** drops oldest API-round groups and re-summarizes.
   - If reactive compact succeeds, the query loop **restarts** with the compacted messages.
   - If all recovery fails, the error surfaces to the user.
4. **Hard blocking limit:** If auto-compact is disabled and the conversation exceeds `actualContextWindow - MANUAL_COMPACT_BUFFER_TOKENS`, the request is blocked with an error telling the user to compact manually.

---

## Different History Strategies for Different Modes

| Mode / Query Source | Strategy |
|---------------------|----------|
| `repl_main_thread` | Full pipeline: tool budget → snip → microcompact → collapse → autocompact → reactive |
| `agent:*` (subagents) | Tool budget applied, but cached-MC skipped (prevents cross-contamination of global state). Autocompact skipped for `compact` and `session_memory` sources (deadlock prevention). |
| `marble_origami` (ctx-agent) | Autocompact skipped to prevent destroying main thread's committed log. |
| Forked agents (`agentSummary`, `/btw`) | Content replacement state is cloned; ephemeral callers don't persist replacement records. |
| Resume | Replacement state reconstructed from transcript records; inherited replacements gap-filled from parent. |
| SDK / CCR / Eval | May hit reactive compact more often (single human turn, entire workload). Reactive compact uses API-round grouping instead of human-turn grouping. |

---

## Key Code Snippets

### Prompt History Reader (newest-first, bounded)
```ts
// history.ts
const MAX_HISTORY_ITEMS = 100

export async function* getHistory(): AsyncGenerator<HistoryEntry> {
  const otherSessionEntries: LogEntry[] = []
  let yielded = 0

  for await (const entry of makeLogEntryReader()) {
    if (entry.project !== currentProject) continue
    if (entry.sessionId === currentSession) {
      yield await logEntryToHistoryEntry(entry)
      yielded++
    } else {
      otherSessionEntries.push(entry)
    }
    if (yielded + otherSessionEntries.length >= MAX_HISTORY_ITEMS) break
  }
  // ...yield other sessions
}
```

### Per-Message Budget Enforcement
```ts
// utils/toolResultStorage.ts
export async function enforceToolResultBudget(
  messages: Message[],
  state: ContentReplacementState,
): Promise<{ messages: Message[]; newlyReplaced: ToolResultReplacementRecord[] }> {
  const candidatesByMessage = collectCandidatesByMessage(messages)
  const limit = getPerMessageBudgetLimit() // 200K default

  for (const candidates of candidatesByMessage) {
    const { mustReapply, frozen, fresh } = partitionByPriorDecision(candidates, state)
    // Re-apply cached replacements (byte-identical, zero I/O)
    mustReapply.forEach(c => replacementMap.set(c.toolUseId, c.replacement))
    // Select largest fresh results to replace until under budget
    const selected = frozenSize + freshSize > limit
      ? selectFreshToReplace(eligible, frozenSize, limit)
      : []
    // ...persist and replace
  }
}
```

### Auto-Compact Threshold
```ts
// services/compact/autoCompact.ts
export function getAutoCompactThreshold(model: string): number {
  const effectiveContextWindow = getEffectiveContextWindowSize(model)
  return effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS // 13K buffer
}
```

### PTL Retry Head Truncation
```ts
// services/compact/compact.ts
export function truncateHeadForPTLRetry(
  messages: Message[],
  ptlResponse: AssistantMessage,
): Message[] | null {
  const groups = groupMessagesByApiRound(input)
  const tokenGap = getPromptTooLongTokenGap(ptlResponse)
  // Drop oldest groups until token gap is covered
  let dropCount = tokenGap !== undefined
    ? /* accumulate tokens */
    : Math.max(1, Math.floor(groups.length * 0.2))
  dropCount = Math.min(dropCount, groups.length - 1)
  return groups.slice(dropCount).flat()
}
```

### Time-Based Microcompact
```ts
// services/compact/microCompact.ts
function maybeTimeBasedMicrocompact(messages, querySource) {
  const trigger = evaluateTimeBasedTrigger(messages, querySource)
  if (!trigger) return null
  const { gapMinutes, config } = trigger
  const keepRecent = Math.max(1, config.keepRecent)
  const keepSet = new Set(compactableIds.slice(-keepRecent))
  // Replace cleared results with placeholder
  return messages.map(message => {
    // ... replace tool_result.content with TIME_BASED_MC_CLEARED_MESSAGE
  })
}
```

---

## Insights for PersonAgent

### What to Adopt

1. **Multi-layered cascading strategy:** Don't jump straight to summarization. Apply cheaper, less-lossy layers first (per-result limits, aggregate budgets, time-based clearing) before invoking expensive summarization.

2. **Prompt cache stability is paramount:** Once a prefix is sent to the model, never change it. Track "seen" IDs and freeze their fate. Re-apply replacements byte-identically. This is the core insight that makes Claude Code's compaction cheap.

3. **Disk persistence for large results:** Instead of truncating tool results in-place, persist them to disk and send a preview with the file path. This preserves the information for the model to read back if needed (via `Read`), while saving context tokens.

4. **Duck-typed search indexing:** Don't index raw model-facing content (which contains system reminders, wrappers, etc.). Extract searchable text from the native tool output shapes. Prefer under-counting over phantom matches.

5. **Detailed summarization prompt:** The compact prompt is not "summarize this" — it has 9 explicit sections, demands full code snippets, verbatim user quotes, and an analysis scratchpad. The quality of the summary determines whether the model can continue working effectively.

6. **Separate prompt history from conversation history:** The user's Up-arrow history (`history.ts`) is a completely separate concern from the LLM's message array. Don't conflate them.

### What to Adapt

1. **Simpler environment:** PersonAgent may not need cache-editing APIs (cached microcompact) or complex forked-agent summarization if it's running with smaller context windows or simpler toolsets.

2. **No Bedrock/1P API duality:** Claude Code has extra complexity for merging consecutive user messages (Bedrock compatibility). If PersonAgent targets a single API, this can be simplified.

3. **Reactive vs proactive:** For a smaller project, proactive auto-compact may be sufficient; reactive compact (handling 413 errors) may be overkill unless you're running very close to context limits.

4. **Session memory compaction:** The idea of continuously extracting a "session memory" file and using it as a pre-computed summary is elegant and avoids an extra API call. Worth adopting if PersonAgent has a background memory extraction process.
