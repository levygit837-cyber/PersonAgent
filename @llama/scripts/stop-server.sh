#!/bin/bash
# ============================================================
# Script para encerrar o llama-server
# ============================================================

echo "🛑 PersonAgent — Encerrando llama-server..."

# Procura processos do llama-server
PIDS=$(pgrep -f "llama-server" || true)

if [ -z "${PIDS}" ]; then
    echo "ℹ️  Nenhum processo llama-server encontrado"
    exit 0
fi

# Encerra processos
echo "   Processos encontrados: ${PIDS}"
kill -TERM ${PIDS} 2>/dev/null || true

sleep 2

# Força kill se ainda estiver rodando
REMAINING=$(pgrep -f "llama-server" || true)
if [ -n "${REMAINING}" ]; then
    echo "   Forçando encerramento..."
    kill -KILL ${REMAINING} 2>/dev/null || true
fi

echo "✅ llama-server encerrado"
