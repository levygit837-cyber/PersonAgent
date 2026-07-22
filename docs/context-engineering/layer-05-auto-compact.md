# Layer 5: Auto-Compact

## What It Is

Auto-compact is the **primary proactive compaction strategy**. When the conversation's token count exceeds a threshold (~93% of the effective context window), the system automatically generates a detailed summary of older messages and replaces them with that summary.

## Why It Matters

This is the main safety valve that prevents the conversation from hitting the hard context window limit. It's proactive (fires before the API rejects the request) and generates a **rich, structured summary** that preserves technical details, code snippets, and user intent.

## How It Works

### Trigger Conditions

```
autoCompactThreshold = effectiveContextWindow - 13,000 tokens

where:
  effectiveContextWindow = contextWindow - maxOutputTokens(reserve)
  maxOutputTokens(reserve) = min(modelMaxOutput, 20_000)
```

For a 200K context window model:
- Effective window: 200K - 20K = 180K
- Auto-compact trigger: 180K - 13K = **167K tokens**

### The Compaction Pipeline

```
1. shouldAutoCompact()
   └── Check token count against threshold
   └── Skip if: disabled, forked agent, reactive-only mode, context-collapse active

2. autoCompactIfNeeded()
   └── Circuit breaker check (max 3 consecutive failures)
   └── Try session memory compaction first (cheaper)
   └── Fall back to full compaction

3. compactConversation()
   a. Execute pre-compact hooks
   b. Build compact prompt (structured 9-section instructions)
   c. Strip images from messages (replace with [image])
   d. Strip re-injected attachments (skill_discovery, skill_listing)
   e. Stream summary from forked agent
   f. Handle PTL retry (if compact itself hits prompt-too-long)
   g. Clear file read cache
   h. Generate post-compact attachments:
      - Restore up to 5 recently read files (50K budget, 5K per file)
      - Re-inject skills, plans, deferred tools, agent listings, MCP instructions
   i. Execute session-start hooks
   j. Create compact boundary marker
   k. Return CompactionResult

4. Build post-compact messages
   [boundaryMarker, summaryMessages, messagesToKeep, attachments, hookResults]
```

### The Compact Prompt

The prompt given to the summarizing agent is highly structured:

```
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

Your task is to create a detailed summary of the conversation so far...

Before providing your final summary, wrap your analysis in <analysis> tags.

Your summary should include:
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections (with FULL code snippets)
4. Errors and fixes
5. Problem Solving
6. All user messages (non-tool results)
7. Pending Tasks
8. Current Work
9. Optional Next Step (with verbatim quotes)
```

### Post-Compact Recovery

After compaction, critical context is restored:

| Recovery Item | Budget |
|---------------|--------|
| Recently read files (up to 5) | 50K tokens total, 5K per file |
| Skills | 25K tokens total, 5K per skill |
| Plan mode instructions | As needed |
| Deferred tool schemas | Full set |
| Agent listings | Full set |
| MCP instructions | Full set |

### Boundary Marker

A system message marks the compact boundary:
```
[Compact boundary: auto | manual]
[Pre-compact token count: X]
[Last message UUID: ...]
```

This marker is used by the loader to understand the conversation structure and by telemetry to track compaction events.

### Circuit Breaker

If compaction fails 3 times in a row (e.g., context is irrecoverably over limit), auto-compact stops trying:
```
autocompact: circuit breaker tripped after 3 consecutive failures
             — skipping future attempts this session
```

Without this, doomed sessions would hammer the API with futile compaction attempts.

## Code Location

- `services/compact/autoCompact.ts` — threshold logic, circuit breaker
- `services/compact/compact.ts` — full compaction implementation
- `services/compact/prompt.ts` — compact prompts (BASE + PARTIAL variants)
- `services/compact/grouping.ts` — API-round grouping
- `query.ts:453-543` — integration into main query loop

## Key Insight

Auto-compact is **expensive** (requires a full LLM call to generate the summary) but **preserves rich context**. The 9-section prompt ensures that critical technical details — full code snippets, error messages, verbatim user quotes — survive compaction. This is why Claude Code can work on 500+ turn sessions without losing track of what it's doing.

## Token Flow Example

```
Pre-compact:  170K tokens (170 messages)
  ↓ compactConversation()
Summary call:  170K input + 8K output = 178K tokens spent
  ↓
Post-compact:  25K tokens (boundary + summary + 8 recent messages + attachments)
  ↓
Next 10 turns: 25K → 80K → 120K → 160K → trigger again
```


## When This Layer Fires

- **Every turn** (token count check is cheap)
- Only when `tokenCountWithEstimation(messages) > threshold`
- Not for forked agents (compact, session_memory query sources)
- Not when context-collapse is active
- Not when reactive-only mode is enabled

## Design Philosophy

Auto-compact embodies: **"Summarize with fidelity."** The goal is not just to reduce tokens but to create a summary so good that the model can continue working as if it had read the full conversation. This requires structured instructions, verbatim quotes, and full code snippets — not just a high-level overview.
