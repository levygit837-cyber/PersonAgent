# AI-Guide: Session Memory Service


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Mantém arquivos Markdown de memória por conversa no filesystem, atualizados periodicamente pelo LLM com resumo do histórico recente. É a camada 1 (Session Memory) da arquitetura de memória de 3 camadas.

---

## Entry Points

### `SessionMemoryService.load` @ `application/services/session_memory.py:34`
```python
def load(self, conversation_id: str) -> str | None
```
- Lê arquivo de memória do filesystem
- Path: `~/.personagent/session-memory/{safe_conversation_id}.md`
- Retorna `None` se arquivo não existir

### `SessionMemoryService.update` @ `:44`
```python
async def update(
    self,
    conversation: Conversation,
    *,
    model: str,
    provider: str,
) -> str | None
```
- Gera/atualiza arquivo de memória via LLM
- Template: `SESSION_MEMORY_TEMPLATE` (se não houver memória anterior)
- Prompt de update: `SESSION_MEMORY_UPDATE_PROMPT`
- Temperatura=0, max_tokens=2_048
- Retorna conteúdo atualizado ou `None` em falha

### `SessionMemoryService.memory_path` @ `:30`
```python
def memory_path(self, conversation_id: str) -> Path
```
- Sanitiza `conversation_id` (alnum + `-_`, max 96 chars)
- Retorna `Path(root) / "{id}.md"`

---

## Construtor

### `SessionMemoryService.__init__` @ `:22`
```python
def __init__(
    self,
    llm_backend: LLMBackendRepository | None = None,
    root: str | Path | None = None,
) -> None
```
- `root` default: `~/.personagent/session-memory`
- `llm_backend` — necessário para `update()`; se `None`, update retorna `None`

---

## Prompts

### `SESSION_MEMORY_TEMPLATE`
- Importado de `domain.prompts.compact`
- Template base para novas memórias de sessão

### `SESSION_MEMORY_UPDATE_PROMPT`
- Importado de `domain.prompts.compact`
- Instrui LLM a analisar histórico e produzir memória estruturada

---

## Quando Modificar

### Mudar local de armazenamento
- Passar `root` no construtor ou modificar default @ `:28`

### Ajustar tamanho de memória
- Modificar `max_tokens` em `update()` @ `:70` (atualmente 2_048)
- Ajustar template em `domain.prompts.compact`

### Desabilitar session memory
- Não injetar `llm_backend` no construtor → `update()` retorna `None`

---

## Anti-patterns

- **Nunca** escrever diretamente no filesystem fora deste serviço — a sanitização de `conversation_id` é crítica para segurança
- **Nunca** usar memória sem verificar `load()` primeiro — pode não existir para conversas novas
- **Nunca** chamar `update()` sincronamente — é async e pode levar segundos (chamada LLM)

---

## Dependências

- `domain.models.conversation` — `Conversation`, `Message`
- `domain.repositories.llm_backend_repository` — `LLMBackendRepository`
- `domain.prompts.compact` — `SESSION_MEMORY_TEMPLATE`, `SESSION_MEMORY_UPDATE_PROMPT`
- Consumido por: `ChatCompletionUseCase` (via DIContainer), `PromptBuilder`
