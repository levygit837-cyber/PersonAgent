"""Shared fixtures and gating for live-backend stress tests.

Environment variables:
    STRESS_LIVE_TESTS=1         — master switch for all live stress tests
    STRESS_LIVE_PROVIDER        — provider to use: nvidia, vertex, kimi, deepseek, codex, llama (default: auto-detect)
    STRESS_LIVE_MODEL           — override model ID (optional)
    STRESS_LIVE_TIMEOUT         — per-test timeout in seconds (default: 30)
    STRESS_LIVE_CONCURRENCY     — max concurrent requests (default: 5)
    STRESS_LIVE_ITERATIONS      — repetitions per benchmark (default: 10)

Provider-specific (follows existing integration test patterns):
    NVIDIA_API_KEY              — for NVIDIA NIM
    GOOGLE_API_KEY              — for Vertex AI
    KIMI_API_KEY                — for Kimi Coding
    DEEPSEEK_API_KEY            — for DeepSeek
    CODEX_HOME / codex CLI      — for Codex Subscription
    LLAMA_BASE_URL              — for local llama.cpp (default: http://localhost:8080/v1)
    EMBEDDING_SERVER_URL        — for real embedding server (default: http://localhost:8081/v1)
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dotenv import load_dotenv

from personagent.domain.llm_backend.repositories import LLMBackendRepository

PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")


def live_enabled() -> bool:
    """Master gate: STRESS_LIVE_TESTS=1 must be set."""
    return os.getenv("STRESS_LIVE_TESTS") == "1"


def provider_available(provider: str) -> bool:
    """Check if a specific provider has its credentials configured."""
    if not live_enabled():
        return False
    checks = {
        "nvidia": lambda: bool(os.getenv("NVIDIA_API_KEY")),
        "vertex": lambda: bool(os.getenv("GOOGLE_API_KEY")),
        "kimi": lambda: bool(os.getenv("KIMI_API_KEY")),
        "deepseek": lambda: bool(os.getenv("DEEPSEEK_API_KEY")),
        "codex": lambda: Path(os.path.expanduser("~/.codex/auth.json")).exists(),
        "llama": lambda: True,  # local server, always "available" if enabled
    }
    return checks.get(provider, lambda: False)()


def requested_provider() -> str | None:
    """Return the explicitly requested provider, or None for auto-detect."""
    return os.getenv("STRESS_LIVE_PROVIDER")


def requested_model() -> str | None:
    """Return the explicitly requested model, or None for provider default."""
    return os.getenv("STRESS_LIVE_MODEL")


def live_timeout() -> float:
    return float(os.getenv("STRESS_LIVE_TIMEOUT", "30"))


def live_concurrency() -> int:
    return int(os.getenv("STRESS_LIVE_CONCURRENCY", "5"))


def live_iterations() -> int:
    return int(os.getenv("STRESS_LIVE_ITERATIONS", "10"))


skip_reason = "Set STRESS_LIVE_TESTS=1 and provider API key"


def _build_nvidia(**overrides):
    from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
    return NvidiaNimAdapter(
        api_key=os.environ["NVIDIA_API_KEY"],
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        default_max_tokens=512,
        timeout=live_timeout(),
        **overrides,
    )


def _build_vertex(**overrides):
    from personagent.infrastructure.llm.vertex_ai import VertexAiAdapter
    return VertexAiAdapter(
        api_key=os.environ["GOOGLE_API_KEY"],
        auth_mode=os.getenv("VERTEX_AUTH_MODE", "auto"),
        project_id=os.getenv("VERTEX_PROJECT_ID", ""),
        location=os.getenv("VERTEX_LOCATION", "global"),
        default_model=requested_model() or os.getenv("VERTEX_DEFAULT_MODEL", "gemini-3.1-flash-lite-preview"),
        default_max_tokens=512,
        timeout=live_timeout(),
        **overrides,
    )


def _build_kimi(**overrides):
    from personagent.infrastructure.llm.kimi.coding_adapter import KimiCodingAdapter
    return KimiCodingAdapter(
        api_key=os.environ["KIMI_API_KEY"],
        base_url=os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1"),
        default_model=requested_model() or os.getenv("KIMI_DEFAULT_MODEL", "kimi-for-coding"),
        default_max_tokens=4096,
        timeout=live_timeout(),
        **overrides,
    )


def _build_deepseek(**overrides):
    from personagent.infrastructure.llm.deepseek_adapter import DeepSeekAdapter
    return DeepSeekAdapter(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        default_model=requested_model() or os.getenv("DEEPSEEK_DEFAULT_MODEL", "deepseek-v4-flash"),
        default_max_tokens=4096,
        timeout=live_timeout(),
        **overrides,
    )


def _build_codex(**overrides):
    from personagent.infrastructure.llm.codex.subscription_adapter import CodexSubscriptionAdapter
    return CodexSubscriptionAdapter(
        default_model=requested_model() or os.getenv("CODEX_DEFAULT_MODEL", "gpt-5.5"),
        default_max_tokens=4096,
        timeout=live_timeout(),
        **overrides,
    )


def _build_llama(**overrides):
    from personagent.infrastructure.llm.llama_cpp_adapter import LlamaCppAdapter
    return LlamaCppAdapter(
        base_url=os.getenv("LLAMA_BASE_URL", "http://localhost:8080/v1"),
        default_max_tokens=512,
        timeout=live_timeout(),
        **overrides,
    )


PROVIDER_BUILDERS = {
    "nvidia": _build_nvidia,
    "vertex": _build_vertex,
    "kimi": _build_kimi,
    "deepseek": _build_deepseek,
    "codex": _build_codex,
    "llama": _build_llama,
}


def build_adapter(provider: str | None = None) -> LLMBackendRepository:
    """Build an LLM adapter for the given or auto-detected provider."""
    if provider is None:
        provider = requested_provider()
    if provider is None:
        # Auto-detect: first available
        for name, builder in PROVIDER_BUILDERS.items():
            if provider_available(name):
                return builder()
        pytest.skip("No provider available. Set STRESS_LIVE_PROVIDER and API key.")

    if provider not in PROVIDER_BUILDERS:
        pytest.fail(f"Unknown provider: {provider}. Use: {list(PROVIDER_BUILDERS.keys())}")
    if not provider_available(provider):
        pytest.skip(f"{provider} not configured. Set the appropriate API key.")

    return PROVIDER_BUILDERS[provider]()


@pytest.fixture
def live_adapter() -> LLMBackendRepository:
    """Fixture that provides a live LLM adapter (auto-detects provider)."""
    adapter = build_adapter()
    yield adapter
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(adapter.close())
    except RuntimeError:
        pass


@pytest.fixture
def embedding_adapter():
    """Fixture for the real embedding server (if available)."""
    if not live_enabled():
        pytest.skip("STRESS_LIVE_TESTS not set")
    from personagent.infrastructure.llm.shared.embedding_adapter import OpenAICompatibleEmbeddingAdapter
    url = os.getenv("EMBEDDING_SERVER_URL", "http://localhost:8081/v1")
    return OpenAICompatibleEmbeddingAdapter(
        base_url=url,
        api_key="local",
        model=os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-8B-Q4_K_M.gguf"),
        timeout=float(os.getenv("EMBEDDING_TIMEOUT", "60")),
    )
