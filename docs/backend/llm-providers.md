# LLM Providers no PersonAgent

## Visão geral

O PersonAgent suporta múltiplos provedores de LLM via **Repository Pattern** (`LLMBackendRepository`). Cada adapter traduz chamadas internas para o protocolo do provedor.

## Provedores suportados

| Provedor | Adapter | Uso principal |
|----------|---------|---------------|
| **llama** | `LlamaBackendAdapter` | Inferência local (llama.cpp TurboQuant) |
| **nvidia** | `NvidiaBackendAdapter` | NIM (NVIDIA Inference Microservices) |
| **deepseek** | `DeepSeekBackendAdapter` | API DeepSeek (reasoning nativo) |
| **zenmux** | `ZenMuxBackendAdapter` | ZenMux (gateway multi-modelo) |
| **vertex** | `VertexBackendAdapter` | Google Cloud Vertex AI |
| **kimi** | `KimiBackendAdapter` | Moonshot Kimi |
| **codex** | `CodexBackendAdapter` | OpenAI Codex |

## Interface comum

```python
class LLMBackendRepository(Protocol):
    async def chat_completion(self, messages, temperature, max_tokens, ...): ...
    async def chat_completion_stream(self, messages, ...): ...
    async def embedding(self, texts): ...
    async def close(self): ...
```

## Seleção de provider

1. Requisição do cliente: `provider: "llama"` (default).
2. Fallback automático: se `llama` não responder em 30s, o retry budget pode tentar novamente (ADR 0016).
3. Não há fallback para outro provider automaticamente; isso é decisão explícita do usuário.

## Streaming

Todos os adapters implementam `chat_completion_stream()`, retornando `AsyncIterator[StreamChunk]`:

```python
async for chunk in backend.chat_completion_stream(messages=...):
    yield chunk.content
```

## Configuração

```yaml
llm:
  provider: llama
  model: local-model
  temperature: 0.7
  max_tokens: -1
  reasoning_level: medium
  reasoning_budget_tokens: 2048
```

## Adicionando um novo provider

1. Criar `infrastructure/llm/adapters/<provider>_adapter.py`.
2. Implementar `LLMBackendRepository`.
3. Registrar no `DIContainer.get_llm_backend()`.
4. Adicionar testes de contrato em `tests/unit/llm/`.

## Referências

- ADR 0003: Multi-Provider LLM
- ADR 0005: llama.cpp TurboQuant
