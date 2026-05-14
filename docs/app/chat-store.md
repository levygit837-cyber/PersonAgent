# Chat Store no PersonAgent

## Visão geral

O estado do chat no frontend é gerenciado por uma combinação de **TanStack Query** (dados do servidor) e **React Context** (estado local da UI).

## Estrutura de estado

```typescript
interface ChatState {
  conversationId: string | null;
  messages: Message[];
  isStreaming: boolean;
  planMode: PlanModeState | null;
  pendingToolApprovals: ToolApproval[];
  error: ChatError | null;
}
```

## Fluxo de dados

1. **Inicialização**: TanStack Query busca conversas e mensagens do backend.
2. **Envio**: usuário digita mensagem -> `POST /chat` -> SSE stream.
3. **Streaming**: eventos SSE atualizam o estado incrementalmente (`message`, `tool_call_started`, `tool_result`).
4. **Persistência**: mensagens confirmadas pelo backend são invalidadas e re-fetched.

## Plan Mode na UI

- Quando `plan_mode_changed` com `status: "awaiting_approval"`, a UI exibe o plano e botões Aprovar/Cancelar.
- Aprovação chama `POST /chat/plan/{approval_id}/approve` com assinatura HMAC.

## Tool Approvals

- Evento `permission_required` pausa o stream e exibe modal de aprovação.
- O desktop gera assinatura via `auth.createSignedActionApproval()`.

## Referências

- `src/stores/chatStore.ts` (se existir)
- ADR 0009: Plan Mode
