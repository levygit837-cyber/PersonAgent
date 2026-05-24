# Playbook: Decompose LLM Adapters

This playbook covers three related god files that share the same
decomposition pattern:

- `infrastructure/llm/vertex_ai_adapter.py` (1,064 lines, 45 methods)
- `infrastructure/llm/codex_subscription_adapter.py` (944 lines, 41 methods)
- `infrastructure/llm/kimi_coding_adapter.py` (892 lines, 38 methods)

**Target packages:**
- `infrastructure/llm/vertex_ai/`
- `infrastructure/llm/codex/`
- `infrastructure/llm/kimi/`

**Tests:**
- `@backend/tests/test_chat_models_api.py`
- `@backend/tests/unit/test_chat_streaming_turn.py`

Read `_protocol.md` first.

## Why these files are hard

Each LLM adapter is a monolithic class that handles:

1. **Request building** — converting PersonAgent's internal message format
   to the provider's API format (with provider-specific quirks).
2. **Streaming** — handling Server-Sent Events or streaming responses,
   parsing delta chunks, accumulating tool calls.
3. **Error handling** — retries, rate limiting, authentication refresh.
4. **Model configuration** — model specs, token limits, capability flags.

The three adapters share this shape but differ in provider-specific
details. Decomposition follows the same 3-slice pattern for each.

## Public contract that must be preserved

Each adapter implements the `LLMAdapter` protocol. Public surface:
- `__init__(...)`
- `async def chat_completion(request) -> Response`
- `async def chat_completion_stream(request) -> AsyncIterator[Chunk]`
- Model discovery methods

## Status

### vertex_ai_adapter.py

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract models + config | ⏳ Pending | — | |
| 2 — Extract content builder | ⏳ Pending | — | |
| 3 — Extract streaming handler | ⏳ Pending | — | |

### codex_subscription_adapter.py

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract auth store + models | ⏳ Pending | — | |
| 2 — Extract SSE streaming | ⏳ Pending | — | |
| 3 — Extract content builder | ⏳ Pending | — | |

### kimi_coding_adapter.py

| Slice | Status | PR | Notes |
|-------|--------|----|-------|
| 1 — Extract stream state + models | ⏳ Pending | — | |
| 2 — Extract streaming handler | ⏳ Pending | — | |
| 3 — Extract content builder | ⏳ Pending | — | |

## Proposed slices — shared pattern (per adapter)

### Slice 1 — Extract models + config to `<adapter>/models.py`

**What moves out:** Dataclasses, model specs, config constants,
auth-related classes (e.g., `CodexAuthStore`, `CodexAuthSnapshot`,
`VertexModelSpec`, `_AnthropicStreamState`).

**Risk:** Low — pure data.

**Tests:** 5+ cases per adapter.

### Slice 2 — Extract content/request builder to `<adapter>/content_builder.py`

**What moves out:** Methods that convert PersonAgent message format
to the provider's request format. Includes tool call formatting,
image handling, and system prompt construction.

**Risk:** Medium — format differences are subtle.

**Tests:** 15+ cases per adapter — message types, tool calls, images, system prompts.

### Slice 3 — Extract streaming handler to `<adapter>/streaming.py`

**What moves out:** SSE/stream parsing, delta accumulation, tool call
assembly, finish reason handling.

**Risk:** Medium-high — streaming is stateful and timing-sensitive.

**Tests:** 15+ cases per adapter — normal completion, tool calls, abort, errors.

## Anti-patterns specific to LLM adapters

- **Don't abstract across providers** — each adapter is intentionally
  provider-specific. Do not create a shared base class during extraction.
- **Don't change retry logic** — each adapter has provider-specific
  retry/backoff behavior that must be preserved verbatim.
- **Don't normalize error types** — provider-specific exceptions are part
  of the adapter's contract.

## Validation gates

```bash
cd @backend
uv run ruff check src/ tests/
uv run pytest tests/test_chat_models_api.py -v
uv run pytest tests/unit/test_chat_streaming_turn.py -v
uv run pytest tests/unit/ -q
```
