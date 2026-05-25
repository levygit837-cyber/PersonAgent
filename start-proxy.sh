#!/bin/bash
# =============================================================================
# Claude Code <-> CommandCode Proxy Launcher
# Modelo padrao: DeepSeek V4 Pro (via CommandCode)
# =============================================================================

set -euo pipefail

PORT="${1:-8000}"
API_KEY="${COMMAND_CODE_API_KEY:-}"

# --- Descobrir API Key ---
if [ -z "$API_KEY" ]; then
    AUTH_FILE="$HOME/.commandcode/auth.json"
    if [ -f "$AUTH_FILE" ]; then
        if command -v jq &>/dev/null; then
            API_KEY=$(jq -r '.apiKey // empty' "$AUTH_FILE" 2>/dev/null)
        else
            API_KEY=$(python3 -c "import json,sys; d=json.load(open('$AUTH_FILE')); print(d.get('apiKey',''))" 2>/dev/null)
        fi
    fi
fi

if [ -z "$API_KEY" ]; then
    echo "=========================================="
    echo "  ERRO: API Key do CommandCode nao encontrada"
    echo "=========================================="
    echo ""
    echo "Configure uma das opcoes:"
    echo "  1. export COMMAND_CODE_API_KEY=<sua_key>"
    echo "  2. Faca login na CLI: cmd login"
    echo ""
    exit 1
fi

# --- Verificar se a porta esta livre ---
if command -v lsof &>/dev/null; then
    if lsof -Pi :"$PORT" -sTCP:LISTEN -t &>/dev/null; then
        echo "ERRO: Porta $PORT ja esta em uso!"
        echo "Outro proxy ja esta rodando ou outro processo esta usando a porta."
        exit 1
    fi
fi

# --- Iniciar proxy em background ---
PROXY_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/commandcode-proxy.log"

echo "=========================================="
echo "  Claude Code <-> CommandCode Proxy"
echo "=========================================="
echo "Porta:        $PORT"
echo "API Key:      ${API_KEY:0:20}..."
echo "Modelo real:  DeepSeek V4 Pro (via CommandCode)"
echo "Alias Claude: claude-sonnet-4-6"
echo "Log file:     $LOG_FILE"
echo "=========================================="
echo ""

# Limpar log anterior
> "$LOG_FILE"

nohup python3 "$PROXY_DIR/claude-code-commandcode-proxy.py" --port "$PORT" > "$LOG_FILE" 2>&1 &
PROXY_PID=$!

# Aguardar proxy iniciar
sleep 2

# Verificar se iniciou
if ! kill -0 "$PROXY_PID" 2>/dev/null; then
    echo "ERRO: O proxy nao iniciou! Verifique o log:"
    tail -n 20 "$LOG_FILE"
    exit 1
fi

echo "✓ Proxy iniciado (PID: $PROXY_PID)"
echo ""
echo "=========================================="
echo "  VARIAVEIS DE AMBIENTE PARA O CLAUDE"
echo "=========================================="
echo ""
echo "Execute ESTES comandos no terminal onde"
echo "voce vai rodar o Claude Code:"
echo ""
echo "  export ANTHROPIC_BASE_URL=http://localhost:$PORT"
echo "  export ANTHROPIC_AUTH_TOKEN=$API_KEY"
echo ""
echo "Escolha o modelo (todos funcionam via CommandCode):"
echo "  export ANTHROPIC_MODEL=deepseek-v4-pro          # DeepSeek V4 Pro (PADRAO)"
echo "  export ANTHROPIC_MODEL=deepseek-v4-flash        # DeepSeek V4 Flash"
echo "  export ANTHROPIC_MODEL=kimi-k2.5                # Kimi K2.5"
echo "  export ANTHROPIC_MODEL=kimi-k2.6                # Kimi K2.6"
echo "  export ANTHROPIC_MODEL=qwen-3.7-max             # Qwen 3.7 Max"
echo "  export ANTHROPIC_MODEL=glm-5.1                  # GLM 5.1"
echo "  export ANTHROPIC_MODEL=minimax-m2.7             # MiniMax M2.7"
echo "  export ANTHROPIC_MODEL=claude-sonnet-4-6        # Alias -> DeepSeek V4 Pro"
echo ""
echo "  claude"
echo ""
echo "=========================================="
echo ""
echo "Para parar o proxy:"
echo "  kill $PROXY_PID"
echo ""
echo "Para ver logs em tempo real:"
echo "  tail -f $LOG_FILE"
echo ""
echo "Para testar se esta funcionando:"
echo "  curl http://localhost:$PORT/health"
echo "=========================================="
