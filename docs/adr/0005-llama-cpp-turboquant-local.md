# ADR 0005: Fork llama.cpp with TurboQuant KV Cache for Local Inference

Date: 2025-06-10
Status: Accepted

## Context

Hosted API providers have latency, cost, and data-privacy constraints. We need a first-class local inference path that supports very long context windows (262k tokens) and runs on consumer GPUs without exhausting VRAM.

## Decision

Maintain a fork of `llama.cpp` with **TurboQuant** KV-cache quantization (`turbo4` for both K and V) as the default local inference runtime.

**Process management**
- `LlamaServerProcessManager` discovers the `llama-server` binary (configurable path, PATH fallback, common locations), locates the GGUF model, builds the CLI command, and starts the subprocess during FastAPI lifespan.
- Startup health-check loop probes `GET /health` with a 60-second timeout.
- Graceful shutdown sends `SIGTERM` to the process group, then `SIGKILL` if needed.

**Default local parameters**
```yaml
llm:
  cache_type_k: "turbo4"
  cache_type_v: "turbo4"
  ctx_size: 262144
  n_gpu_layers: 999
  threads: 6
```

**Embedding server**
- `EmbeddingServerProcessManager` extends the same binary with `--embedding --pooling last`.
- Fallback ctx-size cascade: target -> 24576 -> 16384 -> 8192 if startup fails.

## Consequences

- **Easier**: zero-cost local inference; long-context models fit on 24 GB VRAM thanks to TurboQuant; no network dependency for sensitive code review.
- **Harder**: binary must be compiled for the target platform; GPU layer count varies by card; model files are large.
- **Risk**: fork drift from upstream llama.cpp; TurboQuant is experimental and may have subtle accuracy tradeoffs at extreme context lengths.
- **Out of scope**: automatic model downloading; Windows-native build pipeline (community supported).

## Alternatives Considered

- **Ollama**: higher-level but hides quantization flags and context-size tuning we need for TurboQuant.
- **vLLM**: excellent throughput, but heavier memory footprint and no TurboQuant integration.

## Validation

- `llama_server_auto_started` logged at backend startup when `llama_auto_start=True`.
- `@llama/README.md` documents the build flags (`-DGGML_CUDA=ON`, etc.) and benchmark results.
