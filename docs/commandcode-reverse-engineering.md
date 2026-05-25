# CommandCode API — Engenharia Reversa

> Data: 2026-05-25
> Versao da CLI analisada: command-code@0.27.0
> Pacote: /home/levybonito/.nvm/versions/node/v24.14.1/lib/node_modules/command-code/

---

## 1. Visao Geral

A CLI do CommandCode (commandcode.ai) e um bundle Node.js (dist/index.mjs) que se comunica com uma API REST propria. O objetivo desta engenharia reversa foi mapear os endpoints de inferencia de modelos para uso fora do harness oficial.

**Conclusao principal:** o endpoint /alpha/generate funciona no plano Go (basico) e permite acesso direto aos modelos sem o system prompt nem as ferramentas injetadas do CommandCode.

---

## 2. Infraestrutura da Instalacao

| Item | Caminho |
|------|---------|
| Binario | ~/.nvm/versions/node/v24.14.1/bin/commandcode |
| Bundle principal | ~/.nvm/versions/node/v24.14.1/lib/node_modules/command-code/dist/index.mjs |
| Arquivo de auth | ~/.commandcode/auth.json |
| Configuracao | ~/.commandcode/config.json |

O bundle e um ESM minificado de ~1.4MB (linha unica). Para analise, foi reformatado com Node.js.

---

## 3. Autenticacao

### 3.1 Fontes da API Key

A CLI busca a chave em ordem:

1. Variavel de ambiente: COMMAND_CODE_API_KEY
2. Arquivo de auth: ~/.commandcode/auth.json (campo apiKey)

### 3.2 Formato do auth.json

```json
{
  "apiKey": "user_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "userId": "uuid",
  "userName": "username",
  "keyName": "cli-2026-05-21T06-58-46",
  "authenticatedAt": "2026-05-21T06:58:48.509Z"
}
```

### 3.3 Header de Autorizacao

```
Authorization: Bearer <apiKey>
```

---

## 4. Base URLs

A funcao getApiBaseUrl() no bundle define:

| Modo | Condicao | URL |
|------|----------|-----|
| Sandbox | COMMANDCODE_SANDBOX=true + COMMANDCODE_API_URL | Valor da env |
| Local | --local na CLI | http://localhost:9090 |
| Staging | --staging na CLI | https://staging-api.commandcode.ai |
| Producao | Padrao | https://api.commandcode.ai |

---

## 5. Endpoints Mapeados

### 5.1 Endpoints Alpha (nativos da CLI)

| Metodo | Endpoint | Descricao | Plano Go |
|--------|----------|-----------|----------|
| GET | /alpha/whoami | Dados do usuario autenticado | 403 fora da CLI |
| POST | /alpha/generate | Inferencia principal | Funciona |
| POST | /alpha/agent/generate | Geracao de agentes | Nao testado |
| POST | /alpha/sandbox/start | Sandbox | Nao testado |
| POST | /alpha/sandbox/stream | Stream de sandbox | Nao testado |
| GET | /alpha/sandbox/status | Status sandbox | Nao testado |
| POST | /alpha/sandbox/stop | Parar sandbox | Nao testado |
| GET | /alpha/sandbox/sessions | Listar sessoes sandbox | Nao testado |
| POST | /alpha/share/create | Criar share | Nao testado |
| DELETE | /alpha/share/delete | Deletar share | Nao testado |
| GET | /alpha/billing/credits | Creditos | Nao testado |
| GET | /alpha/billing/subscriptions | Assinaturas | Nao testado |
| GET | /alpha/usage/summary | Uso | Nao testado |

### 5.2 Endpoints Provider (OpenAI-compatible)

| Metodo | Endpoint | Descricao | Plano Go |
|--------|----------|-----------|----------|
| POST | /provider/v1/chat/completions | Chat completions padrao | Bloqueado |
| GET | /provider/v1/models | Listar modelos | 403 fora da CLI |
| POST | /provider/v1/messages | Anthropic Messages shape | Bloqueado |

**Nota:** os endpoints /provider/v1/* exigem upgrade para Pro+. O bloqueio e server-side na API key, nao nos headers.

---

## 6. Inferencia — /alpha/generate

### 6.1 Payload Completo

```json
{
  "config": {
    "workingDir": "/caminho/atual",
    "date": "2026-05-25",
    "environment": "linux-x64, Python 3.12",
    "structure": [],
    "isGitRepo": false,
    "currentBranch": "",
    "mainBranch": "",
    "gitStatus": "",
    "recentCommits": []
  },
  "memory": "",
  "taste": "",
  "skills": "",
  "params": {
    "model": "deepseek/deepseek-v4-pro",
    "messages": [
      { "role": "user", "content": "Ola!" }
    ],
    "system": "Voce e um assistente neutro.",
    "max_tokens": 64000,
    "temperature": 0.3,
    "stream": true,
    "tools": []
  },
  "threadId": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 6.2 System Prompt Custom

O campo params.system sobrescreve completamente o system prompt do CommandCode. O evento start-step no streaming confirma que o prompt enviado ao modelo contem apenas o system + user message fornecidos.

### 6.3 Ferramentas (Tools)

Testes confirmaram:

- params.tools: [] -> nenhuma ferramenta e injetada no prompt
- O modelo nao tem acesso as ferramentas internas do CommandCode (Bash, Read, Glob, etc.)
- O servidor valida rigorosamente o schema de tools e rejeita formatos OpenAI padrao
- Os unicos tipos possivelmente aceitos sao web_search e web_fetch

---

## 7. Headers da Requisicao

Headers obrigatorios:

```
POST /alpha/generate HTTP/1.1
Host: api.commandcode.ai
Content-Type: application/json
Accept: application/json, text/event-stream
User-Agent: command-code/0.27.0
Authorization: Bearer <apiKey>
x-cli-environment: production
x-command-code-version: 0.27.0
```

**Importante:** o User-Agent e obrigatorio. Requisicoes sem ele (ou com User-Agent do urllib do Python) retornam 403 Forbidden.

---

## 8. Resposta Streaming

O /alpha/generate retorna um stream de JSON newline-delimited (nao e SSE padrao com data:).

### 8.1 Eventos do Stream

| Tipo | Descricao |
|------|-----------|
| start | Inicio da geracao |
| start-step | Inicio do step; contem request.body com o prompt final |
| text-delta | Chunk de texto gerado |
| reasoning-start | Inicio de reasoning tokens |
| reasoning-delta | Chunk de reasoning |
| reasoning-end | Fim de reasoning tokens |
| tool-call | Chamada de ferramenta |
| tool-result | Resultado de ferramenta |
| finish-step | Fim do step; contem usage, finishReason |
| finish | Fim do stream completo |
| provider-metadata | Metadados do provider (cost, routing) |
| error | Erro |

### 8.2 Estrutura de Usage

```json
{
  "inputTokens": 31,
  "outputTokens": 98,
  "inputTokenDetails": {
    "noCacheTokens": 114,
    "cacheReadTokens": 7424
  },
  "outputTokenDetails": {
    "textTokens": 88,
    "reasoningTokens": 10
  }
}
```

---

## 9. Modelos Disponiveis

| ID | Nome | Context Length |
|----|------|----------------|
| claude-sonnet-4-6 | Claude Sonnet 4.6 | 1.000.000 |
| claude-opus-4-7 | Claude Opus 4.7 | 1.000.000 |
| claude-haiku-4-5-20251001 | Claude Haiku 4.5 | 200.000 |
| gpt-5.5 | GPT-5.5 | 200.000 |
| gpt-5.4 | GPT-5.4 | 400.000 |
| gpt-5.3-codex | GPT-5.3 Codex | 400.000 |
| gpt-5.4-mini | GPT-5.4 Mini | 400.000 |
| moonshotai/Kimi-K2.6 | Kimi K2.6 | 256.000 |
| moonshotai/Kimi-K2.5 | Kimi K2.5 | 256.000 |
| zai-org/GLM-5.1 | GLM-5.1 | 200.000 |
| zai-org/GLM-5 | GLM-5 | 200.000 |
| MiniMaxAI/MiniMax-M2.7 | MiniMax M2.7 | 200.000 |
| MiniMaxAI/MiniMax-M2.5 | MiniMax M2.5 | 200.000 |
| deepseek/deepseek-v4-pro | DeepSeek V4 Pro | 1.000.000 |
| deepseek/deepseek-v4-flash | DeepSeek V4 Flash | 1.000.000 |
| Qwen/Qwen3.6-Max-Preview | Qwen 3.6 Max Preview | 200.000 |
| Qwen/Qwen3.6-Plus | Qwen 3.6 Plus | 200.000 |
| Qwen/Qwen3.7-Max | Qwen 3.7 Max | 1.000.000 |
| stepfun/Step-3.5-Flash | Step 3.5 Flash | 1.000.000 |
| google/gemini-3.5-flash | Gemini 3.5 Flash | 1.000.000 |
| google/gemini-3.1-flash-lite | Gemini 3.1 Flash Lite | 1.000.000 |

---

## 10. Limitacoes do Plano Go

| Recurso | Status |
|---------|--------|
| /alpha/generate | Funciona |
| /alpha/whoami | Pode dar 403 |
| /provider/v1/models | Pode dar 403 |
| /provider/v1/chat/completions | Bloqueado (upgrade_required) |
| /provider/v1/messages | Bloqueado |
| System prompt custom | Sobrescreve o do CommandCode |
| Ferramentas internas do CC | Nao injetadas |
| Tool calls custom (OpenAI shape) | Rejeitado pelo schema |

---

## 11. Headers Custom do CommandCode

| Header | Valor/Descricao |
|--------|-----------------|
| x-cli-environment | production, staging, etc. |
| x-command-code-version | Versao da CLI (ex: 0.27.0) |
| x-session-id | UUID da sessao |
| x-project-slug | Slug do projeto atual |
| x-taste-learning | true ou false |
| x-taste-usage | true ou false |
| x-system-prompt-breakdown | Metadados de prompt |
| x-cmd-zdr | 1 se CMD_ZDR=1 |
| x-oauth-token | Bearer <token> (Codex/Anthropic) |
| x-oauth-provider | anthropic, etc. |
| x-oss-primary-provider | Provider primario (env) |
| traceparent | OpenTelemetry trace ID |

---

## 12. Estrategia de Uso em Harness Custom

Para usar os modelos do CommandCode em um harness proprio com o plano Go:

1. Ler a API key de ~/.commandcode/auth.json ou COMMAND_CODE_API_KEY
2. Usar o endpoint POST https://api.commandcode.ai/alpha/generate
3. Enviar os headers obrigatorios (Authorization, User-Agent, x-cli-environment, x-command-code-version)
4. Construir o payload com config, params, threadId
5. Definir params.system para controlar o comportamento do modelo
6. Usar params.tools: [] para garantir que nao ha ferramentas injetadas
7. Consumir o stream como JSON newline-delimited
8. Extrair text-delta para texto e reasoning-delta para reasoning tokens

---

## 13. Proximos Passos

- [ ] Mapear o Claude Code para verificar se e possivel trocar os endpoints
- [ ] Criar um harness Python/Node reutilizavel e testado
- [ ] Adicionar suporte a multiplos turns (historico de conversa)
- [ ] Implementar parser robusto para o streaming JSON
- [ ] Adicionar retry logic para erros de rede

---

Documento gerado a partir da engenharia reversa do bundle command-code@0.27.0.

---

## 14. Claude Code Proxy Adapter

Foi desenvolvido um proxy adapter que permite usar o **Claude Code** (harness oficial da Anthropic) consumindo os modelos do **CommandCode**.

### 14.1 Como funciona

O Claude Code usa a Anthropic Messages API (`POST /v1/messages`). O proxy:
1. Recebe requisicoes no formato Anthropic Messages API
2. Converte para o formato CommandCode `/alpha/generate`
3. Converte o streaming de volta para SSE no formato Anthropic
4. Permite usar DeepSeek, Kimi, GLM, etc. no harness do Claude Code

### 14.2 Arquitetura

```
Claude Code -> POST /v1/messages (Anthropic format)
     |
     v
Proxy Adapter (localhost:8000)
     |
     v
POST /alpha/generate (CommandCode format)
     |
     v
api.commandcode.ai
```

### 14.3 Mapeamento de Modelos

| Anthropic ID | CommandCode ID |
|--------------|----------------|
| claude-sonnet-4-6 | deepseek/deepseek-v4-pro |
| claude-opus-4-7 | deepseek/deepseek-v4-pro |
| claude-haiku-4-5-20251001 | deepseek/deepseek-v4-flash |

### 14.4 Uso

```bash
# 1. Inicie o proxy
python claude-code-commandcode-proxy.py --port 8000

# 2. Em outro terminal, configure o Claude Code
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_AUTH_TOKEN=$(jq -r .apiKey ~/.commandcode/auth.json)
export ANTHROPIC_MODEL=claude-sonnet-4-6

# 3. Execute o Claude Code
claude
```

### 14.5 Traducoes Implementadas

**Requisicao Anthropic -> CommandCode:**
- `model` -> mapeado via tabela de modelos
- `messages` -> `params.messages`
- `system` -> `params.system`
- `max_tokens` -> `params.max_tokens`
- `temperature` -> `params.temperature`
- `tools` -> `params.tools` (com conversao de formato)
- `stream: true` -> `params.stream: true`

**Resposta CommandCode -> Anthropic SSE:**
- `start` -> `message_start` + `content_block_start`
- `text-delta` -> `content_block_delta` (text_delta)
- `reasoning-start/delta/end` -> `content_block_start/delta/stop` (thinking)
- `tool-call` -> `content_block_start` (tool_use)
- `finish-step` -> `message_delta` + `message_stop`
- `error` -> `error`

### 14.6 Limitacoes do Proxy

- Tool calls custom precisam de mapeamento adicional
- Alguns headers especificos da Anthropic (anthropic-beta) sao ignorados
- O proxy nao implementa todas as features da API Anthropic (batches, count_tokens)
- Funciona apenas com streaming (stream=true)

