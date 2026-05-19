# State Events (SSE) no PersonAgent

## Visão geral

O backend envia eventos unidirecionais para o desktop via **Server-Sent Events** (`/state/events`). Isso mantém o frontend sincronizado sem polling contínuo.

## Eventos principais

| Evento | Payload | Quando |
|--------|---------|--------|
| `state.invalidation` | `{ "keys": ["conversations", "workspace"] }` | Cache precisa ser limpo |
| `git.signature` | `{ "branch", "dirty", "ahead", "behind" }` | Mudança no repo Git |
| `plan_mode_changed` | `{ "plan_id", "status", "plan_content" }` | Transição de plan mode |
| `memory_job_update` | `{ "job_type", "status", "progress" }` | Job de memória |
| `browser_workspace_update` | `{ "browser_id", "view" }` | Mudança no browser |

## Protocolo

```
GET /state/events
Content-Type: text/event-stream

event: connected
data: {"client_id": "..."}

event: state.invalidation
data: {"keys": ["conversations"]}
```

## Reconexão

O desktop reconecta automaticamente em até 3 segundos após queda. O backend envia `connected` em cada nova stream para que o cliente saiba re-hidratar estado.

## Escopo

- **Unidirecional**: backend -> desktop apenas.
- **Não usa WebSocket** (mais leve para push simples).
- Team Mode usa WebSocket próprio (`/chat/team/ws`).

## Referências

- ADR 0015: State Events SSE
