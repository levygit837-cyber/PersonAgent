# AI-Guide: Next-Step Suggestion Service


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Gera sugestões curtas de próximo passo para o compositor do desktop após cada turno de chat, baseado nas últimas 8 mensagens da conversa.

---

## Entry Point

### `NextStepSuggestionService.suggest` @ `application/services/next_step.py:20`
```python
async def suggest(
    self,
    conversation: Conversation,
    *,
    model: str,
    provider: str,
    finish_reason: str | None = None,
    suppressed: bool = False,
) -> str | None
```
- **Parâmetros**:
  - `conversation` — objeto `Conversation` com mensagens
  - `model`, `provider` — identificadores para chamada LLM
  - `finish_reason` — se for `permission_required`, `plan_approval_requested`, ou `error`, retorna `None`
  - `suppressed` — se `True`, retorna `None`
- **Retorna**: string com sugestão (max 12 palavras) ou `None`

---

## Fluxo

```
suggest()
├── llm_backend is None or suppressed? → return None
├── finish_reason em {permission_required, plan_approval_requested, error}? → return None
├── _render_recent(conversation) → últimas 8 mensagens truncadas a 1200 chars cada
├── resultado vazio? → return None
├── LLM call:
│   ├── system: NEXT_STEP_SUGGESTION_PROMPT (de domain.prompts.compact)
│   ├── user: _render_recent()
│   ├── temperature=0, max_tokens=64, stream=False
│   └── reasoning_level="low", reasoning_budget_tokens=0
├── falha? → log warning, return None
├── sanitiza: remove quotes, collapse whitespace, limita a 12 palavras
└── retorna sugestão
```

---

## Método Privado

### `_render_recent` (função privada do módulo)
```python
def _render_recent(conversation: Conversation) -> str
```
- Localizada em `application/services/next_step.py` (após o método `suggest`)
- Itera `conversation.messages[-8:]` (últimas 8 mensagens)
- Para cada mensagem: `"{role.value}: {content[:1200]}"`
- Content com whitespace collapsed (`" ".join(content.split())`)
- Join com `"\n"`

---

## Prompt

`NEXT_STEP_SUGGESTION_PROMPT` — importado de `domain/prompts/compact.py`
- Não documentado inline; buscar em `domain/prompts/compact.py`

---

## Quando Modificar

### Ajustar número de mensagens analisadas
- Modificar slice `conversation.messages[-8:]` em `_render_recent()` @ `:65`
- Ajustar `max_tokens` proporcionalmente em `suggest()` @ `:43`

### Mudar o prompt
- Editar `NEXT_STEP_SUGGESTION_PROMPT` em `domain/prompts/compact.py`
- Este arquivo não contém o prompt diretamente

### Desabilitar completamente
- Passar `suppressed=True` no caller (chat completion use case)
- Ou não injetar `llm_backend` no construtor

---

## Anti-patterns

- **Nunca** chamar `suggest()` sem verificar `finish_reason` primeiro — o próprio método faz isso, mas o caller deve evitar chamadas desnecessárias.
- **Nunca** aumentar `max_tokens` além de 64 sem considerar o custo — esta é uma chamada LLM extra por turno.

---

## Dependências

- `domain.models.conversation` — `Conversation`
- `domain.repositories.llm_backend_repository` — `LLMBackendRepository`
- `domain.prompts.compact` — `NEXT_STEP_SUGGESTION_PROMPT`
- Consumido por: `chat_completion.py` (via DIContainer)
