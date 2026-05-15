# AI-Guide: Memory Jobs and Scheduler


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Agenda e executa jobs de memória em background via APScheduler: extração de memórias após turnos de chat e consolidação periódica (auto-dream) via cron.

---

## Entry Points

### `MemoryJobScheduler.initialize` @ `application/jobs/memory_job_scheduler.py:33`
```python
def initialize(self) -> None
```
- Cria instância de `AsyncIOScheduler`

### `MemoryJobScheduler.start` @ `:48`
```python
def start(self) -> None
```
- Inicia o scheduler; deve ser chamado após `initialize()`

### `MemoryJobScheduler.shutdown` @ `:55`
```python
def shutdown(self) -> None
```
- Para o scheduler graciosamente

### `MemoryJobScheduler.submit_job` @ `:61`
```python
async def submit_job(self, job: MemoryJob) -> str
```
- Submete job para execução imediata (fire-and-forget)
- Retorna ID do job
- Usado para jobs triggered por eventos (ex: após turno de chat)

### `MemoryJobScheduler.schedule_cron` @ `:86`
```python
def schedule_cron(
    self,
    job_type: JobType,
    cron_expr: str,
    timezone: str = "UTC",
    payload: dict[str, Any] | None = None,
) -> str
```
- Agenda job recorrente via expressão cron
- Retorna ID do job agendado
- Usado para auto-dream (diário às 3 AM)

### `MemoryJobScheduler.register_handler` @ `:38`
```python
def register_handler(self, job_type: JobType, handler: Any) -> None
```
- Registra handler para um tipo de job
- Handler é chamado em `_execute_job`

---

## Job Types

### `JobType` enum @ `application/jobs/memory_job.py`
- Valores típicos: `EXTRACT_MEMORIES`, `CONSOLIDATE`, `AUTO_DREAM`
- Definidos no arquivo de modelos de job

### `MemoryJob` @ `application/jobs/memory_job.py`
```python
@dataclass
class MemoryJob:
    id: str
    type: JobType
    conversation_id: str | None
    project_slug: str
    payload: dict[str, Any]
    status: str = "pending"     # pending | running | completed | failed
    result: Any | None = None
    error: str | None = None
```
- `mark_running()`, `mark_completed(result)`, `mark_failed(error)`

---

## Workers

### `ExtractMemoryWorker` @ `application/jobs/workers/extract_memory_worker.py`
- Executado após turnos de chat
- Extrai fatos relevantes da conversa
- Chama `OperationalMemoryService` para chunkar e indexar

### `ConsolidateMemoryWorker` @ `application/jobs/workers/consolidate_memory_worker.py`
- Executado periodicamente (cron)
- Consolida chunks de memória em items estruturados
- Remove duplicatas e atualiza embeddings

---

## Quando Modificar

### Adicionar novo tipo de job
1. Adicionar valor ao enum `JobType` em `memory_job.py`
2. Criar worker em `application/jobs/workers/`
3. Registrar handler no DIContainer lifespan
4. Adicionar teste

### Mudar frequência do auto-dream
- Modificar `cron_expr` passado para `schedule_cron()` no DIContainer
- Default: `0 3 * * *` (3 AM UTC)

### Mudar timezone
- Passar `timezone` para `schedule_cron()` (default `"UTC"`)

---

## Anti-patterns

- **Nunca** chamar `submit_job()` sem `initialize()` + `start()` primeiro — gera RuntimeError
- **Nunca** registrar handler que bloqueia — APScheduler é async
- **Nunca** esquecer de `shutdown()` no lifespan do FastAPI — pode deixar threads órfãs

---

## Dependências

- `apscheduler` — `AsyncIOScheduler`, `CronTrigger`
- `application.jobs.memory_job` — `JobType`, `MemoryJob`
- Consumido por: DIContainer lifespan (inicialização e registro de handlers)