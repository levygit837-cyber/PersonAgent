# Layer 6: Reactive Compact

## What It Is

Reactive compact is the **emergency fallback** that fires when the API rejects a request with "prompt too long" (HTTP 413). Unlike auto-compact (which is proactive), reactive compact is **reactive** — it only runs after the API has already refused the request.

## Why It Matters

Even with proactive auto-compact, edge cases can slip through:
- The token estimate is off (rare but possible)
- A single message is larger than expected
- The model's context window is smaller than configured
- A provider-specific limit is hit

Reactive compact is the last line of defense before the user sees an error.

## How It Works

### Trigger

The API returns an error indicating the prompt is too long. Claude Code recognizes these error patterns:
- Anthropic: `prompt_too_long`
- Bedrock/Vertex: Various error formats
- Custom error prefix matching

### Recovery Strategy

```
1. Catch API 413 error
2. Parse the error to determine "token gap" (how many tokens over limit)
3. If gap is parseable:
   a. Group messages by API round
   b. Drop oldest groups until gap is covered
   c. Retry the API call with truncated messages
4. If gap is unparseable:
   a. Drop 20% of oldest groups
   b. Retry
5. Repeat up to MAX_PTL_RETRIES (3 times)
6. If all retries fail, show user error message
```

### Truncation Logic

The `truncateHeadForPTLRetry()` function:
1. Groups messages by API round (same `message.id` = same round)
2. Calculates how many groups to drop:
   - If token gap is known: drop groups until `roughTokenCountEstimation >= gap`
   - If gap unknown: drop `max(1, floor(groups.length * 0.2))`
3. Ensures at least one group remains (can't drop everything)
4. If the first remaining message is assistant (API requires user first):
   - Prepends a synthetic user marker: `[earlier conversation truncated for compaction retry]`

### Synthetic Marker

```
[earlier conversation truncated for compaction retry]
```

This marker:
- Satisfies the API's "first message must be user" requirement
- Tells the model that context was lost
- Is stripped on subsequent processing to avoid accumulation

### Media Recovery

If the original request withheld media (images/documents) due to PTL risk, reactive compact restores them after successful truncation and retry.

## Code Location

- `services/compact/compact.ts:243-291` — `truncateHeadForPTLRetry()`
- `services/compact/compact.ts:450-491` — PTL retry loop in `compactConversation()`
- `query.ts` — error catching and reactive compact integration

## Key Insight

Reactive compact is **lossy and emergency-only**. It doesn't generate a summary — it just deletes old messages. The model loses all context from those deleted messages. But it's better than failing completely.

The design philosophy is: **"When all else fails, sacrifice old context to keep the conversation alive."**


## When This Layer Fires

- **Only when the API rejects a request** with prompt-too-long
- After auto-compact has already run (or failed)
- Before showing the user an error
- Up to 3 retries per rejection

## Design Philosophy

Reactive compact embodies: **"Never give up on the user."** Even when everything else has failed — estimation was wrong, proactive compact didn't fire, the context grew unexpectedly — the system makes a best-effort attempt to recover by sacrificing the oldest, least-relevant context.

## Example Flow

```
Turn 50: Conversation at 175K tokens
         Auto-compact threshold: 167K
         But auto-compact was DISABLED by user
         
         API call with 175K tokens
         → HTTP 413: prompt_too_long
         
         Token gap: 15K tokens
         
         Reactive compact:
           - Group into 50 API rounds
           - Drop rounds 1-3 (~18K tokens)
           - Retry with 157K tokens
           → Success!
           
         User sees: normal response (no error)
```
