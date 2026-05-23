# AI-Guide: Request Context

## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Histórico

Até a Fase 0.3 desta refatoração existia um `StateManager` singleton em
`application/state/services/state_manager.py` que mantinha um único
`AppState` mutável por processo. O padrão era inseguro para multi-tenant:
duas requisições concorrentes sobrescreviam o mesmo `conversation_id`,
`workspace_root`, `system_context`, `user_context` etc.

O singleton foi **removido** nesta fase. Em seu lugar usamos um snapshot
imutável por requisição: `RequestContext`.

## Propósito

`RequestContext` é um `@dataclass(frozen=True, slots=True)` instanciado
no edge da API (rota FastAPI / handler WebSocket) e propagado
explicitamente pela cadeia de chamadas. Cada requisição obtém o seu
próprio contexto, sem compartilhar estado com nenhuma outra requisição.

---

## Entry Points

### `RequestContext.__init__` @ `application/state/request_context.py`
Construção direta para casos de teste e fluxos sem `BuildContextUseCase`.

```python
RequestContext(
    request_id="…",            # default: uuid4
    conversation_id="…",
    workspace_root="…",
    permission_mode="manual",  # "auto" | "manual" | "ask"
    system_context=None,
    user_context=None,
    tenant_id=None,
    user_id=None,
    created_at=…,              # default: now(UTC)
    extra={},
)
```

### `RequestContext.from_build_result`
Caminho canônico depois de rodar `BuildContextUseCase`:

```python
ctx = RequestContext.from_build_result(
    conversation_id="conv-1",
    workspace_root="/path/ws",
    result=context_build_result,
    permission_mode="auto",
    tenant_id=None,
    user_id=None,
    request_id=None,
)
```

### `BuildContextUseCase.build_request_context`
`application/use_cases/context/build_context.py:78` — atalho que combina
`execute()` com `RequestContext.from_build_result`. Use sempre que
precisar do contexto montado e do snapshot da requisição em um único
passo.

### `RequestContext.with_overrides`
Devolve uma **cópia** com campos opcionais substituídos. O `request_id`
e o `created_at` permanecem para preservar a identidade da requisição
original.

---

## Campos

| Campo | Tipo | Notas |
|-------|------|-------|
| `request_id` | `str` | UUID gerado por requisição |
| `conversation_id` | `str` | ID da conversa ativa |
| `workspace_root` | `str` | Diretório raiz absoluto |
| `permission_mode` | `str` | `auto` / `manual` / `ask` |
| `system_context` | `SystemContext \| None` | Snapshot do contexto de sistema |
| `user_context` | `UserContext \| None` | Snapshot do contexto do usuário |
| `tenant_id` | `str \| None` | Reservado para multi-tenant |
| `user_id` | `str \| None` | Reservado para multi-tenant |
| `created_at` | `datetime` | Timestamp UTC |
| `extra` | `dict[str, Any]` | Metadados específicos da requisição |

---

## AppState

`AppState` (`application/state/app_state.py`) continua existindo como
**dataclass passiva** para casos em que código legado ainda precisa do
shape antigo (testes, scripts). Não há mais singleton segurando-o, e
nenhum caminho de produção lê/escreve no `AppState`.

Não adicione novas dependências em `AppState`. Adicione campos novos a
`RequestContext` em vez disso.

---

## Quando Modificar

### Adicionar novo campo de requisição
1. Adicionar o campo a `RequestContext` em `application/state/request_context.py`
2. Atualizar `from_build_result` e `with_overrides` se necessário
3. Propagar pelo `BuildContextUseCase.build_request_context` quando aplicável
4. Adicionar teste em `tests/unit/test_request_context.py`

### Adicionar suporte multi-tenant
1. Popular `tenant_id` / `user_id` no edge (rota/handler) com base na auth
2. Repassar o `RequestContext` para use cases que precisarem do tenant
3. Os campos já existem em `RequestContext` — nenhuma mudança de schema necessária

---

## Anti-patterns

- **Nunca** reintroduzir um singleton global de estado. Se precisar de
  estado compartilhado, modele como repositório/serviço injetado via
  DI container.
- **Nunca** mutar `RequestContext` diretamente. Use `with_overrides`
  para produzir uma cópia derivada.
- **Nunca** passar `dict[str, Any]` no lugar de `RequestContext`. O
  contrato explícito é o ponto da refatoração.

---

## Dependências

- `domain.context.models` — `ContextBuildResult`, `SystemContext`, `UserContext`
- Consumidores diretos: `BuildContextUseCase` (constrói o snapshot).
  Em PRs subsequentes da Fase 0/1 outros use cases serão atualizados
  para receber `RequestContext` como parâmetro.
