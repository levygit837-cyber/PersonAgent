# Layer 2: Microcompact

## What It Is

Microcompact selectively clears the **content** of old tool results while keeping the tool result structure intact. Instead of summarizing the entire conversation, it surgically removes bulky tool outputs that are no longer needed.

## Why It Matters

Tool results accumulate linearly. After 20 turns with file reads, grep results, and shell outputs, the conversation can be 90% tool results and 10% actual dialogue. Microcompact addresses this by recognizing that **old tool results are rarely referenced** by the model on subsequent turns.

## How It Works

There are two distinct paths:

### Path A: Time-Based Microcompact

**Trigger:** Time gap since last assistant message exceeds threshold (configurable, default ~5-30 minutes).

**Logic:**
1. Collect all compactable tool IDs (tools in the `COMPACTABLE_TOOLS` set)
2. Keep the most recent N tool results (configurable, default ~3-5)
3. Replace the **content** of all older tool results with the marker: `[Old tool result content cleared]`
4. Reset cached microcompact state (since cache is now cold)

**Why time-based?** If the user stepped away, the server-side prompt cache has likely expired. The full prefix will be rewritten anyway, so clearing old tool results now is "free" — no cache invalidation penalty.

### Path B: Cached Microcompact (API-Level)

**Trigger:** Number of compactable tool results exceeds a threshold (count-based, from GrowthBook config).

**Logic:**
1. Track all tool results by `tool_use_id` in module-level state
2. When count exceeds threshold, identify which tool results to delete
3. Instead of modifying local messages, generate a `cache_edits` block
4. The `cache_edits` block is sent to the Anthropic API, which removes those tool results from the cached prefix **without invalidating the cache**
5. Pin the edit block to a specific user message position for subsequent turns

**Why cache-editing?** This is an Anthropic API feature that allows removing content from a cached prompt prefix. The cache key stays the same, so subsequent requests get a cache hit on the prefix and only pay for the modified portion.

### Compactable Tools

Only these tools are eligible for microcompact:
- `file_read`
- `shell` (all variants)
- `grep`
- `glob`
- `web_search`
- `web_fetch`
- `file_edit`
- `file_write`

Tools like `ask_user`, `plan`, `skill_search` are **never** microcompacted because their results are semantically important.

## Code Location

- `services/compact/microCompact.ts` — main logic
- `services/compact/cachedMicrocompact.ts` — cache-editing variant
- `services/compact/timeBasedMCConfig.ts` — time-based configuration

## Key Insight

Microcompact is **surgical** — it only touches tool results, not user messages or assistant reasoning. This preserves the conversation flow while eliminating the bulk of token growth. The `[Old tool result content cleared]` marker tells the model "there was a tool result here, but the content is gone," which is enough for it to understand the conversation structure.

## Token Savings

Typical savings: 20-60% of conversation tokens, depending on tool usage intensity.

## Example Flow

```
Conversation:
  [assistant] Read file A
  [user]    file A content (15K tokens)
  [assistant] Read file B
  [user]    file B content (20K tokens)
  [assistant] Grep pattern
  [user]    grep results (8K tokens)
  [assistant] Read file C
  [user]    file C content (25K tokens)

Time-based microcompact fires (user was away 10 min):
  [assistant] Read file A
  [user]    [Old tool result content cleared]
  [assistant] Read file B
  [user]    [Old tool result content cleared]
  [assistant] Grep pattern
  [user]    [Old tool result content cleared]
  [assistant] Read file C
  [user]    file C content (25K tokens)  ← kept

Tokens: 68K → 25K (63% reduction)
```


## When This Layer Fires

- **Every turn**, before autocompact
- Time-based: when user returns after a gap
- Cached: when tool result count exceeds threshold
- Does NOT fire for forked agents (sub-agents inherit main thread state)
