# AI-Guide: Browser Cooperation


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Sistema de cooperação entre usuário e agente no browser. Rastreia eventos do browser, normaliza-os em envelopes, aplica redação de dados sensíveis, e constrói contexto para o agente sobre o que o usuário está fazendo na web.

---

## Constantes Críticas

| Constante | Valor | Linha | Significado |
|-----------|-------|-------|-------------|
| `BROWSER_COOPERATION_METADATA_KEY` | `"browser_cooperation"` | `:23` | Chave no `Conversation.metadata` |
| `BROWSER_COOPERATION_DEFAULT_MODE` | `"observe_only"` | `:24` | Modo padrão quando ativado |
| `BROWSER_COOPERATION_MODES` | `{"observe_only", "suggest_before_action", "agent_control"}` | `:25` | Modos válidos |
| `MAX_INGEST_EVENTS` | `100` | `:26` | Limite de eventos por ingest |
| `MAX_RECENT_ACTIONS` | `12` | `:27` | Ações recentes no contexto do agente |
| `MAX_NOTIFICATIONS` | `12` | `:28` | Notificações no contexto |
| `MAX_VISIBLE_BUTTONS` | `16` | `:29` | Botões visíveis na UI |
| `MAX_PAYLOAD_CHARS` | `4_000` | `:30` | Limite de chars por payload |
| `MAX_USEFUL_TIMELINE` | `200` | `:31` | Eventos na timeline útil |
| `MAX_RAW_EVENTS_PREVIEW` | `80` | `:32` | Preview de eventos raw |
| `MAX_AGENT_EVENTS` | `12` | `:33` | Eventos enviados ao agente |
| `MAX_PENDING_PROPOSALS` | `12` | `:34` | Propostas pendentes |

---

## Classes Principais

### `BrowserEventEnvelope` @ `application/services/browser_cooperation.py:80`
```python
@dataclass(frozen=True, slots=True)
class BrowserEventEnvelope:
    event_id: str
    sequence: int
    conversation_id: str
    browser_id: str
    kind: str                     # Tipo de evento (click, input, navigation, etc.)
    source: str = "user"           # Origem: user, agent, system, browser
    timestamp: str | None = None
    tab_id: str | None = None
    page_id: str | None = None
    url: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    channel: str = "event"         # event, action, proposal, trace
    trace_role: str = "user"       # user, agent, system, browser
    visibility: str = "raw"        # raw, useful, debug
    raw_kind: str | None = None
    coordinates: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None
    trace_effect: str | None = None
    correlation_id: str | None = None
    importance: str = "low"        # low, medium, high
    semantic_label: str = ""
```

---

## Regras de Redação (Dados Sensíveis)

### `_SENSITIVE_FIELD_RE` @ `:45`
- Match para: password, token, secret, api_key, auth, session, cookie, credit card, cvv, email, ssn, cpf

### `_SENSITIVE_QUERY_KEYS` @ `:50`
- `access_token`, `auth`, `code`, `email`, `key`, `password`, `refresh_token`, `session`, `state`, `token`

### Padrões de detecção
- `_EMAIL_RE` @ `:62` — regex de email
- `_CARD_RE` @ `:63` — sequência de 13-19 dígitos (cartões)
- `_JWT_RE` @ `:64` — formato JWT (3 partes base64 separadas por `.`)
- `_LONG_TOKEN_RE` @ `:65` — strings alfanuméricas de 32+ chars

### Importância de Eventos
- `_HIGH_IMPORTANCE_KINDS` @ `:66` — `click`, `input`, `change`, `submit`, `route`, `route_change`, `navigation`, `action`, `mutation`

---

## Política Padrão

`DEFAULT_COOPERATION_POLICY` @ `:35`
```python
{
    "raw_event_retention_limit": 5000,
    "raw_event_retention_days": 7,
    "visible_timeline_limit": 200,
    "agent_context_recent_limit": 12,
    "store_raw_payloads": False,
}
```

---

## Quando Modificar

### Adicionar novo tipo de evento
1. Adicionar ao `kind` permitido (não há enum, é string livre)
2. Se for de alta importância, adicionar a `_HIGH_IMPORTANCE_KINDS`
3. Atualizar `BrowserActionArbiter` se a ação requer aprovação

### Ajustar redação de dados sensíveis
- Modificar `_SENSITIVE_FIELD_RE` @ `:45`
- Adicionar query keys a `_SENSITIVE_QUERY_KEYS` @ `:50`

### Mudar limites de timeline
- Constantes `MAX_*` @ `:26-34`

---

## Anti-patterns

- **Nunca** armazenar payloads raw sem redação quando `store_raw_payloads=True` em produção
- **Nunca** confiar em `source="user"` para autenticação — é apenas uma flag
- **Nunca** bypassar o envelope — sempre normalizar eventos para `BrowserEventEnvelope`

---

## Dependências

- `infrastructure.persistence.models` — `BrowserCooperationEventORM`, `BrowserWorkspaceORM`
- Consumido por: `BrowserActionArbiter`, `BrowserWorkspaceService`
