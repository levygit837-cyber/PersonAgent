# Token Management in Claude Code

## Overview

Claude Code employs a **multi-layered token management architecture** that combines API-reported usage, client-side estimation, server-side task budgets, and aggressive context compaction. The system is designed to maximize conversation length while minimizing cost surprises and API errors. It distinguishes between:

1. **Context window size** — how many tokens fit in the model's input
2. **Output token budget** — how many tokens the model may generate per response
3. **User turn budget** — an opt-in auto-continue limit parsed from natural language (e.g. "+500k")
4. **API task budget** — a first-party-only server-side spend limit
5. **Cost tracking** — cumulative USD spend per session, persisted across resumes

---

## Token Counting Mechanism

### Primary Source: API Usage Objects

Claude Code treats the Anthropic API's `usage` object as the ground truth. Every assistant message carries:

```ts
// utils/tokens.ts
export function getTokenUsage(message: Message): Usage | undefined {
  if (message?.type === 'assistant' && 'usage' in message.message) {
    return message.message.usage
  }
  return undefined
}
```

The **canonical context size** function `tokenCountWithEstimation()` anchors to the **last real API response** and adds rough estimates for any messages added since:

```ts
// utils/tokens.ts
export function tokenCountWithEstimation(messages: readonly Message[]): number {
  let i = messages.length - 1
  while (i >= 0) {
    const message = messages[i]
    const usage = message ? getTokenUsage(message) : undefined
    if (message && usage) {
      // Walk back past split sibling records from parallel tool calls
      // so interleaved tool_results are included in the estimate.
      const responseId = getAssistantMessageId(message)
      if (responseId) { /* ...walk back... */ }
      return getTokenCountFromUsage(usage) +
             roughTokenCountEstimationForMessages(messages.slice(i + 1))
    }
    i--
  }
  return roughTokenCountEstimationForMessages(messages)
}
```

This avoids the **double-counting trap** of summing cumulative tokens across a growing conversation.

### Fallback Estimation: Character-Based Heuristics

When no API usage is available (new conversations, Bedrock limitations), Claude falls back to:

```ts
// services/tokenEstimation.ts
export function roughTokenCountEstimation(content: string, bytesPerToken = 4): number {
  return Math.round(content.length / bytesPerToken)
}
```

With **file-type awareness**:
- JSON / JSONL → **2 bytes/token** (dense punctuation drives token count up)
- Everything else → **4 bytes/token**

Image/document blocks are estimated at a flat **2,000 tokens** (conservatively matching API limits).

### API-Based Token Counting

For precise counts, Claude Code can call the API directly:

```ts
// services/tokenEstimation.ts
export async function countMessagesTokensWithAPI(messages, tools): Promise<number | null> {
  // Uses Anthropic beta.messages.countTokens
  // Falls back to Haiku/Sonnet create() for Vertex/Bedrock edge cases
  // Strips tool-search-specific fields before sending
}
```

- **Anthropic**: `anthropic.beta.messages.countTokens()`
- **Bedrock**: AWS `CountTokensCommand`
- **Vertex**: filtered beta headers to avoid 400 errors

A special **Haiku fallback** (`countTokensViaHaikuFallback`) sends messages to a fast cheap model when the primary API doesn't support countTokens.

---

## Token Budget System

### 1. User Turn Budget (Auto-Continue)

Users can inject a token target into their prompt using natural language:

```ts
// utils/tokenBudget.ts
const SHORTHAND_START_RE = /^\s*\+(\d+(?:\.\d+)?)\s*(k|m|b)\b/i
const VERBOSE_RE = /\b(?:use|spend)\s+(\d+(?:\.\d+)?)\s*(k|m|b)\s*tokens?\b/i
```

Examples: `+500k`, `use 2M tokens`, `spend 1.5m tokens`

The parser extracts the numeric budget and the query loop enforces it:

```ts
// query/tokenBudget.ts
export function checkTokenBudget(
  tracker: BudgetTracker,
  agentId: string | undefined,
  budget: number | null,
  globalTurnTokens: number,
): TokenBudgetDecision {
  if (agentId || budget === null || budget <= 0) {
    return { action: 'stop', completionEvent: null }
  }

  const pct = Math.round((turnTokens / budget) * 100)
  const deltaSinceLastCheck = globalTurnTokens - tracker.lastGlobalTurnTokens

  const isDiminishing =
    tracker.continuationCount >= 3 &&
    deltaSinceLastCheck < DIMINISHING_THRESHOLD && // 500 tokens
    tracker.lastDeltaTokens < DIMINISHING_THRESHOLD

  if (!isDiminishing && turnTokens < budget * COMPLETION_THRESHOLD) { // 0.9
    // Auto-continue with nudge message
    return { action: 'continue', nudgeMessage: getBudgetContinuationMessage(pct, turnTokens, budget), ... }
  }

  // Stop at 90% or when diminishing returns detected
  return { action: 'stop', completionEvent: { ... } }
}
```

**Rules:**
- **Not enforced for subagents** (`agentId` check)
- Continues automatically up to **90%** of the budget
- Stops if **3+ continuations** produce <500 tokens of progress each (diminishing returns)
- Nudge message: `"Stopped at X% of token target (Y / Z). Keep working — do not summarize."`

### 2. API Task Budget (Server-Side)

A separate, first-party-only feature sends a **server-side token budget** to the API:

```ts
// services/api/claude.ts
export function configureTaskBudgetParams(
  taskBudget: Options['taskBudget'],
  outputConfig: BetaOutputConfig & { task_budget?: TaskBudgetParam },
  betas: string[],
): void {
  outputConfig.task_budget = {
    type: 'tokens',
    total: taskBudget.total,
    ...(taskBudget.remaining !== undefined && { remaining: taskBudget.remaining }),
  }
  betas.push(TASK_BUDGETS_BETA_HEADER) // task-budgets-2026-03-13
}
```

The client computes `remaining` across **compaction boundaries** by subtracting the pre-compact final context window size. This prevents the server from under-counting spend after history is summarized.

### 3. Context Window & Auto-Compact Thresholds

```ts
// utils/context.ts
export const MODEL_CONTEXT_WINDOW_DEFAULT = 200_000
```

Context window resolution (`getContextWindowForModel()`):
- Defaults to **200k**
- Supports **1M** for Sonnet 4.x / Opus 4-6 via `[1m]` suffix or beta header
- Overrideable via `CLAUDE_CODE_MAX_CONTEXT_TOKENS` (ant-only)

Auto-compact triggers at:

```ts
// services/compact/autoCompact.ts
export const AUTOCOMPACT_BUFFER_TOKENS = 13_000
export const WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
export const ERROR_THRESHOLD_BUFFER_TOKENS = 20_000
export const MANUAL_COMPACT_BUFFER_TOKENS = 3_000
```

```
Effective Window = ContextWindow - maxOutputTokens(reserved for response)
Auto-Compact Threshold = Effective Window - 13,000
Blocking Limit = Effective Window - 3,000
```

So for a 200k Sonnet 4.6 (32k max output):
- Effective window ≈ 168k
- Auto-compact fires at ≈ **155k** tokens
- Hard block at ≈ **165k** tokens (if auto-compact disabled)

---

## Cost Tracking

### Per-Session Accumulation

All costs live in a **global mutable state** (`bootstrap/state.ts`):

```ts
type State = {
  totalCostUSD: number
  totalAPIDuration: number
  totalToolDuration: number
  totalLinesAdded: number
  totalLinesRemoved: number
  modelUsage: { [modelName: string]: ModelUsage }
  // ...
}
```

The `addToTotalSessionCost()` function (`cost-tracker.ts`) is the single entry point:

```ts
export function addToTotalSessionCost(cost: number, usage: Usage, model: string): number {
  const modelUsage = addToTotalModelUsage(cost, usage, model)
  addToTotalCostState(cost, modelUsage, model)

  // OpenTelemetry counters
  getCostCounter()?.add(cost, attrs)
  getTokenCounter()?.add(usage.input_tokens, { ...attrs, type: 'input' })
  getTokenCounter()?.add(usage.output_tokens, { ...attrs, type: 'output' })
  // ...

  // Recursively add advisor costs
  for (const advisorUsage of getAdvisorUsage(usage)) {
    totalCost += addToTotalSessionCost(advisorCost, advisorUsage, advisorUsage.model)
  }
  return totalCost
}
```

### Model Pricing Tiers

Hardcoded in `utils/modelCost.ts`:

| Model Family | Input $/Mtok | Output $/Mtok | Cache Write $/Mtok | Cache Read $/Mtok |
|-------------|--------------|---------------|--------------------|-------------------|
| Sonnet (3.5/4/4.5/4.6) | $3 | $15 | $3.75 | $0.30 |
| Opus 4 / 4.1 | $15 | $75 | $18.75 | $1.50 |
| Opus 4.5 | $5 | $25 | $6.25 | $0.50 |
| Opus 4.6 Fast Mode | $30 | $150 | $37.5 | $3.00 |
| Haiku 3.5 | $0.80 | $4 | $1.00 | $0.08 |
| Haiku 4.5 | $1 | $5 | $1.25 | $0.10 |

Unknown models fallback to the **Sonnet 4.5 tier** ($5/$25) and set a warning flag.

### Session Persistence

Costs survive process restarts via project-level config:

```ts
// cost-tracker.ts
export function saveCurrentSessionCosts(fpsMetrics?: FpsMetrics): void {
  saveCurrentProjectConfig(current => ({
    ...current,
    lastCost: getTotalCostUSD(),
    lastTotalInputTokens: getTotalInputTokens(),
    lastTotalOutputTokens: getTotalOutputTokens(),
    lastModelUsage: Object.fromEntries(
      Object.entries(getModelUsage()).map(([model, usage]) => [model, { ...usage }])
    ),
    lastSessionId: getSessionId(),
  }))
}
```

Restoration only occurs if the session ID matches, preventing cross-session pollution.

### Cost Hook (Lifecycle)

```ts
// costHook.ts
export function useCostSummary(getFpsMetrics?: () => FpsMetrics | undefined): void {
  useEffect(() => {
    const f = () => {
      if (hasConsoleBillingAccess()) {
        process.stdout.write('\n' + formatTotalCost() + '\n')
      }
      saveCurrentSessionCosts(getFpsMetrics?.())
    }
    process.on('exit', f)
  }, [])
}
```

Prints total cost on exit and persists to disk.

---

## Budget Enforcement

### Pre-API: Blocking Limit (Synthetic Error)

Before every API call, the query loop checks if the conversation is at a **blocking limit** when auto-compact is disabled:

```ts
// query.ts
const { isAtBlockingLimit } = calculateTokenWarningState(
  tokenCountWithEstimation(messagesForQuery) - snipTokensFreed,
  toolUseContext.options.mainLoopModel,
)
if (isAtBlockingLimit) {
  yield createAssistantAPIErrorMessage({
    content: PROMPT_TOO_LONG_ERROR_MESSAGE,
    error: 'invalid_request',
  })
  return { reason: 'blocking_limit' }
}
```

### Post-API: Prompt-Too-Long Recovery

If the API returns a 413 (prompt too long), Claude Code has a **reactive recovery chain**:

1. **Context Collapse drain** — commits staged collapses (if enabled)
2. **Reactive Compact** — forcibly summarizes history
3. If both fail → surface the error and stop

```ts
// query.ts (simplified)
if (isWithheld413) {
  if (contextCollapse) {
    const drained = contextCollapse.recoverFromOverflow(messagesForQuery, querySource)
    if (drained.committed > 0) continue // retry with drained context
  }
  if (reactiveCompact) {
    const compacted = await reactiveCompact.tryReactiveCompact({ ... })
    if (compacted) continue // retry with compacted context
  }
  yield lastMessage
  return { reason: 'prompt_too_long' }
}
```

### Max Output Tokens Recovery

When the model hits `max_output_tokens`:

1. **Escalation** (one-shot): if slot-cap enabled, retry same request at **64k** tokens
2. **Multi-turn recovery** (up to 3 times): inject a meta-message:  
   `"Output token limit hit. Resume directly — no apology, no recap..."`

```ts
// query.ts
if (maxOutputTokensRecoveryCount < MAX_OUTPUT_TOKENS_RECOVERY_LIMIT) {
  const recoveryMessage = createUserMessage({
    content: `Output token limit hit. Resume directly — no apology, no recap...`,
    isMeta: true,
  })
  // continue loop with recoveryMessage appended
}
```

### Tool Result Budgeting

Tool results are capped at multiple levels:

```ts
// constants/toolLimits.ts
export const DEFAULT_MAX_RESULT_SIZE_CHARS = 50_000
export const MAX_TOOL_RESULT_TOKENS = 100_000
export const MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 200_000
```

- **Per-tool**: default 50k characters (~12.5k tokens). Tools can declare their own `maxResultSizeChars`, clamped by the global default.
- **Per-message aggregate**: 200k characters across all parallel tool results in one turn.
- **Overflow handling**: results exceeding limits are **persisted to disk** (`tool-results/<id>.txt`) and replaced in-context with a preview + file path.

---

## Key Code Snippets

### Canonical Context Size Calculation

```ts
// utils/tokens.ts
export function tokenCountWithEstimation(messages: readonly Message[]): number {
  let i = messages.length - 1
  while (i >= 0) {
    const message = messages[i]
    const usage = message ? getTokenUsage(message) : undefined
    if (message && usage) {
      // Handle parallel tool call splits
      const responseId = getAssistantMessageId(message)
      if (responseId) {
        let j = i - 1
        while (j >= 0) {
          const prior = messages[j]
          const priorId = prior ? getAssistantMessageId(prior) : undefined
          if (priorId === responseId) {
            i = j
          } else if (priorId !== undefined) {
            break
          }
          j--
        }
      }
      return (
        getTokenCountFromUsage(usage) +
        roughTokenCountEstimationForMessages(messages.slice(i + 1))
      )
    }
    i--
  }
  return roughTokenCountEstimationForMessages(messages)
}
```

### Auto-Compact Threshold

```ts
// services/compact/autoCompact.ts
export function getEffectiveContextWindowSize(model: string): number {
  const reservedTokensForSummary = Math.min(
    getMaxOutputTokensForModel(model),
    MAX_OUTPUT_TOKENS_FOR_SUMMARY, // 20,000
  )
  let contextWindow = getContextWindowForModel(model, getSdkBetas())
  // Env override: CLAUDE_CODE_AUTO_COMPACT_WINDOW
  return contextWindow - reservedTokensForSummary
}

export function getAutoCompactThreshold(model: string): number {
  const effectiveContextWindow = getEffectiveContextWindowSize(model)
  return effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS // 13,000
}
```

### Token Budget Decision

```ts
// query/tokenBudget.ts
export function checkTokenBudget(
  tracker: BudgetTracker,
  agentId: string | undefined,
  budget: number | null,
  globalTurnTokens: number,
): TokenBudgetDecision {
  if (agentId || budget === null || budget <= 0) {
    return { action: 'stop', completionEvent: null }
  }

  const turnTokens = globalTurnTokens
  const pct = Math.round((turnTokens / budget) * 100)
  const deltaSinceLastCheck = globalTurnTokens - tracker.lastGlobalTurnTokens

  const isDiminishing =
    tracker.continuationCount >= 3 &&
    deltaSinceLastCheck < DIMINISHING_THRESHOLD &&
    tracker.lastDeltaTokens < DIMINISHING_THRESHOLD

  if (!isDiminishing && turnTokens < budget * COMPLETION_THRESHOLD) {
    tracker.continuationCount++
    return {
      action: 'continue',
      nudgeMessage: getBudgetContinuationMessage(pct, turnTokens, budget),
      ...
    }
  }

  return {
    action: 'stop',
    completionEvent: { continuationCount: tracker.continuationCount, pct, turnTokens, budget, diminishingReturns: isDiminishing, durationMs: Date.now() - tracker.startedAt },
  }
}
```

### Cost Accumulation

```ts
// cost-tracker.ts
export function addToTotalSessionCost(cost: number, usage: Usage, model: string): number {
  const modelUsage = addToTotalModelUsage(cost, usage, model)
  addToTotalCostState(cost, modelUsage, model)

  getCostCounter()?.add(cost, attrs)
  getTokenCounter()?.add(usage.input_tokens, { ...attrs, type: 'input' })
  getTokenCounter()?.add(usage.output_tokens, { ...attrs, type: 'output' })
  getTokenCounter()?.add(usage.cache_read_input_tokens ?? 0, { ...attrs, type: 'cacheRead' })
  getTokenCounter()?.add(usage.cache_creation_input_tokens ?? 0, { ...attrs, type: 'cacheCreation' })

  // Recurse for advisor usage
  let totalCost = cost
  for (const advisorUsage of getAdvisorUsage(usage)) {
    const advisorCost = calculateUSDCost(advisorUsage.model, advisorUsage)
    totalCost += addToTotalSessionCost(advisorCost, advisorUsage, advisorUsage.model)
  }
  return totalCost
}
```

---

## Insights for PersonAgent

### 1. Prefer API Usage Over Estimation
Claude Code's `tokenCountWithEstimation()` anchors to the **last API response's usage object** and only estimates messages added since. This is far more accurate than summing cumulative tokens or using character heuristics for the entire conversation. PersonAgent should similarly treat provider usage reports as ground truth.

### 2. Separate Context Window from Output Budget
The codebase cleanly separates:
- `getContextWindowForModel()` — input capacity
- `getModelMaxOutputTokens()` — response capacity
- `getMaxOutputTokensForModel()` — runtime override/env cap

PersonAgent should maintain this separation rather than conflating "max tokens" with context size.

### 3. Natural Language Budget Parsing is Powerful
The `parseTokenBudget()` utility recognizes `+500k`, `use 2M tokens`, etc. This allows users to set spend/context targets inline without UI controls. Consider adopting a similar lightweight NLP approach for PersonAgent's user directives.

### 4. Aggressive Compaction with Circuit Breakers
Auto-compact fires at ~93% of effective window, has a **3-strike circuit breaker** for failures, and tries **session memory compaction** before falling back to full summarization. This prevents API death spirals. PersonAgent should implement similar proactive compaction with failure limits.

### 5. Tool Result Overflow Should Spill to Disk
Rather than truncating tool results in-context (which loses information), Claude Code **persists oversized results to disk** and feeds the model a preview + path. This preserves data integrity while protecting the context window.

### 6. Diminishing Returns Detection
The token budget system detects when continuations produce <500 tokens of progress for 3+ cycles and stops. This prevents infinite "keep going" loops. Any auto-continue feature should include a similar stagnation detector.

### 7. Per-Model Cost Tracking with Fallback Tiers
Maintaining a `modelUsage` map with hardcoded pricing tiers allows accurate cost forecasting. Unknown models fall back to a conservative tier with a warning flag. This is safer than crashing or returning $0.

### 8. Session Persistence for Cost Continuity
Costs are saved to project config keyed by `sessionId` and only restored when IDs match. This simple mechanism prevents cross-session leakage while allowing resume workflows.
