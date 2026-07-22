# Layer 7: Session Memory Compact

## What It Is

Session memory compact is an **optimization** that bypasses the expensive LLM summarization call entirely. Instead of asking a model to generate a summary, it uses a **pre-extracted session memory file** as the continuity context.

## Why It Matters

Auto-compact requires a full LLM call to generate the summary. For a 170K-token conversation, this costs ~170K input tokens + ~8K output tokens = **178K tokens**. On expensive models, this is significant. Session memory compact reduces this to **zero** — the summary already exists.

## How It Works

### Session Memory Extraction

A background process continuously extracts key information from the conversation:
- User preferences and instructions
- Important files and code patterns
- Errors and how they were fixed
- Decisions made
- Pending tasks

This is written to a `session_memory.md` file in the project directory.

### Compact Process

```
1. Check if session memory compaction is enabled
2. Wait for any in-progress session memory extraction
3. Get the session memory content
4. Check if session memory is empty (just template, no real content)
5. Find lastSummarizedMessageId (the boundary between summarized and unsummarized)
6. Calculate messages to keep:
   - Start from lastSummarizedIndex
   - Expand backwards to meet minimums:
     * At least 10K tokens
     * At least 5 messages with text blocks
     * Hard cap at 40K tokens
   - Adjust to not split tool_use/tool_result pairs
7. Filter out old compact boundary messages
8. Run session start hooks
9. Create compaction result from session memory
10. Check if post-compact token count is still above threshold
    - If yes, fall back to traditional compaction
    - If no, return session memory result
```

### Messages to Keep Calculation

The `calculateMessagesToKeepIndex()` function ensures:
- Minimum token preservation: 10K tokens
- Minimum text-block messages: 5
- Maximum token cap: 40K tokens
- Tool pair invariant: never orphan a tool_result
- Boundary floor: don't go below last compact boundary

### Fallback

If session memory compact would result in a context still above the auto-compact threshold, it **falls back to traditional compaction**:
```
postCompactTokenCount >= autoCompactThreshold
→ "Session memory too large, falling back to full compact"
```

## Code Location

- `services/compact/sessionMemoryCompact.ts` — main implementation
- `services/SessionMemory/` — session memory extraction (background process)
- `utils/sessionStart.ts` — session start hooks

## Key Insight

Session memory compact is **only possible because Claude Code has a background memory extraction system**. This system runs continuously, not just at compact time. Without that infrastructure, session memory compact can't work.

The trade-off is that session memory is **less detailed** than a freshly generated summary. It's optimized for "what does the model need to know to continue?" not "what happened in every turn?"

## Comparison with Traditional Compaction

| Aspect | Traditional Compact | Session Memory Compact |
|--------|---------------------|------------------------|
| LLM call required | ✅ Yes (~178K tokens) | ❌ No (zero cost) |
| Summary detail | High (9-section structured) | Medium (pre-extracted) |
| Freshness | Generated at compact time | Continuously updated |
| Messages to keep | Last 8 + preserved | Configurable (10K-40K) |
| Fallback available | N/A | ✅ Yes (to traditional) |
| Background process | No | ✅ Yes (memory extraction) |


## When This Layer Fires

- **Before traditional auto-compact** (cheaper path attempted first)
- Only when session memory feature flags are enabled
- Only when session memory file has real content
- Only when the resulting context would be under the threshold

## Design Philosophy

Session memory compact embodies: **"Invest in background work to save foreground costs."** By continuously extracting session memory in the background, the system avoids an expensive LLM call at compact time. This is a classic time-vs-space trade-off: background CPU time is spent to save API tokens later.

## Prerequisites

For this layer to work, the system needs:
1. **Session memory extractor** — background process that reads conversation and writes `session_memory.md`
2. **Message ID tracking** — `lastSummarizedMessageId` to know the boundary
3. **Session start hooks** — to re-inject CLAUDE.md and other context
4. **Feature flags** — to enable/disable the experiment

Without these prerequisites, the system falls back to traditional auto-compact seamlessly.
