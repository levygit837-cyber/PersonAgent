# Findings: Root Cause of Token Burn

**Date:** 2026-05-30  
**Method:** Deep code analysis + token trace harness  
**Scope:** PersonAgent benchmark harness, production backend, and agent framework

---

## 1. The Core Mechanism: Full History Resend

Every API call sends the **entire conversation history**. The LLM has no memory between calls — each request is stateless.

```
Turn 1: System prompt (3K) + user message
Turn 2: System prompt (3K) + turn 1 + tool results = 15K
Turn 3: System prompt (3K) + turn 1 + 2 + more results = 35K
Turn 10: Everything from turns 1-9 = ~300K
Turn 20: Everything from turns 1-19 = ~800K
```

**The cost grows quadratically.** After 20 turns you have sent ~5M tokens total, even though each "new" turn was only 10-50K tokens.

### Why This Happens

The OpenAI/Anthropic API requires the full `messages` array on every call:
- System prompt (~3K tokens) — repeated every time
- All user messages
- All assistant responses
- All tool results
- Tool definitions (~5K-20K tokens)

There is no "continue from turn 15." The API sees the conversation as one big array.

---

## 2. What the Trace Harness Revealed

We built a token trace harness that logs real API usage per turn.

### Simple Task (6 turns, small files)

```
Total prompt tokens:  27,190
Max context size:      5,432
```

Small, manageable. Tool results were capped (30 lines per read, 30 files per glob).

### Intensive Task (8 turns, uncapped tool results)

```
Total prompt tokens: 502,575  ← HALF A MILLION
Max context size:     79,590
```

**The trigger:** Turn 1 did a `Grep("token", max_results=50)` that returned **203,355 characters** (50,838 tokens). This single result caused the context to jump from 3,559 tokens to **64,846 tokens** on Turn 2.

Then that 64K context was **resent on every subsequent turn**:

| Turn | Prompt Tokens | Growth | What Happened |
|------|--------------|--------|---------------|
| 1 | 3,559 | — | Initial query |
| 2 | 64,846 | +61,287 | Grep returned 203K chars |
| 3 | 66,116 | +1,270 | Resending the 203K result |
| 4 | 67,973 | +1,857 | Resending the 203K result |
| 5 | 70,657 | +2,684 | More file reads |
| 6 | 72,210 | +1,553 | Resending everything |
| 7 | 77,624 | +5,414 | More reads |
| 8 | 79,590 | +1,966 | Final response |

**Key insight:** The 203K grep result was added to history on Turn 1 and **resent unchanged** on Turns 2-8. The model paid for it 8 times even though it only needed it once.

### What This Means

After 8 turns with large tool results: **502K prompt tokens spent.**

If this agent continued for 20 turns: **~1.5M+ prompt tokens.**

If 4 agents ran in parallel: **~6M prompt tokens.**

---

## 3. The Memory System Is NOT the Culprit

We investigated whether PersonAgent's memory system contributes to token bloat.

**Operational memory** (execution history recall):
- Max capture: 24,000 chars per event
- Recall budget: `min(2,400, context_window × 0.015)`
- Max items: 6 (`recall_top_k = 6`)
- **Max injected per turn: ~2,400 tokens**

**Classic memory** (file-backed MEMORY.md):
- `memory_recall_max_tokens = 256`
- `memory_max_bytes_per_file = 25,000`
- **Max injected per turn: ~256 tokens**

**Session memory**:
- Generated with `max_tokens = 2,048`
- **Max injected per turn: ~2,048 tokens**

**Total memory per turn: ~4,700 tokens max.**

This is negligible compared to the 50K-200K from conversation history + tool results.

> **Note:** The benchmark harness does not even use the memory system. It is a standalone script.

---

## 4. Agent Framework Token Burn (The "3M" Problem)

When we dispatched 4 background agents to analyze Claude Code's codebase, each agent's conversation grew unchecked:

| Agent | Task | Estimated Tokens |
|-------|------|------------------|
| Token management | Read tokens.ts, tokenEstimation.ts | ~600K |
| History truncation | Read truncate.ts, history.ts | ~700K |
| Context analysis | Read analyzeContext.ts, query.ts | ~800K |
| Main orchestration | Read query.ts, QueryEngine.ts | ~900K |

**Why:**
1. **No token budgets** — agents have no spending limit
2. **No shared cache** — 4 agents independently read the same files
3. **Full history every turn** — no compaction in the agent framework
4. **Read entire files** — never use offset/limit
5. **No stuck detection** — agents loop on Grep/Read without progress tracking

The agent framework has **zero token awareness**.

---

## 5. What Already Exists in PersonAgent

PersonAgent's backend (`@backend/`) already has:

- **`ConversationCompactor`** — keeps last 8 messages, summarizes older ones
- **`MessagePreparer`** — checks token budget before each turn
- **Token counting** — `tiktoken` with `chars/4` fallback

**But it's missing:**
- Tool result budget management (no per-tool limits)
- Micro-compaction (no old tool result clearing)
- Reactive compact (no API 413 handling)
- Post-compact recovery (no file restoration)
- Circuit breaker (no failure limit)
- API-anchored token counting (only rough estimation)

The benchmark harness bypasses all of this.

---

## 6. The Fix Is Simple

Before every API call, check if context is too large. If yes, replace old messages with a summary:

```python
# Before EVERY API call
if estimate_tokens(messages) > THRESHOLD:
    summary = await generate_summary(old_messages)
    messages = [system_prompt, summary, *recent_messages]
```

This single check would have prevented the 502K token burn in the intensive trace.

**Two things are needed:**
1. **Cap tool results** before they enter history (prevention)
2. **Compact history** when it grows too large (cure)

---

## Key Files

- Trace harness: `benchmarks/exploration-harness/token_trace_harness.py`
- Production compactor: `@backend/src/personagent/application/use_cases/chat/lifecycle/compaction.py`
- Message preparer: `@backend/src/personagent/application/use_cases/chat/messaging/message_preparation.py`
- Token counting: `@backend/src/personagent/domain/token_counting.py`
