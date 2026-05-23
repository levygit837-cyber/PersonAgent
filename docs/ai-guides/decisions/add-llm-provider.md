# Decision Tree: Adicionar um Novo Provider LLM


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Pergunta inicial
> Preciso adicionar suporte a um novo provedor de LLM (ex: Groq, Together, Fireworks).

---

## Passo 1: Verificar se o provider é OpenAI-compatible

### Se sim (usa `/chat/completions` e `/models`):
1. Criar `infrastructure/llm/<provider>_adapter.py`
2. Herdar de `LLMBackendRepository`
3. Copiar `LlamaCppAdapter` como template
4. Modificar: base_url, auth header, timeout defaults
5. Pular para **Passo 4**

### Se não (protocolo próprio):
1. Criar adapter do zero
2. Implementar `chat_completion()`, `chat_completion_stream()`, `get_models()`, `close()`
3. Pular para **Passo 4**

---

## Passo 2: Verificar se tem reasoning nativo

### Se sim (ex: DeepSeek, Codex):
- Implementar `extract_reasoning_field()` ou usar `openai_compatible_parser.split_thinking_tags()`
- Passar `reasoning_content` como parte do `InferenceResult`

### Se não:
- Reasoning é em tags `<thinking>` no content
- Usar `openai_compatible_parser.split_thinking_tags()` para parsear

---

## Passo 3: Verificar tool calls

### Se suporta tool_calls nativamente (formato OpenAI):
- Usar `accumulate_tool_call_delta()` para streaming
- Formato: `{"type":"function","function":{"name":"...","arguments":"..."}}`

### Se não suporta:
- O agente não pode usar tools com este provider
- Ou implementar parsing custom no adapter

---

## Passo 4: Registrar no DIContainer

### Arquivo: `interfaces/config/di_container.py`

1. Adicionar import do novo adapter
2. Adicionar provider à validação em `get_llm_backend()` (linha ~95):
   ```python
   if normalized_provider not in {
       "llama", "nvidia", "deepseek", "zenmux", "vertex", "kimi", "codex", "NOVO",
   }:
   ```
3. Adicionar branch em `_create_llm_backend()`:
   ```python
   if normalized_provider == "NOVO":
       return NovoAdapter(...)
   ```

---

## Passo 5: Adicionar configuração

### Arquivo: `infrastructure/config/settings.py`

Adicionar settings opcionais:
```python
NOVO_BASE_URL: str = "https://api.novo.com/v1"
NOVO_API_KEY: str | None = None
NOVO_TIMEOUT: float = 120.0
```

---

## Passo 6: Testes

1. Criar `tests/unit/llm/test_novo_adapter.py`
2. Testar:
   - `chat_completion()` com mock HTTP
   - `chat_completion_stream()` com mock SSE
   - `get_models()` com mock
   - `close()` limpa cliente
3. Testar integração: `tests/integration/test_chat.py` com provider="NOVO"

---

## Passo 7: Documentação

1. Atualizar ADR 0003: adicionar provider à tabela
2. Atualizar `docs/backend/llm-providers.md`
3. Atualizar `docs/ai-guides/backend/llm-adapters-deep-dive.md`

---

## Checklist

- [ ] Adapter implementa `LLMBackendRepository`
- [ ] Retry configurado para connection/timeout errors
- [ ] Reasoning content extraído corretamente
- [ ] Tool calls funcionam em streaming
- [ ] Registrado no DIContainer
- [ ] Testes unitários passam
- [ ] Testes de integração passam
- [ ] Docs atualizadas
