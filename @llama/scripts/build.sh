#!/bin/bash
# ============================================================
# Script de build do llama.cpp com TurboQuant
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_DIR="${SCRIPT_DIR}/../llama-cpp-turboquant"
BUILD_DIR="${LLAMA_DIR}/build"

echo "🔧 PersonAgent — Compilando llama.cpp com TurboQuant + CUDA"
echo "============================================================"

# Verifica se o repositório existe
if [ ! -d "${LLAMA_DIR}" ]; then
    echo "❌ Repositório não encontrado em ${LLAMA_DIR}"
    echo "   Execute primeiro: git clone https://github.com/TheTom/llama-cpp-turboquant ${LLAMA_DIR}"
    exit 1
fi

# Muda para a branch correta
cd "${LLAMA_DIR}"
echo "📦 Branch atual: $(git branch --show-current 2>/dev/null || echo 'N/A')"

# Configura build com CUDA
echo ""
echo "⚙️  Configurando CMake..."
cmake -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_CUDA=ON \
    -DLLAMA_CURL=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF \
    ${CMAKE_EXTRA_ARGS}

# Compila
echo ""
echo "🔨 Compilando..."
cmake --build "${BUILD_DIR}" --config Release -j$(nproc)

echo ""
echo "✅ Build completo!"
echo ""
echo "📍 Binários disponíveis em: ${BUILD_DIR}/bin/"
echo "   - llama-server"
echo "   - llama-cli"
echo "   - llama-bench"
echo ""
echo "🚀 Para iniciar o servidor, execute:"
echo "   ./${BUILD_DIR}/bin/llama-server -m <modelo.gguf> --port 8080"
