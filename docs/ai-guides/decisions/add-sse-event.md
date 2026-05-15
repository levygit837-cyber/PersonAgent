# Decision Tree: Adicionar um Novo Evento SSE

## Pergunta inicial
> Preciso adicionar um novo tipo de evento SSE para comunicar algo ao frontend.

---

## Passo 1: Definir o evento

### O que precisa comunicar?
- Estado mudou? → `state.invalidation`
- Dados novos disponíveis? → `data.update`
- Progresso de operação? → `progress`

---

## Passo 2: Adicionar tipo de evento

### Arquivo: `application/state/services/state_manager.py` (se for estado)
Ou arquivo específico do subsistema

### Criar função de emissão:
```python
async def emit_novo_evento(
    self,
    client_id: str,
    payload: dict[str, Any],
) -> None:
    await self._emit(
        client_id=client_id,
        event="novo.evento",
        data=json.dumps(payload),
    )
```

---

## Passo 3: Adicionar à API de SSE

### Arquivo: `interfaces/api/state_events.py`

Adicionar handler de evento se necessário:
```python
@router.get("/state/events")
async def state_events(...) -> EventSourceResponse:
    ...
```

Ou usar `StateManager` para emitir via fila existente.

---

## Passo 4: Handler no Frontend

### Arquivo: `desktop-electron/src/api/sse.ts` ou componente específico

```typescript
eventSource.addEventListener("novo.evento", (event) => {
  const data = JSON.parse(event.data);
  // Atualizar store/UI
});
```

---

## Passo 5: Testes

1. Backend: `tests/integration/test_sse.py`
2. Verificar que evento é emitido com formato correto
3. Verificar reconexão (evento deve ser re-enviado se conexão caiu)

---

## Passo 6: Documentação

1. Atualizar `docs/api/README.md` com novo evento
2. Atualizar `docs/app/state-events.md`

---

## Checklist

- [ ] Nome do evento não conflita com existentes
- [ ] Payload é JSON serializável
- [ ] Frontend reconhece novo evento
- [ ] Testes de SSE passam
- [ ] Documentação da API atualizada
