"""LLM backend creation and lifecycle mixin."""

from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.infrastructure.llm.codex.subscription_adapter import CodexSubscriptionAdapter
from personagent.infrastructure.llm.deepseek_adapter import DeepSeekAdapter
from personagent.infrastructure.llm.kimi.coding_adapter import KimiCodingAdapter
from personagent.infrastructure.llm.llama_cpp_adapter import LlamaCppAdapter
from personagent.infrastructure.llm.nvidia_nim_adapter import NvidiaNimAdapter
from personagent.infrastructure.llm.vertex_ai import VertexAiAdapter
from personagent.infrastructure.llm.zenmux_adapter import ZenMuxAdapter


class _LLMMixin:
    def get_llm_backend(self, provider: str = "llama") -> LLMBackendRepository:
        """Retorna o adapter do LLM (singleton)."""
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {
            "llama",
            "nvidia",
            "deepseek",
            "zenmux",
            "vertex",
            "kimi",
            "codex",
        }:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        if normalized_provider not in self._llm_backends:
            self._llm_backends[normalized_provider] = self._create_llm_backend(normalized_provider)
        return self._llm_backends[normalized_provider]

    def _create_llm_backend(self, provider: str) -> LLMBackendRepository:
        if provider == "llama":
            return LlamaCppAdapter(
                base_url=self._settings.llama_server_url,
                api_key=self._settings.llama_server_api_key,
                timeout=self._settings.llama_timeout_seconds,
                stream_read_timeout=self._settings.llama_stream_read_timeout_seconds,
                default_max_tokens=self._settings.llama_max_tokens,
                reasoning=self._settings.llama_reasoning,
                reasoning_budget=self._settings.llama_reasoning_budget,
                ctx_size=self._settings.llama_ctx_size,
            )
        if provider == "nvidia":
            return NvidiaNimAdapter(
                base_url=self._settings.nvidia_base_url,
                api_key=self._settings.nvidia_api_key,
                timeout=self._settings.nvidia_timeout_seconds,
                stream_read_timeout=self._settings.nvidia_stream_read_timeout_seconds,
                default_model=self._settings.nvidia_default_model,
                default_max_tokens=self._settings.nvidia_max_tokens,
                models_cache_ttl_seconds=self._settings.nvidia_models_cache_ttl_seconds,
            )
        if provider == "deepseek":
            return DeepSeekAdapter(
                base_url=self._settings.deepseek_base_url,
                api_key=self._settings.deepseek_api_key,
                timeout=self._settings.deepseek_timeout_seconds,
                stream_read_timeout=self._settings.deepseek_stream_read_timeout_seconds,
                default_model=self._settings.deepseek_default_model,
                default_max_tokens=self._settings.deepseek_max_tokens,
                models_cache_ttl_seconds=self._settings.deepseek_models_cache_ttl_seconds,
            )
        if provider == "zenmux":
            return ZenMuxAdapter(
                base_url=self._settings.zenmux_base_url,
                api_key=self._settings.zenmux_api_key,
                timeout=self._settings.zenmux_timeout_seconds,
                stream_read_timeout=self._settings.zenmux_stream_read_timeout_seconds,
                default_model=self._settings.zenmux_default_model,
                default_max_tokens=self._settings.zenmux_max_tokens,
                models_cache_ttl_seconds=self._settings.zenmux_models_cache_ttl_seconds,
                context_window=self._settings.zenmux_context_window,
            )
        if provider == "vertex":
            return VertexAiAdapter(
                api_key=self._settings.google_api_key,
                auth_mode=self._settings.vertex_auth_mode,
                project_id=self._settings.vertex_project_id,
                location=self._settings.vertex_location,
                timeout=self._settings.vertex_timeout_seconds,
                stream_read_timeout=self._settings.vertex_stream_read_timeout_seconds,
                default_model=self._settings.vertex_default_model,
                default_max_tokens=self._settings.vertex_max_tokens,
                models_cache_ttl_seconds=self._settings.vertex_models_cache_ttl_seconds,
            )
        if provider == "kimi":
            return KimiCodingAdapter(
                base_url=self._settings.kimi_base_url,
                api_key=self._settings.kimi_api_key,
                timeout=self._settings.kimi_timeout_seconds,
                stream_read_timeout=self._settings.kimi_stream_read_timeout_seconds,
                default_model=self._settings.kimi_default_model,
                default_max_tokens=self._settings.kimi_max_tokens,
                context_window=self._settings.kimi_context_window,
                anthropic_version=self._settings.kimi_anthropic_version,
            )
        if provider == "codex":
            return CodexSubscriptionAdapter(
                base_url=self._settings.codex_base_url,
                codex_home=self._settings.codex_home,
                codex_cli_path=self._settings.codex_cli_path,
                client_version=self._settings.codex_client_version,
                timeout=self._settings.codex_timeout_seconds,
                stream_read_timeout=self._settings.codex_stream_read_timeout_seconds,
                default_model=self._settings.codex_default_model,
                default_max_tokens=self._settings.codex_max_tokens,
                context_window=self._settings.codex_context_window,
                models_cache_ttl_seconds=self._settings.codex_models_cache_ttl_seconds,
            )
        raise ValueError(f"Unsupported LLM provider: {provider}")

    async def close_llm_backends(self) -> None:
        """Close all initialized LLM adapters."""
        for backend in self._llm_backends.values():
            close = getattr(backend, "close", None)
            if close is not None:
                await close()
        self._llm_backends.clear()
        if self._embedding_adapter is not None:
            close = getattr(self._embedding_adapter, "close", None)
            if close is not None:
                await close()
            self._embedding_adapter = None
