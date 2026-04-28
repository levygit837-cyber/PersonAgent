# 🤖 PersonAgent

Sistema de Agente Pessoal com **llama.cpp + TurboQuant** para inferência local de LLMs.

## 🏗️ Arquitetura Clean

```
PersonAgent/
├── @backend/                    ← Python + FastAPI (Arquitetura Clean)
│   ├── src/personagent/
│   │   ├── domain/              💎 Regras de negócio puras
│   │   ├── application/         🧠 Casos de uso / Orquestração
│   │   ├── infrastructure/      🔌 Adaptadores externos
│   │   └── interfaces/          🖥️ FastAPI + CLI
│   └── pyproject.toml
│
├── @llama/                      ← Fork llama.cpp + TurboQuant
│   ├── llama-cpp-turboquant/    🔥 Motor de inferência
│   ├── scripts/
│   │   ├── build.sh             ← Compila com CUDA + TurboQuant
│   │   ├── start-server.sh      ← Inicia llama-server
│   │   └── stop-server.sh       ← Encerra llama-server
│   └── models/                  ← Symlinks para GGUFs
│
├── @desktop-electron/           ← Electron + React desktop client (official desktop app)
│   ├── electron/                ← main/preload with isolated IPC
│   └── src/                     ← React renderer, shadcn-style UI, Chat
│
├── docker-compose.yml           ← PostgreSQL
├── config.yaml                  ← Configuração YAML
└── .env                         ← Variáveis de ambiente
```

## 🚀 Quick Start

### 1. Pré-requisitos

- **Python** 3.11+
- **Node.js** 20+ e **npm** (cliente desktop Electron)
- **PostgreSQL** (via Docker)
- **CUDA Toolkit** (para GPU NVIDIA)
- **cmake**, **build-essential**

### 2. Iniciar PostgreSQL

```bash
docker compose up -d postgres
```

### 3. Compilar llama.cpp com TurboQuant

```bash
cd @llama
./scripts/build.sh
```

### 4. Instalar dependências Python

```bash
cd @backend
pip install -e ".[dev]"
```

### 5. Iniciar o Sistema

```bash
# Via CLI
personagent chat -m "Olá, quem é você?"

# Via API Server
personagent serve --port 8000
```

## ⚡ TurboQuant

O **TurboQuant** é uma técnica de quantização extrema do KV Cache que:
- Reduz uso de memória em **~87%** (compressão 4.57x)
- Permite contextos enormes com pouca VRAM
- Tem perda de precisão próxima de zero

Configuração padrão no `config.yaml`:
```yaml
llm:
  cache_type_k: "turbo4"
  cache_type_v: "turbo4"
  ctx_size: 262144
```

## 📡 API Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/chat/completions` | Chat completion síncrono |
| POST | `/chat/completions/stream` | Chat completion com SSE streaming |
| GET | `/conversations` | Lista conversas |
| GET | `/conversations/{id}` | Detalhes da conversa |
| DELETE | `/conversations/{id}` | Remove conversa |
| GET | `/health` | Health check |

## 🛠️ Comandos CLI

```bash
# Chat interativo
personagent chat -m "Sua mensagem aqui"

# Com streaming e ocultar reasoning
personagent chat -m "Explique quantum computing" --no-think

# Verificar status do modelo
personagent model --status

# Listar conversas
personagent conversations-list

# Iniciar servidor API
personagent serve --port 8000 --reload
```

## 🖥️ Desktop Electron

O cliente desktop oficial fica em `@desktop-electron/`:

```bash
cd @desktop-electron
npm install
npm run dev
```

## 📁 Workspaces

- **`@backend/`** — Backend Python com Arquitetura Clean
- **`@llama/`** — Fork llama.cpp com TurboQuant

## 📝 Licença

MIT
