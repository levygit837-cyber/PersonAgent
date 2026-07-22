# Claude Code Context Management Reference

Claude Code uses a **7-layer escalating cascade** for context management. Each layer attacks a different aspect of the same problem: the full history resend.

## The 7 Layers at a Glance

| Layer | What It Does | Cost | Savings |
|-------|-------------|------|---------|
| 1. Tool Result Budget | Caps individual tool outputs at 50K chars | Zero | Prevents injection |
| 2. Microcompact | Clears old tool result content | Zero | 20-60% |
| 3. History Snip | Drops oldest messages entirely | Zero | 30-80% |
| 4. Context Collapse | Archives old groups to separate store | Medium | Non-destructive |
| 5. Auto-Compact | Summarizes old messages via LLM | High (~170K tokens) | Major reduction |
| 6. Reactive Compact | Truncates on API 413 error | Zero (emergency) | Last resort |
| 7. Session Memory | Uses pre-extracted summary file | Zero | Bypasses LLM call |

## Thresholds

```
Context Window: 200K (up to 1M for newer models)
Output Reserve: min(model_max_output, 20K)
Effective Window: context_window - output_reserve

Auto-Compact Trigger: effective_window - 13,000  (~93%)
Warning Threshold: auto_compact - 20,000
Blocking Limit: effective_window - 3,000  (~98.5%)
```

## Layer 1: Tool Result Budget

**What:** Caps tool outputs before they enter the conversation.

- Per-tool limit: 50,000 characters → spill to disk, replace with preview
- Per-message aggregate: 200,000 characters → replace largest results

**Why first:** This is purely mechanical — no LLM calls, no summarization. It prevents the problem before it starts.

**Code:** `utils/toolResultStorage.ts`, `query.ts:376-394`

## Layer 2: Microcompact

**What:** Surgically clears content from old tool results while keeping structure.

Two paths:
- **Time-based:** If gap since last assistant > threshold, clear old results (keep last N)
- **Cached:** Uses Anthropic's cache-editing API to remove results without invalidating cache

**Compactable tools:** `file_read`, `shell`, `grep`, `glob`, `web_search`, `web_fetch`, `file_edit`, `file_write`

**Marker:** `[Old tool result content cleared]`

**Code:** `services/compact/microCompact.ts`

## Layer 3: History Snip

**What:** Drops oldest API-round groups from the tail. Pure deletion, no summary.

**When:** Before microcompact and autocompact. Lossy but free.

**Boundary marker:** `[earlier conversation truncated for length]`

**Code:** `services/compact/snipCompact.ts`

## Layer 4: Context Collapse

**What:** Non-destructive archive system. Full history is preserved in a collapse store; the API sees a computed "view."

**How:**
1. Commit log (append-only) records collapsed ranges
2. `projectView()` replays commits on every turn
3. Summary messages live in the collapse store, not the REPL array


1. Collapse Store (separate from the conversation):
    • Stores original message groups
    • Stores summary messages for collapsed groups
    • Maintains a commit log of all collapse operations
  2. Projected View function:
    • Replays the commit log on the input messages
    • Returns the API-safe message list with collapsed sections replaced by summaries
    • Runs on every turn to keep the view fresh
  3. Commit Log (append-only):
    • Each commit targets a specific message range
    • Stores the summary that replaces that range
    • Is immutable once written


**Benefit:** Reversible, user can "expand" collapsed sections.

**Status:** Experimental, gated behind `CONTEXT_COLLAPSE` flag.

**Code:** `services/contextCollapse/index.ts`

## Layer 5: Auto-Compact

**What:** Primary proactive compaction. Replaces old messages with a structured summary.

**Trigger:** Token count > `effectiveContextWindow - 13,000`

**Pipeline:**
1. Execute pre-compact hooks
2. Strip images (replace with `[image]`)
3. Strip re-injected attachments
4. Fork agent with structured 9-section prompt
5. Handle PTL retry (if compact itself hits limit)
6. Clear file read cache
7. Restore up to 5 recently read files (50K budget, 5K per file)
8. Re-inject skills, plans, deferred tools
9. Execute session-start hooks
10. Create compact boundary marker

**Summary prompt structure:**
```
CRITICAL: Respond with TEXT ONLY.

Your summary must include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections (with FULL code snippets)
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Current Work
9. Optional Next Step
```

**Circuit breaker:** Max 3 consecutive failures.

**Code:** `services/compact/autoCompact.ts`, `services/compact/compact.ts`, `services/compact/prompt.ts`

## Layer 6: Reactive Compact

**What:** Emergency fallback when API returns "prompt too long" (HTTP 413).

**Process:**
1. Catch API 413 error
2. Parse token gap from error
3. Drop oldest API-round groups until gap is covered
4. Retry up to 3 times
5. If all fail, show user error

**Synthetic marker:** `[earlier conversation truncated for compaction retry]`

**Code:** `services/compact/compact.ts:243-291`

## Layer 7: Session Memory Compact

**What:** Bypasses the expensive LLM summarization call by using a pre-extracted session memory file.

**How:**
1. Background process continuously writes `session_memory.md`
2. At compact time, use the file as the summary instead of calling LLM
3. Keep recent messages (configurable: 10K-40K tokens)
4. Fallback to traditional compact if result still exceeds threshold

**Benefit:** Zero-cost compaction (no LLM call).

**Prerequisites:** Session memory extractor, message ID tracking, session start hooks.

**Code:** `services/compact/sessionMemoryCompact.ts`

## Token Counting Strategy

Claude Code uses **three-tier token counting:**

1. **Exact API counts** — Anchor to last API response's `usage` object
2. **Haiku fallback** — Use cheap model for counting when exact unavailable
3. **Rough estimation** — `content.length / 4` (or `/ 2` for JSON), images = 2000

```typescript
function tokenCountWithEstimation(messages): number {
  // Walk back from last message to find last API usage record
  // Add rough estimates only for messages added since
  // Handle parallel tool calls by walking to FIRST sibling
}
```

**Code:** `utils/tokens.ts`, `services/tokenEstimation.ts`

## Comparison with PersonAgent

| Feature | Claude Code | PersonAgent |
|--------|-------------|-------------|
| Token counting from API usage | ✅ Anchored | ❌ Rough estimate only |
| Tool result budget (50K/200K) | ✅ Yes | ❌ No limit |
| Micro-compaction | ✅ Yes | ❌ No |
| History snip | ✅ Yes | ❌ No |
| Context collapse | ✅ Experimental | ❌ No |
| Auto-compact | ✅ 9-section summary | ✅ Basic summary |
| Reactive compact (API 413) | ✅ Yes | ❌ No |
| Post-compact file recovery | ✅ 5 files + skills | ❌ No |
| Circuit breaker | ✅ Max 3 failures | ❌ No |
| Session memory compact | ✅ Yes | ❌ No |
| Image stripping for compact | ✅ Yes | ❌ No |
| Tool result spill to disk | ✅ Yes | ❌ No |
