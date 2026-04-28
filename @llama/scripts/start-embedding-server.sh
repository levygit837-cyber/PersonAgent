#!/bin/bash
# Start a dedicated llama-server for operational memory embeddings.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_DIR="${SCRIPT_DIR}/../llama-cpp-turboquant"
BUILD_DIR="${LLAMA_DIR}/build"
LLAMA_SERVER="${BUILD_DIR}/bin/llama-server"

MODEL_PATH="${EMBEDDING_MODEL_PATH:-/home/levybonito/.lmstudio/models/Qwen/Qwen3-Embedding-8B-GGUF}"
PORT="${EMBEDDING_PORT:-8081}"
CTX_SIZE="${EMBEDDING_CTX_SIZE:-32768}"
N_GPU_LAYERS="${EMBEDDING_N_GPU_LAYERS:-999}"
THREADS="${EMBEDDING_THREADS:-6}"
PARALLEL="${EMBEDDING_PARALLEL:-1}"

if [ ! -f "${LLAMA_SERVER}" ]; then
    echo "llama-server not found at ${LLAMA_SERVER}"
    echo "Run first: ./@llama/scripts/build.sh"
    exit 1
fi

if [ -d "${MODEL_PATH}" ]; then
    GGUF_FILE=$(find "${MODEL_PATH}" -maxdepth 1 -name "*.gguf" ! -name "mmproj*" | head -n 1)
    if [ -z "${GGUF_FILE}" ]; then
        echo "No .gguf file found in ${MODEL_PATH}"
        exit 1
    fi
    MODEL_PATH="${GGUF_FILE}"
elif [ ! -f "${MODEL_PATH}" ]; then
    echo "Embedding model not found: ${MODEL_PATH}"
    exit 1
fi

echo "PersonAgent embedding server"
echo "Model: $(basename "${MODEL_PATH}")"
echo "Port: ${PORT}"
echo "Context: ${CTX_SIZE}"
echo "Parallel slots: ${PARALLEL}"

exec "${LLAMA_SERVER}" \
    -m "${MODEL_PATH}" \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --ctx-size "${CTX_SIZE}" \
    --n-gpu-layers "${N_GPU_LAYERS}" \
    --threads "${THREADS}" \
    --parallel "${PARALLEL}" \
    --embedding \
    --pooling last \
    "$@"
