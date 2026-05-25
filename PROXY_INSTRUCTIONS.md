# Claude Code + CommandCode Proxy — Guia Rapido

## O que voce precisa

1. **CommandCode CLI instalada e logada** (para ter a API key em `~/.commandcode/auth.json`)
2. **Claude Code instalado** (`claude --version`)
3. **Python 3** instalado

## Passo 1: Iniciar o Proxy

No terminal, navegue ate a pasta do projeto e execute:

```bash
cd /home/levybonito/Documentos/PersonAgent
./start-proxy.sh 8000
```

Ou diretamente com Python:

```bash
cd /home/levybonito/Documentos/PersonAgent
python3 claude-code-commandcode-proxy.py --port 8000
```

Voce vera uma mensagem como:

```
==========================================
  Claude Code <-> CommandCode Proxy
==========================================
Porta: 8000
...
```

**Deixe esse terminal rodando!**

## Passo 2: Configurar o Claude Code

Em um **NOVO terminal**, execute:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_AUTH_TOKEN=$(jq -r .apiKey ~/.commandcode/auth.json)
export ANTHROPIC_MODEL=claude-sonnet-4-6
```

## Passo 3: Usar o Claude Code

Ainda no novo terminal, execute:

```bash
# Modo interativo
claude

# Ou modo nao-interativo (print)
claude -p "Explique o que e um vector database"
```

## Mapeamento de Modelos

O proxy traduz os IDs Anthropic para IDs do CommandCode:

| Anthropic ID (usado no Claude Code) | Modelo real no CommandCode |
|-------------------------------------|---------------------------|
| `claude-sonnet-4-6` | `deepseek/deepseek-v4-pro` |
| `claude-opus-4-7` | `deepseek/deepseek-v4-pro` |
| `claude-haiku-4-5-20251001` | `deepseek/deepseek-v4-flash` |

Voce tambem pode usar diretamente qualquer modelo do CommandCode adicionando ao mapeamento no arquivo `claude-code-commandcode-proxy.py`.

## Teste rapido (sem Claude Code)

Para testar se o proxy funciona antes de abrir o Claude Code:

```bash
curl -s -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(jq -r .apiKey ~/.commandcode/auth.json)" \
  -d '{
    "model": "claude-sonnet-4-6",
    "max_tokens": 50,
    "messages": [{"role": "user", "content": "Say hello"}],
    "stream": false
  }'
```

## Variaveis de ambiente opcionais

```bash
# Desativar trafego nao-essencial (acelera o startup)
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Desativar hooks e prefetch (mais leve)
export CLAUDE_CODE_SIMPLE=1
```

## Problemas conhecidos

1. **Tool calls do Claude Code podem nao funcionar** — o proxy traduz o formato, mas o CommandCode rejeita tools no formato OpenAI. Use sem tools ou com `--bare`.

2. **Modelos Anthropic nao existem no CommandCode** — o proxy mapeia para DeepSeek, Kimi, etc.

3. **Stream e obrigatorio** — o `/alpha/generate` do CommandCode so funciona com streaming.

## Parar o Proxy

No terminal do proxy, pressione **Ctrl+C**.
