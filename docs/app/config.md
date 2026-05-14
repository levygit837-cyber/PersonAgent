# Configuração no PersonAgent

## Visão geral

A configuração é hierárquica: valores padrão -> arquivo YAML -> variáveis de ambiente -> argumentos de linha de comando.

## Arquivo de configuração

Local padrão: `~/.config/personagent/config.yaml` (ou `config.yaml` no projeto).

```yaml
llm:
  provider: llama
  model: local-model
  temperature: 0.7
  reasoning_level: medium
  reasoning_budget_tokens: 2048

llama:
  auto_start: true
  ctx_size: 262144
  cache_type_k: turbo4
  cache_type_v: turbo4

memory:
  auto_memory_enabled: true
  operational_memory_enabled: true

browser:
  auto_start: true
  cdp_url: ""

server:
  host: 127.0.0.1
  port: 8000
```

## Variáveis de ambiente

| Variável | Descrição |
|----------|-----------|
| `PERSONAGENT_LOCAL_AUTH_TOKEN` | Token de autenticação |
| `DATABASE_URL` | PostgreSQL connection string |
| `LLAMA_MODEL_PATH` | Caminho do modelo GGUF |
| `LLAMA_BINARY_PATH` | Caminho do llama-server |
| `PERSONAGENT_ARTIFACT_ROOT` | Diretório de artefatos |

## Configuração no Desktop

A tela de configurações no Electron permite editar:
- Provider e modelo
- Temperatura e tokens
- Memória (on/off)
- Browser runtime
- Tema (claro/escuro)

## Hot reload

Mudanças em `config.yaml` exigem restart do backend para ter efeito (não há hot reload).

## Referências

- `@backend/src/personagent/infrastructure/config/settings.py`
