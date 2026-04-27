# @llama — llama.cpp + TurboQuant

Fork não-oficial do llama.cpp com suporte ao **TurboQuant** para compressão extrema do KV Cache.

## 📦 Repositório

- **Fork**: `TheTom/llama-cpp-turboquant`
- **Branch**: `feature/turboquant-kv-cache`
- **Original**: Baseado no PR #21131 do ggml-org/llama.cpp

## ⚡ TurboQuant

O TurboQuant é uma técnica de quantização do KV Cache para **3.5 bits** que:
- Alcança compressão de **4.57x**
- Reduz memória em ~87%
- Aumenta velocidade em ~6% (menor largura de banda)
- Perda de precisão próxima de zero

## 🔨 Build

```bash
./scripts/build.sh
```

Isso compila o llama.cpp com:
- CUDA support (`-DGGML_CUDA=ON`)
- CURL para downloads (`-DLLAMA_CURL=ON`)
- TurboQuant KV Cache

## 🚀 Iniciar Servidor

```bash
# Automático (com configurações do config.yaml)
./scripts/start-server.sh

# Ou manualmente
./llama-cpp-turboquant/build/bin/llama-server \
  -m /caminho/para/modelo.gguf \
  --port 8080 \
  --ctx-size 262144 \
  --cache-type-k turbo4 \
  --cache-type-v turbo4 \
  --n-gpu-layers 999 \
  --jinja
```

## 🛑 Encerrar

```bash
./scripts/stop-server.sh
```

## 📝 Flags Importantes

| Flag | Descrição | Padrão |
|------|-----------|--------|
| `--cache-type-k` | Tipo de quantização do cache K | `turbo4` |
| `--cache-type-v` | Tipo de quantização do cache V | `turbo4` |
| `--ctx-size` | Tamanho do contexto | `262144` |
| `--n-gpu-layers` | Camadas na GPU | `999` (todas) |
| `--jinja` | Suporte a templates Jinja | — |

## 🖥️ Hardware Recomendado

- **GPU**: NVIDIA com CUDA (RTX 4060+ ideal)
- **VRAM**: 8GB+ (modelo 4B Q4 ≈ 2.5GB + KV Cache com TurboQuant ≈ 3.5MB)
- **RAM**: 16GB+
