# 🤖 PersonAgent

> **Agente pessoal local-first com LLMs multi-provedor, memória persistente e automação de workspace — tudo rodando no seu desktop.**

PersonAgent é um sistema completo de agente de IA que unifica chat inteligente, automação de navegador, controle de workspace Git e memória contextual de longo prazo em uma única aplicação desktop. Projetado para privacidade (local-first) com fallback para provedores em nuvem.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0%2B-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Electron](https://img.shields.io/badge/Electron-41-47848F?logo=electron&logoColor=white)](https://electronjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## ✨ Funcionalidades Principais

- **🧠 Chat Multi-Provedor** — Troca dinâmica entre LLMs locais (llama.cpp + TurboQuant), NVIDIA NIM, Vertex AI, Kimi Coding, DeepSeek e OpenAI-compatible, com streaming em tempo real via SSE.
- **💾 Memória de Longo Prazo** — Sistema de memória estruturada (projetos) + operacional (runtime) com embeddings semânticos (pgvector) e recuperação contextual automática.
- **🌐 Browser Workspace** — Automação de navegador via CDP/LightPanda com cooperação human-in-the-loop: o agente navega, você aprova ações sensíveis.
- **🛠️ Sistema de Ferramentas (Tools)** — Runtime extensível com ferramentas para Git, filesystem, shell, browser e skills injetáveis dinamicamente.
- **👥 Team Mode** — Orquestração multi-agente onde múltiplos especialistas colaboram em uma única conversa com aprovação de planos.
- **📝 Plan Mode** — O agente propõe planos de ação passo-a-passo; cada ferramenta só executa com sua aprovação explícita.
- **💻 Desktop Nativo** — Aplicativo Electron com React 19, TypeScript, Tailwind CSS e estado gerenciado via Zustand.
- **🔌 CLI Profissional** — Interface de linha de comando completa com Typer e Rich para chat, servidor API e gerenciamento de conversas.
- **🔒 Segurança Local-First** — Autenticação local apenas, escaneamento de secrets (gitleaks), testes de segurança automatizados e sandbox de paths.

---

## 🏗️ Arquitetura

O projeto segue **Clean Architecture** com separação estrita de responsabilidades:

```
┌─────────────────────────────────────────────────────────────┐
│  Electron Desktop (React + TypeScript + Zustand)           │
│  └── Chat │ Session Panel │ Browser │ Git Workspace │ Skills│
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / SSE / WebSocket
┌──────────────────────▼──────────────────────────────────────┐
│  FastAPI Backend (Python 3.11+, async)                      │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐  │
│  │  Interfaces │ │ Application  │ │   Infrastructure     │  │
│  │  (API/CLI)  │ │ (Use Cases)  │ │ (DB, LLM, Browser)   │  │
│  └─────────────┘ └──────────────┘ └──────────────────────┘  │
│         ▲                ▲                    ▲              │
│         └────────────────┴────────────────────┘              │
│                        Domain (Modelos Puros)                │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  PostgreSQL + pgvector  │  llama.cpp/TurboQuant  │  Docker  │
└─────────────────────────────────────────────────────────────┘
```

**Princípios aplicados:**
- **Dependency Rule:** `Domain` não conhece frameworks; `Application` orquestra; `Infrastructure` adapta externo; `Interfaces` expõe HTTP/CLI.
- **Ports & Adapters:** Repositórios abstratos com implementações PostgreSQL; LLM providers intercambiáveis via adapter pattern.
- **Event-Driven:** SSE para invalidação de cache desktop; WebSocket para chat em tempo real.

---

## 🚀 Tecnologias

| Camada | Stack |
|--------|-------|
| **Backend** | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic, structlog, typer, rich |
| **Desktop** | Electron 41, React 19, TypeScript 5, Vite, Tailwind CSS, Radix UI, Zustand, TanStack Query |
| **LLM/IA** | llama.cpp (TurboQuant KV-cache), NVIDIA NIM, Vertex AI, Kimi Coding, DeepSeek, OpenAI-compatible |
| **Dados** | PostgreSQL 15, pgvector, embeddings locais (GGUF), operational memory semântica |
| **DevOps** | Docker Compose, GitHub Actions (CI/CD), gitleaks, pre-commit, ruff, mypy, pytest, vitest |
| **Browser** | Playwright, LightPanda/CDP, automação com aprovação human-in-the-loop |

---

## ⚡ Quick Start

> **Pré-requisitos:** Python 3.11+, Node.js 20+, Docker, cmake, build-essential

```bash
# 1. Clone e entre no repo
git clone https://github.com/levygit837-cyber/PersonAgent.git
cd PersonAgent

# 2. Prepare a configuração local (cópias dos templates versionados)
cp .env.example .env                        # ajuste POSTGRES_PASSWORD + chaves de LLM
cp docker-compose.yml.example docker-compose.yml

# 3. Inicie o PostgreSQL (pgvector)
docker compose up -d postgres

# 4. Backend
cd @backend
pip install -e ".[dev]"                     # ou: uv sync --extra dev
uv run alembic upgrade head                 # aplica as migrations versionadas
personagent serve --port 8000 --reload

# 5. Pre-commit hooks (uma vez por clone)
cd ..
@backend/.venv/bin/pre-commit install       # ou: uv run pre-commit install

# 6. Desktop (novo terminal)
cd @desktop-electron
npm install
npm run dev
```

Veja o [guia completo](docs/development/README.md) para build do llama.cpp e configuração de provedores.

### CI e qualidade local

- **CI** (`.github/workflows/ci.yml`): ruff + mypy (escopo das partes refatoradas) + pytest unitário + typecheck/vitest do desktop + gitleaks. Roda em todo PR contra `main`.
- **Pre-commit** (`.pre-commit-config.yaml`): trailing whitespace, EOF, check-yaml/toml, large files, merge-conflict markers, private-key detection, `ruff --fix` no `@backend/`, gitleaks.
- **Migrations**: `uv run alembic upgrade head` aplica `0001_baseline` + revisões futuras (ver `@backend/README.md`).

---

## 📊 Status do Projeto

| Aspecto | Status |
|---------|--------|
| **Fase** | Alpha — funcional, em evolução rápida |
| **Commits** | 45+ em 3 semanas |
| **Testes** | 20+ suites (pytest + vitest), CI ativo |
| **Documentação** | 21 ADRs, docs completos, API reference |
| **Qualidade** | ruff, mypy, pre-commit, gitleaks no CI |

---

## 🎓 Aprendizados Técnicos (Relevante para Júnior)

Este projeto foi construído do zero como exercício de consolidação de habilidades fullstack:

- **Arquitetura de Software:** Aplicação prática de Clean Architecture, Dependency Inversion e Ports & Adapters em código real (não teoria).
- **Async Python:** Uso intensivo de `async/await`, SQLAlchemy async, SSE streaming e gerenciamento de estado concorrente.
- **Integração LLM:** Abstração de múltiplos providers com parsing compatível OpenAI, retry com backoff, orquestração de tool-calling e streaming.
- **Desktop Development:** IPC seguro no Electron (contextIsolation + preload scripts), state management com Zustand, bundling com Vite.
- **DevOps & Qualidade:** Pipeline CI/CD completo, linting estrito, testes de segurança, documentação de decisões arquiteturais (ADRs).
- **Product Thinking:** Design de um produto real com preocupações de UX (Plan Mode, aprovações, memória contextual) e não apenas CRUD.

---

## 📚 Documentação Técnica

- [Visão Geral da Arquitetura](docs/architecture/overview.md)
- [API Reference](docs/api/README.md)
- [ADR Index — 21 Decisões Arquiteturais](docs/adr/README.md)
- [Guia de Desenvolvimento](docs/development/README.md)
- [Backend & LLM Providers](docs/backend/README.md)

---

## 📝 Licença

[MIT](LICENSE) © 2026 levygit837-cyber
