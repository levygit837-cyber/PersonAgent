# Layer 1: Tool Result Budget

## What It Is

The first and cheapest line of defense against context bloat. Before any compaction or summarization happens, Claude Code caps the size of individual tool results and the aggregate size of all tool results within a single user message.

## Why It Matters

Tool results are the #1 source of token growth in agentic conversations. A single `Read` of a large file or a `shell` command with verbose output can inject 50K+ tokens into the context. Without limits, one tool call can push the entire conversation over the context window.

## How It Works

### Per-Tool Result Limit: 50,000 characters

When a tool returns more than 50K characters:
1. The full result is written to disk in a spill file
2. The in-context result is replaced with a **preview** (first ~500 chars + "... truncated")
3. A reference to the spill file is stored in `contentReplacementState`

### Per-Message Aggregate Budget: 200,000 characters

When the SUM of all tool results within a single user message exceeds 200K characters:
1. Identify the largest "fresh" (not yet persisted) tool results
2. Replace them with previews, starting from the largest
3. Continue until the aggregate is under 200K or all fresh results are replaced

### Which Tools Are Capped?

All tools are subject to the per-tool limit. The aggregate budget applies to tool results within a single user message block.

## Code Location

- `utils/toolResultStorage.ts` — spill logic, preview generation
- `query.ts:376-394` — `applyToolResultBudget()` call site

## Key Insight

This layer is **purely mechanical** — no LLM calls, no summarization. It just truncates and spills. This makes it extremely cheap and reliable. The trade-off is information loss: the model no longer has the full tool result in context, only a preview.

## Recovery Strategy

When the model needs the full content again:
1. The tool result reference is still in the conversation
2. The spill file path is tracked in `contentReplacementState`
3. If the model re-reads the same file, the tool gets a cache hit (or re-executes)

## Example Flow

```
Turn 1: Read large_file.py → 80K chars
        → Spill to disk, replace with 500-char preview
Turn 2: Grep pattern → 10K chars
        → Under limit, keep full result
Turn 3: shell ls -R → 120K chars
        → Under per-tool limit, but message aggregate = 130K
        → Keep full result
Turn 4: Read another_large_file.py → 90K chars
        → Spill to disk, replace with preview
        → Message aggregate would be 220K > 200K
        → Also replace Turn 3's shell result with preview
```


## When This Layer Fires

- **Every turn**, before microcompact, before autocompact
- Even on short conversations where compaction wouldn't trigger yet
- As a preventive measure, not a reactive one
