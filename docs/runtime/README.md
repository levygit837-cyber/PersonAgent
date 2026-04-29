# Runtime Documentation

This section covers local model runtime, hosted provider adapters, process
management, and configuration.

## Local llama.cpp Runtime

The local runtime lives under `@llama/` and is started by backend process
management when `llama_auto_start` is enabled.

Current long-context defaults:

```yaml
llm:
  cache_type_k: "turbo4"
  cache_type_v: "turbo4"
  ctx_size: 262144
```

Build and runtime notes remain in `@llama/README.md`; this central section
tracks how the app depends on that runtime.

## Hosted Providers

Provider credentials and provider-specific payload logic are backend-owned.
The Electron desktop sends provider and model selection; it should not own
provider credentials or provider-specific request shaping.

Current backend provider families include:

- Local llama.cpp.
- NVIDIA NIM.
- Official DeepSeek API.
- Vertex/Gemini.
- Kimi.
- Codex subscription-backed inference.

## Configuration

Primary configuration surfaces:

- `config.yaml`
- `.env`
- `@backend/src/personagent/infrastructure/config/settings.py`
- Provider-specific adapter modules under `@backend/src/personagent/infrastructure/llm/`

## Future Pages

- `llama-turboquant.md`
- `config.md`
- `models.md`
- `process-manager.md`
