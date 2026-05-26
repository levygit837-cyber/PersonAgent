"""Constants for NVIDIA NIM adapter."""

from __future__ import annotations

DEFAULT_OUTPUT_TOKENS = 65536
MAX_REASONING_BUDGET_TOKENS = 32768
MIN_REASONING_MAX_TOKENS = 4096
FINAL_RESPONSE_TOKEN_RESERVE = 2048
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 0.0
STREAM_CONNECT_TIMEOUT_SECONDS = 30.0
STREAM_POOL_TIMEOUT_SECONDS = 30.0

KNOWN_REASONING_CHAT_MODELS = {
    # DeepSeek models
    "deepseek-ai/deepseek-v4-flash",
    "deepseek-ai/deepseek-v4-pro",
    # NVIDIA Nemotron models
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/llama-3.1-nemotron-51b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/nemotron-4-340b-reward",
    "nvidia/nemotron-nano-3-30b-a3b",
    "nvidia/nvidia-nemotron-nano-9b-v2",
    # Moonshot AI Kimi K2 models
    "moonshotai/kimi-k2.6",
    # Mistral models
    "mistralai/mistral-large-3-675b-instruct-2512",
    "mistralai/mistral-large-2-instruct",
    "mistralai/mistral-large",
    "mistralai/mistral-medium-3.5-128b",
    "mistralai/mistral-small-4-119b-2603",
    # Meta Llama
    "meta/llama-3.1-405b-instruct",
    "meta/llama-4-maverick-17b-128e-instruct",
    # Qwen large models (480B+)
    "qwen/qwen3-coder-480b-a35b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3-next-80b-a3b-thinking",
    # OpenAI OSS models
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    # ByteDance
    "bytedance/seed-oss-36b-instruct",
    # Zhipu AI (GLM)
    "z-ai/glm-5.1",
    "z-ai/glm5",
    # Stepfun
    "stepfun-ai/step-3.5-flash",
}

THINKING_TEMPLATE_KWARGS_MODELS = {
    "deepseek-ai/deepseek-v4-flash",
    "deepseek-ai/deepseek-v4-pro",
    "nvidia/nemotron-3-nano-30b-a3b",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3.5-122b-a10b",
    "qwen/qwen3-next-80b-a3b-thinking",
}
