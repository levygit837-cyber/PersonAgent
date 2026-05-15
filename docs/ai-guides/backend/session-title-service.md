# AI-Guide: Session Title Service

## Propósito

Gera, verifica e deduplica títulos de conversas usando LLM em batches. Mantém títulos curtos, únicos e cacheáveis por hash de histórico.

---

## Entry Points

### `SessionTitleService.refresh_title` @ `application/services/session_titles.py:185`
```python
async def refresh_title(
    self,
    repo: ConversationRepository,
    conversation: Conversation,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> SessionTitleResult
```
- Refresh de título para uma única conversa, com deduplicação contra todas as sessões existentes.

### `SessionTitleService.verify_all` @ `application/services/session_titles.py:209`
```python
async def verify_all(
    self,
    repo: ConversationRepository,
    *,
    limit: int | None = None,
    offset: int = 0,
    batch_size: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> SessionTitleBatchResult
```
- Verifica títulos em batch para múltiplas conversas.

### `SessionTitleService.maybe_repair_duplicate_titles` @ `application/services/session_titles.py:327`
```python
async def maybe_repair_duplicate_titles(
    self,
    repo: ConversationRepository,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> SessionTitleBatchResult
```
- Roda periodicamente (a cada `duplicate_check_interval_seconds`) para reparar títulos duplicados.

---

## Pipeline de Geração

```
refresh_conversations(conversations)
├── Para cada conversation:
│   ├── history_hash = SHA256(messages) → cache key
│   ├── cached_title? → usar cache (source="cache")
│   ├── sem mensagens? → fallback_title (source="deterministic")
│   └── senão → adiciona ao batch LLM
├── Gera títulos via LLM para o batch (max 6 por batch)
│   ├── Primary provider → se falhar → Fallback provider
│   └── Se batch falhar → split em singles
├── Aplica uniquenesssuffix para evitar duplicatas
└── Persiste no repo + metadata
```

---

## Constantes Críticas

| Constante | Valor | Linha | Significado |
|-----------|-------|-------|-------------|
| `DEFAULT_BATCH_SIZE` | `6` | `:31` | Conversas por chamada LLM |
| `DEFAULT_SCAN_LIMIT` | `10_000` | `:32` | Máximo de sessões a verificar |
| `DEFAULT_MAX_HISTORY_CHARS` | `180_000` | `:33` | Budget de histórico para o prompt |
| `DEFAULT_SIMILARITY_THRESHOLD` | `0.9` | `:35` | Ratio do SequenceMatcher para considerar duplicata |
| `MAX_TITLE_CHARS` | `72` | `:36` | Limite de caracteres por título |
| `MAX_TITLE_WORDS` | `9` | `:37` | Limite de palavras por título |
| `DEFAULT_DUPLICATE_CHECK_INTERVAL_SECONDS` | `300.0` | `:34` | Cooldown entre verificações de duplicata |

---

## Classes e Tipos

### `SessionTitleResult` @ `:70`
```python
@dataclass(slots=True)
class SessionTitleResult:
    conversation_id: str
    old_title: str
    new_title: str
    status: str           # "updated" | "cached" | "skipped" | "failed"
    source: str           # "llm" | "llm_fallback" | "cache" | "deterministic"
    history_hash: str
    reason: str = ""
```

### `SessionTitleBatchResult` @ `:94`
```python
@dataclass(slots=True)
class SessionTitleBatchResult:
    checked: int = 0
    analyzed: int = 0
    updated: int = 0
    cached: int = 0
    skipped: int = 0
    failed: int = 0
    batches: int = 0
    duplicate_groups: int = 0
    primary_model: str = ""
    fallback_model: str = ""
    results: list[SessionTitleResult] = []
```

### `_TitleUniqueness` @ `:725` (classe privada)
- Mantém `set` de títulos normalizados
- `accepts(title)` → retorna `False` se normalizado já existe ou similarity ≥ threshold
- `add(title)` → registra título

---

## Métodos Privados de Lógica

### `_history_hash` @ `:703`
- SHA256 concatenando `role + "\0" + content + "\0" + tool_calls + "\0" + tool_call_id + "\0"` de cada mensagem
- Determina se o cache é válido

### `_cached_title` @ `:601`
- Lê metadata `conversation.metadata["session_title_analysis"]`
- Valida versão do cache (`SESSION_TITLE_CACHE_VERSION = 1`)
- Valida `history_hash` match

### `_generate_titles_for_batch` @ `:377`
- Monta payload JSON com `existing_titles` e `sessions` (id, current_title, message_count, history)
- Chama LLM com `_TITLE_SYSTEM_PROMPT` @ `:835`
- Retry com fallback provider
- Se batch falhar → split em singles recursivamente

### `_unique_title` @ `:614`
1. Sanitiza e verifica se é genérico → fallback
2. Tenta `uniqueness.accepts(title)`
3. Se rejeitado: tenta suffixes em ordem: distinctive keywords → date suffix → UUID prefix → UUID truncado

### `_fallback_title` @ `:644`
- Última mensagem USER não vazia, truncada a `MAX_TITLE_WORDS`
- Se vazio → `Session {uuid_prefix}`

---

## Prompt de Título

`_TITLE_SYSTEM_PROMPT` @ `:835`
- Instrui LLM a gerar títulos curtos em inglês (< 9 palavras, < 72 chars)
- Evita títulos genéricos ("New Chat", "Test", "Session")
- Requer JSON: `{"titles":[{"id":"...","title":"..."}]}`

---

## Quando Modificar

### Mudar prompt de título
- Editar `_TITLE_SYSTEM_PROMPT` @ `:835`
- Ajustar `MAX_TITLE_WORDS` / `MAX_TITLE_CHARS` se necessário

### Suportar novos idiomas
- O prompt atual força inglês ("Produce ... in English"). Remover essa linha para suportar idioma do histórico.
- Ajustar `_STOPWORDS` @ `:49` para incluir stopwords do novo idioma.

### Ajustar deduplicação
- Modificar `DEFAULT_SIMILARITY_THRESHOLD` @ `:35` (0.0-1.0)
- Ajustar `_TitleUniqueness.accepts()` se quiser algoritmo diferente de SequenceMatcher

### Mudar provider/model de geração
- Constantes: `DEFAULT_PRIMARY_PROVIDER`, `DEFAULT_PRIMARY_MODEL`, `DEFAULT_FALLBACK_*` @ `:27-30`
- Ou passar via construtor

---

## Anti-patterns

- **Nunca** gerar título sem passar por `_unique_title()` — duplicatas poluem a UI.
- **Nunca** confiar em `conversation.title` diretamente; sempre verificar cache.
- **Nunca** chamar `verify_all()` com `force=True` em produção sem dry_run primeiro — gera N chamadas LLM.

---

## Dependências

- `domain.models.conversation` — `Conversation`, `Message`, `Role`
- `domain.repositories.conversation_repository` — `ConversationRepository`
- `domain.repositories.llm_backend_repository` — `LLMBackendRepository`
- Consumido por: chat completion use case (após primeira mensagem do usuário)
