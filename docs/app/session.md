# Session Management no PersonAgent

## Visão geral

Uma conversa é uma **sessão** com identificador UUID, histórico de mensagens, metadados (plan mode, browser workspace, memória) e título.

## Ciclo de vida

1. **Criação**: `POST /conversations` cria uma nova conversa vazia.
2. **Chat**: mensagens são adicionadas via `POST /chat`.
3. **Persistência**: todo turno salva `MessageORM` no Postgres.
4. **Compactação**: quando o contexto excede o limite, `ContextCompactionService` resume mensagens antigas.
5. **Arquivamento**: conversas inativas por 30 dias podem ser arquivadas (não implementado).

## Metadados

```json
{
  "plan_mode": { "active": false, "status": "inactive" },
  "browser_workspace": { "browser_id": "...", "view": {} },
  "context_compaction": { "compacted_at": "...", "summary": "..." },
  "_operational_memory_prompt": { "memory_items_injected": 3 }
}
```

## Título automático

- Após a primeira mensagem do usuário, um job background gera um título conciso.
- Usa o próprio LLM com um prompt especial de sumarização.

## API

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/conversations` | Criar conversa |
| GET | `/conversations` | Listar conversas |
| GET | `/conversations/{id}` | Detalhes |
| DELETE | `/conversations/{id}` | Arquivar |

## Referências

- `infrastructure/persistence/models.py` (ConversationORM, MessageORM)
- `application/services/session_title.py`
