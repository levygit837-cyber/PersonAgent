# Chat no PersonAgent

## Visão geral

O chat é o fluxo principal do PersonAgent. O usuário envia uma mensagem; o backend monta o contexto, classifica a intenção, escolhe ferramentas, conversa com o LLM, executa ferramentas, e retorna a resposta via SSE.

## Fluxo de uma mensagem

1. **Receber**: `POST /chat` com `message`, `conversation_id`, `prompt_mode`, etc.
2. **Contexto**: `BuildContextUseCase` resolve workspace, git, persona, regras.
3. **Classificar**: `PromptContextAnalyzer` resolve `prompt_mode` (se `auto`).
4. **Montar prompt**: `PromptBuilder` cria o system prompt com seções dinâmicas.
5. **Selecionar ferramentas**: `ToolRegistry` filtra por allowlist e deferred loading.
6. **LLM**: `chat_completion_stream()` envia mensagens + tools ao provider.
7. **Tool calls**: se o LLM solicitar tools, `ToolOrchestrator` executa em batches.
8. **Resposta**: texto final (ou plan mode) é emitido via SSE.
9. **Persistir**: mensagens e metadados salvos no Postgres.

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/chat` | Chat normal (SSE) |
| POST | `/chat/team` | Team mode (SSE) |
| WS | `/chat/team/ws` | Team mode (WebSocket) |

## Eventos SSE

```json
{ "event": "message", "content": "..." }
{ "event": "tool_call_started", "tool_call_id": "..." }
{ "event": "tool_result", "tool_call_id": "...", "tool_result": "..." }
{ "event": "plan_mode_changed", "plan_status": "awaiting_approval" }
{ "event": "error", "error": { "code": "..." } }
{ "event": "done" }
```

## Plan Mode

- Ativado quando o agente propõe um plano de ações.
- Estado salvo em `Conversation.metadata["plan_mode"]`.
- Usuário aprova ou cancela via `POST /chat/plan/{approval_id}/approve`.

## Referências

- ADR 0007: Prompt Engineering
- ADR 0009: Plan Mode
- ADR 0010: Tool Orchestrator
