# AI-Guide: LLM Adapters Deep Dive

## Propósito

Cada adapter traduz chamadas internas do domínio para o protocolo específico de um provedor de LLM, normalizando: streaming, tool calls, reasoning content, auth, e model listing.

---

## Interface Comum

### `LLMBackendRepository` (Protocol)
```python
async def chat_completion(
    self,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    stream: bool,
    tools: list[dict] | None,
    tool_choice: str | None,
    model: str,
    provider: str,
    reasoning_level: str,
    reasoning_budget_tokens: int,
) -> InferenceResult

async def chat_completion_stream(
    self,
    messages: list[dict],
    ...,
) -> AsyncIterator[StreamChunk]

async def get_models(self) -> list[str]

async def close(self) -> None
```

---

## Adapters

### `LlamaCppAdapter` @ `infrastructure/llm/llama_cpp_adapter.py:34`
- **Protocolo**: OpenAI-compatible HTTP (llama-server local)
- **Base URL**: `http://localhost:8080/v1` (default)
- **Timeout**: 120s (default), stream read timeout configurável
- **Features**:
  - Parsing de reasoning via `<think>` tags ou campo `reasoning_content`
  - Tool call delta accumulation para streaming
  - Retry com tenacity (`stop_after_attempt(3)`, `wait_exponential`)
- **Parâmetros**: `reasoning`, `reasoning_budget`, `ctx_size`

### `NvidiaNimAdapter` @ `infrastructure/llm/nvidia_nim_adapter.py`
- **Protocolo**: OpenAI-compatible (NVIDIA NIM endpoints)
- Suporta self-hosted e cloud

### `DeepSeekAdapter` @ `infrastructure/llm/deepseek_adapter.py`
- **Protocolo**: API oficial DeepSeek
- **Feature nativa**: reasoning com `reasoning_content`
- Auth via API key

### `ZenMuxAdapter` @ `infrastructure/llm/zenmux_adapter.py`
- **Protocolo**: Gateway multi-modelo (OpenAI-compatible)
- Roteamento interno baseado em model selection

### `VertexAiAdapter` @ `infrastructure/llm/vertex_ai_adapter.py`
- **Protocolo**: Google Vertex AI / Gemini
- Auth via service account ou API key
- Suporta streaming e tool calls

### `KimiCodingAdapter` @ `infrastructure/llm/kimi_coding_adapter.py`
- **Protocolo**: Moonshot Kimi com API style Anthropic
- Suporta extended thinking

### `CodexSubscriptionAdapter` @ `infrastructure/llm/codex_subscription_adapter.py`
- **Protocolo**: OpenAI Codex CLI-backed
- Pode usar subprocess ou HTTP local

---

## Parsing OpenAI-Compatible

### `openai_compatible_parser.py`
Funções compartilhadas entre adapters:
- `accumulate_tool_call_delta()` — acumula deltas de tool calls em streaming
- `extract_reasoning_field()` — extrai campo `reasoning_content` da resposta
- `normalize_message_content()` — normaliza content vs reasoning_content
- `split_thinking_tags()` — parseia `<think>...</think>` ou `<thinking>...</thinking>`
- `ThinkingTagState` — máquina de estados para parse de thinking tags em streaming

---

## Retry Policy

### Tenacity configuration (em `LlamaCppAdapter`)
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((LLMBackendConnectionError, LLMBackendTimeoutError)),
)
```
- 3 tentativas
- Backoff exponencial: 2s, 4s, 8s, max 10s
- Só retry para connection/timeout errors

---

## Quando Modificar

### Adicionar novo provider
1. Criar classe em `infrastructure/llm/<provider>_adapter.py`
2. Implementar `LLMBackendRepository`
3. Registrar em `DIContainer._create_llm_backend()` @ `interfaces/config/di_container.py`
4. Adicionar provider à lista de providers suportados no DIContainer
5. Criar testes de contrato

### Ajustar parsing de reasoning
- Modificar `split_thinking_tags()` ou `extract_reasoning_field()` em `openai_compatible_parser.py`
- Atualizar todos os adapters que usam essas funções

### Mudar retry
- Modificar decorators tenacity no adapter específico
- Ou criar retry uniforme em nível de `DIContainer`

---

## Anti-patterns

- **Nunca** hardcode URL de provider no adapter — usar settings/config
- **Nunca** ignorar `reasoning_content` — sempre extrair e repassar
- **Nunca** fazer retry para erros de auth (401) ou rate limit (429) sem backoff exponencial
- **Nunca** criar novo `httpx.AsyncClient` a cada request — reutilizar via `_get_client()`

---

## Dependências

- `domain.repositories.llm_backend_repository` — protocolo
- `domain.models.inference_result` — `InferenceResult`, `StreamChunk`
- `domain.exceptions` — `LLMBackendConnectionError`, `LLMBackendTimeoutError`, `provider_http_error`
- `infrastructure.llm.openai_compatible_parser` — funções compartilhadas
- Consumido por: DIContainer (singleton por provider)
