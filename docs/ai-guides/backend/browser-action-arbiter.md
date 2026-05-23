# AI-Guide: Browser Action Arbiter


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

O `BrowserActionArbiter` decide se uma ação do agente no browser requer aprovação do usuário antes de ser executada. Ele implementa uma máquina de estados de cooperação com três modos e regras de cooldown baseadas em atividade humana recente.

---

## Entry Points

### `BrowserActionArbiter.decide` @ `application/services/browser_action_arbiter.py:48`
```python
def decide(
    self,
    *,
    tool_name: str,
    arguments: ToolArguments,
    context: ToolUseContext,
) -> BrowserArbiterDecision
```
- **Parâmetros**:
  - `tool_name` — nome da ferramenta de browser (ex: `BrowserClick`, `BrowserType`, `BrowserScript`)
  - `arguments` — argumentos da ferramenta (node_id, action, value, submit, etc.)
  - `context` — `ToolUseContext` com metadata contendo estado de browser cooperation
- **Retorna**: `BrowserArbiterDecision` com behavior (`ALLOW` ou `ASK`) e metadata
- **Levanta**: nenhuma exceção; sempre retorna uma decisão

---

## Decision Tree

```
Browser Cooperation desabilitado?
├── Sim → ALLOW (linha 56-57)
└── Não → Qual modo?
    ├── "observe_only" → ASK (linha 60-67)
    ├── "suggest_before_action" → ASK (linha 68-75)
    ├── "agent_control" → Avaliar cooldown
    │   ├── Atividade humana nos últimos 3s? → ASK (linha 88-96)
    │   ├── Ação destrutiva + atividade nos últimos 10s? → ASK (linha 97-105)
    │   ├── Ação destrutiva que requer confirmação explícita? → ASK (linha 106-114)
    │   └── Nenhum dos acima → ALLOW (linha 115)
    └── Modo desconhecido → ASK (linha 77-84)
```

---

## Constantes Críticas

| Constante | Valor | Linha | Significado |
|-----------|-------|-------|-------------|
| `HUMAN_ACTIVITY_COOLDOWN_SECONDS` | `3` | `:22` | Janela após interação do usuário que exige aprovação |
| `DESTRUCTIVE_ACTIVITY_COOLDOWN_SECONDS` | `10` | `:23` | Janela estendida para ações destrutivas |
| `_DESTRUCTIVE_RE` | regex | `:24` | Match para: submit, save, delete, remove, checkout, purchase, buy, pay, confirm, login, sign in, upload, download, close |

---

## Classes e Tipos

### `BrowserArbiterDecision` @ `application/services/browser_action_arbiter.py:31`
```python
@dataclass(frozen=True, slots=True)
class BrowserArbiterDecision:
    behavior: ToolPermissionBehavior   # ALLOW | ASK | DENY
    reason: str                        # Mensagem explicativa
    decision: str                      # Código da decisão (ex: "observe_only_requires_approval")
    metadata: dict[str, Any]           # Contexto da decisão
```
- `to_permission_result()` → converte para `ToolPermissionResult` @ `:37`

---

## Métodos Privados (regras de decisão)

### `_active_state` @ `:117`
- Extrai estado de browser cooperation do `context.metadata`
- Chave: `BROWSER_COOPERATION_METADATA_KEY = "browser_cooperation"` (importado de `browser_cooperation.py`)
- Fallback: procura primeiro `context.conversation_id`, depois qualquer entrada enabled

### `_last_user_activity_age_seconds` @ `:129`
- Lê `state["last_user_activity_at"]` (ISO datetime string)
- Retorna `float | None` — segundos desde a última atividade

### `_is_destructive` @ `:142`
- Ferramentas sempre destrutivas: `BrowserCloseTab`, `BrowserScript`
- `BrowserType` com `submit=True` → destrutivo
- `BrowserClick` sem `node_id` → destrutivo
- Regex `_DESTRUCTIVE_RE` aplicado à concatenação de `action + value + text + key + url`

### `_requires_explicit_confirmation` @ `:158`
- Subconjunto mais restrito de `_is_destructive`
- Sempre requer confirmação para: `BrowserCloseTab`, `BrowserScript`
- `BrowserAct` com action em `{submit, upload, drop}` → confirmação
- `BrowserType` com `submit=True` → confirmação
- `BrowserClick` sem `node_id` → confirmação

---

## Quando Modificar

### Adicionar um novo modo de cooperação
1. Adicionar à constante `BROWSER_COOPERATION_MODES` em `browser_cooperation.py:25`
2. Adicionar branch em `decide()` @ `browser_action_arbiter.py:59-84`
3. Atualizar este AI-Guide

### Ajustar o que é considerado destrutivo
1. Modificar regex `_DESTRUCTIVE_RE` @ `:24`
2. Modificar `_is_destructive()` @ `:142` para novos tool names
3. Modificar `_requires_explicit_confirmation()` @ `:158` se aplicável

### Mudar cooldowns
1. Modificar constantes `HUMAN_ACTIVITY_COOLDOWN_SECONDS` ou `DESTRUCTIVE_ACTIVITY_COOLDOWN_SECONDS` @ `:22-23`

---

## Anti-patterns

- **Nunca** bypassar o arbiter diretamente em handlers de tools. Sempre chamar `decide()` e respeitar o resultado.
- **Nunca** hardcode regras de browser em `ToolOrchestrator` — use o arbiter.
- **Nunca** modificar `_DESTRUCTIVE_RE` sem testar contra falsos positivos (ex: "close" em "close to done").

---

## Testes Relevantes

- `@backend/tests/test_browser_cooperation.py` — valida ciclo de vida de cooperação
- `@backend/tests/integration/test_browser_tools.py` — valida tool calls com arbiter

---

## Dependências

- Importa de: `domain.tools` (`ToolArguments`, `ToolPermissionBehavior`, `ToolPermissionResult`, `ToolUseContext`)
- Importa de: `application.services.browser_cooperation` (constantes de metadata)
- Consumido por: `application.tools.orchestrator` (via permission check de browser tools)
