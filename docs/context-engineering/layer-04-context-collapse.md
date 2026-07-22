# Layer 4: Context Collapse

## What It Is

Context collapse is an experimental system that **archives old message groups into a separate collapse store** rather than modifying the conversation itself. The REPL keeps the full conversation history, but the API sees only a "projected view" where old groups are replaced with summaries.

## Why It Matters

Traditional compaction modifies the conversation in-place: old messages are deleted and replaced with a summary. This is **destructive** — you can't get the original messages back without undo. Context collapse is **non-destructive** — the full history is preserved in the collapse store, and the API sees a "view" that can be recomputed at any time.

This enables:
- **Selective expansion** (planned): The user (via UI) or model (via explicit tool) can ask to "expand" a collapsed section. Note: in the current Claude Code analysis, there is no built-in mechanism for the LLM to automatically expand a collapsed section during inference — this requires an explicit tool call or user action.
- **Accurate transcripts**: The full conversation is preserved for logging/replay
- **Reversible operations**: Collapses can be undone or recomputed from the Collapse Store. However, the LLM itself only sees the projected view and cannot "unfold" collapsed content without an external mechanism.

## How It Works

### Core Concepts

1. **Collapse Store**: A separate data structure (not the REPL messages array) that holds:
   - The original message groups
   - Summary messages for each collapsed group
   - A commit log of all collapse operations

2. **Projected View**: A function `projectView(messages, collapseStore)` that:
   - Replays the commit log on the input messages
   - Returns the API-safe message list with collapsed sections replaced by summaries
   - Runs on **every turn**, so the view is always fresh

3. **Commit Log**: Append-only log of collapse operations. Each commit:
   - Targets a specific message range
   - Stores the summary that replaces that range
   - Is immutable once written

### Collapse Lifecycle

```
Turn N:
  1. Receive full messages from REPL
  2. projectView() replays commit log → collapses old ranges
  3. Check if new collapses are needed (token threshold)
  4. If needed, fork agent to summarize the target range
  5. Append new collapse to commit log
  6. Return projected messages for API call

Turn N+1:
  1. Receive full messages from REPL (still has original messages!)
  2. projectView() replays ALL commits (old + new)
  3. Return projected messages for API call
```

### Commit Thresholds

- **Commit start**: 90% of effective context window
- **Blocking spawn**: 95% of effective context window
- When blocking spawn hits, the system **must** create a collapse before the next API call

### Recovery from Overflow

If the API returns 413 (prompt-too-long) despite collapses:
1. `recoverFromOverflow()` drains all **staged** collapses (commits not yet applied)
2. Falls through to reactive compact as final fallback

## Code Location

- `services/contextCollapse/index.ts` — main module (experimental)
- Referenced in `query.ts:440-447` — integration point
- `autoCompact.ts:215-223` — suppression logic (autocompact doesn't fire when collapse is active)

## Key Insight

Context collapse treats the conversation as a **database with views**. The raw data (full messages) is never modified. The API sees a "materialized view" that is computed on-demand. This is a fundamentally different architecture from in-place compaction.

## Comparison with Traditional Compaction

| Aspect | Traditional Compaction | Context Collapse |
|--------|------------------------|------------------|
| Mutates conversation | ✅ Yes (destructive) | ❌ No (preserves full) |
| Reversible | ❌ No | ✅ Yes |
| User can expand | ❌ No | ✅ Yes (planned) |
| Transcript accuracy | ❌ Lost detail | ✅ Full history |
| Implementation complexity | Lower | Higher |
| API call cost | One-time | Every turn (view projection) |


## When This Layer Fires

- **Experimental feature** — gated behind `CONTEXT_COLLAPSE` feature flag
- When enabled, suppresses autocompact (collapse owns context management)
- Runs on every turn via `projectView()`
- Creates new collapses at 90% threshold
- Blocking spawn at 95%

## Design Philosophy

Context collapse embodies: **"Preserve everything, show only what's needed."** It separates storage from presentation, allowing the system to keep a complete record while managing API costs. This is the most "correct" architecture but also the most complex.
