# Decision Tree: Modificar Política de Retry


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Pergunta inicial
> Preciso ajustar como o sistema reage a falhas temporárias (LLM, tools, etc.).

---

## Passo 1: Identificar o escopo

### Se é retry de LLM providers:
→ **Modificar RetryPolicy em adapters**
- Arquivos: `infrastructure/llm/<provider>_adapter.py`
- Ou modificar `application/retry.py` para retry global

### Se é retry de tool calls:
→ **Modificar ToolOrchestrator**
- Arquivo: `application/tools/orchestrator.py`
- Ou modificar `RetryPolicy` passado ao orchestrator

### Se é retry genérico para qualquer operação:
→ **Modificar RetryPolicy global**
- Arquivo: `application/retry.py`

---

## Passo 2: Modificar RetryPolicy

### Arquivo: `application/retry.py`

```python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 10.0
    jitter_seconds: float = 0.25
    foreground_only_for_rate_limits: bool = True
```

### Para ajustar:
- `max_attempts` — número total de tentativas (incluindo a primeira)
- `base_delay_seconds` — delay inicial (dobra a cada tentativa)
- `max_delay_seconds` — teto do delay
- `jitter_seconds` — variação aleatória

---

## Passo 3: Verificar RetryBudget

`RetryBudget` @ `application/retry.py` registra cada tentativa:
- `attempt`, `delay_seconds`, `error.code`, `retryable`
- Exposto em metadata de erro

### Para adicionar novo tipo de erro como retryable:
1. Adicionar classe ao módulo `domain/exceptions.py`
2. Definir `retryable=True` no dataclass de erro
3. Adicionar ao check em `retry_async()`

---

## Passo 4: Testes

1. `tests/unit/test_retry.py`
2. Verificar:
   - Backoff exponencial (0.5, 1.0, 2.0...)
   - Jitter dentro dos bounds
   - Erros não-retryable param imediatamente
   - Budget é preenchido corretamente

---

## Passo 5: Documentação

1. Atualizar ADR 0016 se mudar decisão arquitetural
2. Atualizar `docs/app/error-handling.md`

---

## Checklist

- [ ] Delay máximo não excede timeout do caller
- [ ] Erros retryable não incluem permission denied
- [ ] Budget não vaza memória (limitado)
- [ ] Testes de retry passam
- [ ] Documentação atualizada
