# llama.cpp TurboQuant no PersonAgent

## Visão geral

O PersonAgent mantém um fork do `llama.cpp` com suporte a **TurboQuant** para inferência local eficiente com contextos de até 262k tokens.

## Build

```bash
cd @llama/llama-cpp-turboquant
mkdir build && cd build
cmake .. -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

## Parâmetros padrão

```yaml
llama:
  ctx_size: 262144
  n_gpu_layers: 999
  threads: 6
  temperature: 0.7
  cache_type_k: turbo4
  cache_type_v: turbo4
  reasoning: default
  reasoning_budget: 2048
```

## Process Manager

`LlamaServerProcessManager` gerencia o ciclo de vida do `llama-server`:

1. Descobre binário (config -> PATH -> locais comuns).
2. Descobre modelo (config -> diretórios padrão).
3. Monta comando com flags TurboQuant e reasoning.
4. Inicia subprocesso no lifespan do FastAPI.
5. Health-check via `GET /health` até 60s.
6. Graceful shutdown com SIGTERM/SIGKILL.

## Embedding Server

Um segundo processo `llama-server` roda com `--embedding --pooling last` para gerar vetores do RAG.

## Troubleshooting

| Problema | Causa provável | Solução |
|----------|----------------|---------|
| `llama_server_auto_start_failed` | Binário não encontrado | Verificar `LLAMA_BINARY_PATH` |
| Timeout no health-check | Modelo muito grande | Aumentar timeout ou reduzir `ctx_size` |
| CUDA out of memory | `n_gpu_layers` alto | Reduzir `n_gpu_layers` ou usar CPU |
| Embedding server falha | Porta ocupada | Verificar `embedding_port` |

## Referências

- ADR 0005: llama.cpp TurboQuant
