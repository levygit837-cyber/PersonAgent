# Context Engineering & Token Preservation

This directory contains the analysis, reference, and implementation plan for fixing PersonAgent's token burn problem.

## Documents

| File | Purpose | Read If You... |
|------|---------|----------------|
| [`01-findings.md`](01-findings.md) | **What we discovered** — root cause, trace data, and the real source of token burn | Want to understand the problem |
| [`02-claude-reference.md`](02-claude-reference.md) | **How Claude Code solves it** — all 7 layers in one reference doc | Want to learn from Claude's architecture |
| [`03-implementation-guide.md`](03-implementation-guide.md) | **What to build** — phased roadmap with code examples | Want to implement fixes |
| [`04-alternatives.md`](04-alternatives.md) | **Other approaches** — truncation, RAG, memory stores, etc. | Want to explore different strategies |
| [`05-benchmark-failures-and-stuckness.md`](05-benchmark-failures-and-stuckness.md) | **Why benchmarks fail** — agent stuckness, loop patterns, fixes | Want to understand the 4/6 failure rate |

## Quick Summary

**The Problem:** Every API call sends the full conversation history. After a large tool result (e.g., 203K char grep output), the context jumps from 3K to 65K tokens. That 65K context is then **resent on every subsequent turn**.

**The Evidence:**
- Simple task (6 turns): 27K total prompt tokens
- Intensive task (8 turns): **502K total prompt tokens** — max context 79K
- One grep result: 203K chars → 50K tokens injected in a single turn

**The Fix:** Cap tool results + compact conversation history before it explodes.

## Layer Documents (Detailed Reference)

For deep dives into individual Claude Code layers:

- [`layer-01-tool-result-budget.md`](layer-01-tool-result-budget.md) — Per-tool limits (50K chars)
- [`layer-02-microcompact.md`](layer-02-microcompact.md) — Clearing old tool results
- [`layer-03-history-snip.md`](layer-03-history-snip.md) — Dropping oldest messages
- [`layer-04-context-collapse.md`](layer-04-context-collapse.md) — Non-destructive archive
- [`layer-05-auto-compact.md`](layer-05-auto-compact.md) — Proactive summarization
- [`layer-06-reactive-compact.md`](layer-06-reactive-compact.md) — Emergency truncation on API 413
- [`layer-07-session-memory-compact.md`](layer-07-session-memory-compact.md) — Pre-extracted summary

These are reference-only. The consolidated learnings are in [`02-claude-reference.md`](02-claude-reference.md).
