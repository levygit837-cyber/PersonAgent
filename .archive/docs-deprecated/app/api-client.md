# API Client no PersonAgent

## Visão geral

O desktop consome a API FastAPI do backend via fetch/http client com autenticação bearer injetada automaticamente.

## Configuração base

```typescript
const API_BASE = "http://localhost:8000";

async function apiFetch(path: string, options?: RequestInit) {
  const headers = await window.electronAPI.auth.getHeaders();
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...options?.headers },
  });
}
```

## Endpoints principais

| Método | Endpoint | Uso |
|--------|----------|-----|
| GET | `/health` | Verificar backend |
| POST | `/chat` | Chat com SSE |
| POST | `/chat/team` | Team mode |
| WS | `/chat/team/ws` | Team mode WebSocket |
| GET | `/state/events` | SSE de eventos |
| GET | `/conversations` | Listar conversas |
| POST | `/conversations` | Criar conversa |
| GET | `/skills` | Listar skills |

## SSE

```typescript
const eventSource = new EventSource(`${API_BASE}/state/events`);
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.event === "state.invalidation") {
    invalidateCache(data.keys);
  }
};
```

## Tratamento de erros

- 401: redirecionar para tela de configuração de token.
- 503: exibir "Backend indisponível" com botão de retry.
- Erros SSE: reconectar automaticamente em 3s.

## Referências

- `src/api/client.ts` (se existir)
- ADR 0018: Local Auth
