#!/bin/bash
# ============================================================
# Script para iniciar o llama-server com TurboQuant
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/../.."

# Carrega configurações do .env ou config.yaml
MODEL_PATH="${LLAMA_MODEL_PATH:-/home/levybonito/.lmstudio/models/Jackrong/Qwen3.5-4B-Reasoning-Distilled-v2-GGUF}"
LLAMA_DIR="${SCRIPT_DIR}/../llama-cpp-turboquant"
BUILD_DIR="${LLAMA_DIR}/build"
LLAMA_SERVER="${BUILD_DIR}/bin/llama-server"

# RTX 4060 = 8GB VRAM, modelo 4B Q4 ≈ 2.5GB
CTX_SIZE="${LLAMA_CTX_SIZE:-131072}"
N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-999}"
TEMP="${LLAMA_TEMPERATURE:-0.7}"
CACHE_TYPE_K="${LLAMA_CACHE_TYPE_K:-turbo4}"
CACHE_TYPE_V="${LLAMA_CACHE_TYPE_V:-turbo4}"
THREADS="${LLAMA_THREADS:-6}"

echo "🚀 PersonAgent — Iniciando llama-server com TurboQuant"
echo "============================================================"

# Verifica binário
if [ ! -f "${LLAMA_SERVER}" ]; then
    echo "❌ llama-server não encontrado em ${LLAMA_SERVER}"
    echo "   Execute primeiro: ./scripts/build.sh"
    exit 1
fi

# Procura modelo GGUF (exclui mmproj)
if [ -d "${MODEL_PATH}" ]; then
    GGUF_FILE=$(find "${MODEL_PATH}" -maxdepth 1 -name "*.gguf" ! -name "mmproj*" | head -n 1)
    if [ -z "${GGUF_FILE}" ]; then
        echo "❌ Nenhum arquivo .gguf encontrado em ${MODEL_PATH}"
        exit 1
    fi
    MODEL_PATH="${GGUF_FILE}"
elif [ ! -f "${MODEL_PATH}" ]; then
    echo "❌ Modelo não encontrado: ${MODEL_PATH}"
    exit 1
fi

echo "📦 Modelo: $(basename "${MODEL_PATH}")"
echo "📐 Contexto: ${CTX_SIZE} tokens"
echo "🧠 GPU Layers: ${N_GPU_LAYERS}"
echo "⚡ TurboQuant: K=${CACHE_TYPE_K}, V=${CACHE_TYPE_V}"
echo "🌡️  Temperatura: ${TEMP}"
echo "🖥️  Threads: ${THREADS}"
echo ""
echo "Pressione Ctrl+C para encerrar"
echo "============================================================"

exec "${LLAMA_SERVER}" \
    -m "${MODEL_PATH}" \
    --host 0.0.0.0 \
    --port 8080 \
    --ctx-size "${CTX_SIZE}" \
    --n-gpu-layers "${N_GPU_LAYERS}" \
    --threads "${THREADS}" \
    --temp "${TEMP}" \
    --cache-type-k "${CACHE_TYPE_K}" \
    --cache-type-v "${CACHE_TYPE_V}" \
    --jinja \
    --verbose \
    "$@"
