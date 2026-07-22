# Layer 3: History Snip

## What It Is

History snip drops the **oldest messages** from the conversation tail entirely. Unlike microcompact (which clears content but keeps structure) or autocompact (which summarizes), snip is pure deletion — old messages are removed with no replacement.

## Why It Matters

Sometimes the conversation has grown so large that even summarizing it would exceed the summarizer's context window. Snip provides a fast, lossy way to reclaim tokens by simply discarding the oldest context. It also helps when the oldest messages are no longer relevant (e.g., the user changed topics 50 turns ago).

## How It Works

### Trigger

Snip is gated behind a feature flag (`HISTORY_SNIP`). When enabled, it runs **before** microcompact and autocompact on every turn.

### Algorithm

1. Group messages by API round (using `groupMessagesByApiRound`)
2. Calculate how many tokens would be freed by dropping the oldest N groups
3. If the conversation exceeds the snip threshold, drop enough oldest groups to get under threshold
4. Insert a **boundary message** indicating that history was snipped
5. Report `tokensFreed` to autocompact so the threshold check reflects the reduction

### Boundary Message

When snip removes messages, a synthetic user message is inserted:
```
[earlier conversation truncated for length]
```

This tells the model that context is missing and prevents it from referencing older messages.

### Grouping by API Round

Messages are grouped at API-round boundaries — when a new assistant response begins (different `message.id` from the prior assistant). This ensures that:
- Tool_use/tool_result pairs stay together
- Streaming chunks from the same response stay together
- Each group is a complete turn

## Code Location

- `services/compact/snipCompact.ts` — snip implementation
- `services/compact/grouping.ts` — API-round grouping logic

## Key Insight

Snip is **the most aggressive and lossiest** layer. It deletes messages permanently with no summary. The trade-off is maximum token recovery with zero computational cost (no LLM call). It's designed as a "pressure relief valve" when gentler methods aren't enough.

## Token Recovery

Typical recovery: 30-80% of conversation tokens, depending on how many groups are dropped.

## Example Flow

```
Conversation (20 API rounds, ~150K tokens):
  Round 1-5:  Initial exploration (40K tokens)
  Round 6-10: File reads and edits (50K tokens)
  Round 11-15: Debugging attempts (35K tokens)
  Round 16-20: Current work (25K tokens)

Snip threshold: 100K tokens
Action: Drop rounds 1-5 (40K tokens freed)
Result: Still over threshold? Drop rounds 6-8 (30K more freed)

New conversation (~80K tokens):
  [user] [earlier conversation truncated for length]
  Round 9-10: File reads and edits
  Round 11-15: Debugging attempts
  Round 16-20: Current work
```


## When This Layer Fires

- **Every turn** (when feature flag is on), before microcompact and autocompact
- Only when conversation exceeds snip threshold
- Can fire multiple times per session
- Not used as a primary strategy — more of a fallback

## Design Philosophy

Snip embodies the principle: **"Old context is less valuable than recent context."** When forced to choose between keeping a detailed summary of everything vs. keeping full fidelity of recent work, snip chooses recent work. This matches how humans work — we remember what we did this morning better than what we did three weeks ago.
