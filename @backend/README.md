# @backend — PersonAgent Backend

Backend Python com **Arquitetura Clean** para o Sistema de Agente Pessoal.

## 🧱 Arquitetura Clean

```
src/personagent/
├── domain/                      💎 Independente de frameworks
│   ├── models/                  ← Entidades (Conversation, Message, Role)
│   ├── repositories/            ← Interfaces (Ports)
│   └── exceptions.py            ← Exceções de domínio
│
├── application/                 🧠 Casos de uso
│   ├── dto/                     ← Data Transfer Objects
│   ├── use_cases/               ← Orquestração de regras de negócio
│   └── ports/                   ← Interfaces dos serviços
│
├── infrastructure/              🔌 Adaptadores externos
│   ├── config/                  ← Settings (.env + YAML)
│   ├── llm/                     ← Adapter llama.cpp + Process Manager
│   └── persistence/             ← PostgreSQL + SQLAlchemy
│
└── interfaces/                  🖥️ Pontos de entrada
    ├── api/                     ← FastAPI + Rotas
    └── cli/                     ← Typer + Rich
```

## 🔌 Injeção de Dependências

O sistema usa um container DI simples em `interfaces/config/di_container.py`:

```python
container = get_container()
llm_backend = container.get_llm_backend()
process_manager = container.get_process_manager()
```

## 🗄️ Banco de Dados

- **PostgreSQL** com SQLAlchemy async
- Tabelas: `conversations`, `messages`
- Migrations em `infrastructure/persistence/migrations/`

## 📡 Streaming

O sistema suporta streaming de respostas com Server-Sent Events (SSE):
- Conteúdo da resposta
- Reasoning/thinking tokens
- Eventos de finalização

## 🧪 Desenvolvimento

```bash
# Instalar dependências
pip install -e ".[dev]"

# Rodar testes
pytest

# Formatar código
ruff check . --fix
ruff format .

# Type check
mypy src/personagent
```
