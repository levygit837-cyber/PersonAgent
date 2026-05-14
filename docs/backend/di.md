# Dependency Injection no PersonAgent

## Visão geral

O PersonAgent usa um **container DI manual** (`DIContainer`) em vez de um framework externo. Isso mantém o wiring explícito, greppável e sem dependências de biblioteca.

## Localização

`@backend/src/personagent/interfaces/config/di_container.py`

## Padrão

```python
class DIContainer:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm_backends: dict[str, LLMBackendRepository] = {}

    def get_llm_backend(self, provider: str = "llama") -> LLMBackendRepository:
        if provider not in self._llm_backends:
            self._llm_backends[provider] = self._create_backend(provider)
        return self._llm_backends[provider]

    async def close_llm_backends(self) -> None:
        for backend in self._llm_backends.values():
            await backend.close()
        self._llm_backends.clear()
```

## Singleton vs Factory

| Tipo | Método | Uso |
|------|--------|-----|
| **Singleton** | `get_*()` | Settings, LLM backends, process managers |
| **Factory** | `create_*()` | Use cases, services que precisam de `AsyncSession` |

## Reset em testes

```python
from personagent.interfaces.config.di_container import reset_container

@pytest.fixture(autouse=True)
def reset_di():
    reset_container()
```

## Lifespan

O `lifespan()` (em `interfaces/api/main.py`) inicializa o container, banco, llama-server e memory scheduler:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    container = get_container()
    await init_db()
    if container.settings.llama_auto_start:
        await container.get_process_manager().start()
    yield
    # shutdown
```

## Adicionando um novo serviço

1. Declare o campo privado no `__init__` do `DIContainer`.
2. Adicione o getter/factory.
3. Registre no shutdown se necessário.
4. Documente no caso de uso ou rota que o consome.

## Referências

- ADR 0006: Manual DI Container
