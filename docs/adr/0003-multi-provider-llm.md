# ADR 0003: Multi-Provider LLM with Repository Pattern and 7 Adapters

Date: 2025-06-10
Status: Accepted

## Context

We do not want vendor lock-in to a single hosted API. Local inference (llama.cpp), NVIDIA NIM, and multiple cloud providers must be interchangeable from the perspective of the chat-completion use case.

## Decision

Introduce a domain port `LLMBackendRepository` and implement one adapter per supported provider. The `DIContainer` holds a singleton map of initialized backends keyed by provider name.

**Supported providers**

| Provider | Adapter | Notes |
|---|---|---|
| `llama` | `LlamaCppAdapter` | Local server, TurboQuant KV cache, longest context |
| `nvidia` | `NvidiaNimAdapter` | Self-hosted or cloud NIM endpoints |
| `deepseek` | `DeepSeekAdapter` | Official DeepSeek API |
| `zenmux` | `ZenMuxAdapter` | Gateway/aggregator endpoint |
| `vertex` | `VertexAiAdapter` | Google Vertex / Gemini |
| `kimi` | `KimiCodingAdapter` | Moonshot Kimi with Anthropic-style API |
| `codex` | `CodexSubscriptionAdapter` | OpenAI Codex CLI-backed inference |

Each adapter implements:
- `chat_completion_stream(...)` returning an async generator of domain chunks.
- `get_models()` with TTL-cached model catalogs.
- `close()` for graceful connection shutdown.

Provider selection travels from the desktop (renderer -> API client) as a string; the backend resolves it through the DI container.

## Consequences

- **Easier**: A/B test models by changing one request field; fallback logic can switch adapters at runtime.
- **Harder**: Every adapter must handle streaming edge cases (chunk boundaries, tool-call split, reasoning blocks) independently.
- **Risk**: payload semantics differ across providers (e.g., reasoning budget, system message placement). Adapters must normalize these before returning domain chunks.
- **Out of scope**: automatic model routing based on workload type (planned for future).

## Alternatives Considered

- **Single OpenAI-compatible client with base-url swap**: rejected because providers diverge on auth, model listing, parameter names, and reasoning formats.
- **LangChain / LiteLLM proxy**: adds an external dependency and latency layer; we prefer lightweight, owned adapters.

## Validation

- Unit tests in `@backend/tests/unit/` mock `LLMBackendRepository` to test use cases without network.
- Adapter-specific tests validate payload shape against provider documentation.
