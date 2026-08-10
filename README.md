<div align="center">

# PersonAgent

**Plataforma alpha de agente pessoal local, com backend FastAPI, cliente Electron/TUI, tools e memória operacional.**

*An experimental local-workspace agent platform for tool use, browser automation, operational memory and multi-agent coordination.*

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Electron](https://img.shields.io/badge/Electron-41-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Status](https://img.shields.io/badge/status-alpha-f59e0b)](#estado-atual)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

## Navegação rápida

[Produto](#o-que-o-projeto-explora) · [Implementação](#o-que-está-implementado) · [Arquitetura](#arquitetura) · [Execução](#rodar-localmente) · [Estado](#estado-atual) · [Guia para avaliadores](docs/reviewer-guide.md)

## O que o projeto explora

O PersonAgent reúne chat, execução de tools, automação de browser, memória e colaboração entre agentes
em superfícies desktop, terminal e API. A proposta é manter a operação local quando possível e usar
providers intercambiáveis para inferência.

É uma base alpha ampla e ativamente iterada. O repositório não está estabilizado e não deve ser
apresentado como produto pronto para produção.

## O que está implementado

- API FastAPI, CLI Typer e interface TUI com Textual;
- adapters para provedores de modelo locais e em nuvem;
- runtime de tools com limites de loop e orçamento para resultados;
- workspace de browser, sessões, snapshots e integrações Playwright/Lightpanda;
- memória operacional com extração, consolidação e recall;
- persistência assíncrona, Alembic, PostgreSQL e pgvector;
- team chat com coordenação, consenso, blackboard e síntese;
- tracing, QA, benchmarks e decisões arquiteturais registradas;
- cliente Electron/React com chat, terminal e estado local;
- alvos de empacotamento para macOS, Windows e Linux.

## Arquitetura

```text
Electron / React       CLI / TUI       API clients
        └──────────────┬──────────────────┘
                       ▼
                  FastAPI / adapters
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
 application       domain          infrastructure
 use cases          contracts       DB / LLM / browser
       │               │                │
       └───────────────┴────────────────┘
                       ▼
          PostgreSQL / pgvector / providers
```

```text
@backend/                 # Python, API, CLI/TUI, domínio e adapters
@desktop-electron/        # Electron, React, terminal e integração desktop
docs/                     # arquitetura, API, desenvolvimento e ADRs
benchmarks/               # cenários e harnesses experimentais
```

## Rodar localmente

Pré-requisitos: Python 3.11+, Node.js, Docker e ferramentas de compilação nativa.

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
docker compose up -d postgres

cd @backend
uv sync --extra dev
uv run alembic upgrade head
uv run personagent serve --port 8000 --reload
```

Em outro terminal:

```bash
cd @desktop-electron
npm install
npm run dev
```

Consulte o [guia do backend](@backend/README.md) para migrations, providers e dependências
opcionais.

## Estado atual

O pacote backend se classifica como **alpha**. Na auditoria limpa de 4 de agosto de 2026:

| Verificação | Resultado observado |
|---|---:|
| Compilação dos arquivos Python | passou |
| Backend unitário | 2.135 passaram, 65 falharam, 2 ignorados, 4 xfailed |
| Regressões Alembic + limite de tool loop | 20 passaram |
| Ruff em `src/` e `tests/` | 173 ocorrências |
| Typecheck do desktop | passou |
| Vitest do desktop | 989 passaram, 12 falharam |

O único workflow está em `.github/workflows-disabled`; portanto não existe CI ativo. Os números acima
descrevem o snapshot auditado e não são uma promessa permanente de contagem.

## Limites atuais

- refactors recentes deixaram testes backend e desktop vermelhos;
- o workflow desativado referencia caminhos antigos e não pode ser chamado de CI/CD ativo;
- integrações dependentes de PostgreSQL, pgvector, browsers e APIs reais não foram validadas como uma
  jornada única no snapshot;
- ADRs e benchmarks registram intenção e experimentos, não garantem que todo caminho esteja ligado;
- configuração multi-provider não significa que cada provider foi validado nesta versão;
- o projeto sobrepõe várias explorações e ainda precisa consolidar a experiência canônica.

## Documentação

- [Guia para avaliadores](docs/reviewer-guide.md)
- [Índice de ADRs](docs/adr/README.md)
- [Guia do backend](@backend/README.md)
- [Guias para agentes](docs/ai-guides/README.md)
- [Engenharia de contexto](docs/context-engineering/README.md)
- [Benchmarks](benchmarks/README.md)

## Desenvolvimento

Projeto dirigido e iterado com agentes de desenvolvimento, visíveis no histórico de commits e PRs.
O trabalho humano incluiu definição do produto, supervisão, revisão, integração e uso de testes e
benchmarks para orientar refactors. Isso não implica autoria manual exclusiva de cada linha.

## Licença

[MIT](LICENSE).
