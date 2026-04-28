"""Adapter for the official DeepSeek OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

from personagent.infrastructure.llm.nvidia_nim_adapter import (
    DEFAULT_OUTPUT_TOKENS,
    FINAL_RESPONSE_TOKEN_RESERVE,
    MIN_REASONING_MAX_TOKENS,
    NvidiaNimAdapter,
)

DEEPSEEK_CONTEXT_WINDOW = 1_000_000
DEEPSEEK_MAX_OUTPUT_TOKENS = 384_000
DEEPSEEK_REASONING_MODELS = {
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    # Compatibility aliases currently route to V4 Flash per DeepSeek docs.
    "deepseek-chat",
    "deepseek-reasoner",
}


class DeepSeekAdapter(NvidiaNimAdapter):
    """Official DeepSeek chat adapter with thinking/tool-call support."""

    def __init__(
        self,
        base_url: str = "https://api.deepseek.com",
        api_key: str = "",
        timeout: float = 240.0,
        stream_read_timeout: float | None = 0.0,
        default_model: str = "deepseek-v4-flash",
        default_max_tokens: int = DEFAULT_OUTPUT_TOKENS,
        models_cache_ttl_seconds: int = 300,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            stream_read_timeout=stream_read_timeout,
            default_model=default_model,
            default_max_tokens=default_max_tokens,
            models_cache_ttl_seconds=models_cache_ttl_seconds,
            provider_key="deepseek",
            provider_display_name="DeepSeek",
            api_key_env_name="DEEPSEEK_API_KEY",
        )

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        stream: bool,
        extra: dict[str, Any],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_model = str(extra.get("model") or "").strip()
        model = self.default_model if requested_model in {"", "local-model"} else requested_model
        thinking_enabled = self._is_reasoning_chat_model(model)
        effective_max_tokens = self._resolve_effective_max_tokens(
            model=model,
            max_tokens=max_tokens,
            thinking_budget=None,
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages_with_reasoning(messages),
            "max_tokens": effective_max_tokens,
            "stream": stream,
        }

        if thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self._reasoning_effort(extra.get("reasoning_level"))
        else:
            payload["temperature"] = temperature

        if extra.get("stop"):
            payload["stop"] = extra["stop"]
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        return payload

    def _normalize_model(self, item: dict[str, Any]) -> dict[str, Any]:
        model = super()._normalize_model(item)
        model["context_length"] = DEEPSEEK_CONTEXT_WINDOW
        model["max_output_tokens"] = DEEPSEEK_MAX_OUTPUT_TOKENS
        return model

    def _is_reasoning_chat_model(self, model_id: str) -> bool:
        return model_id.lower() in DEEPSEEK_REASONING_MODELS

    def _resolve_effective_max_tokens(
        self,
        *,
        model: str,
        max_tokens: int,
        thinking_budget: int | None,
    ) -> int:
        effective_max_tokens = max_tokens if max_tokens > 0 else self.default_max_tokens
        if self._is_reasoning_chat_model(model):
            effective_max_tokens = max(effective_max_tokens, MIN_REASONING_MAX_TOKENS)
        if thinking_budget is not None and thinking_budget >= effective_max_tokens:
            effective_max_tokens = thinking_budget + FINAL_RESPONSE_TOKEN_RESERVE
        return min(effective_max_tokens, DEEPSEEK_MAX_OUTPUT_TOKENS)

    def _reasoning_effort(self, level: Any) -> str:
        normalized = str(level or "high").strip().lower()
        return "max" if normalized in {"max", "xhigh"} else "high"

    def _messages_with_reasoning(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized_messages: list[dict[str, Any]] = []
        for message in messages:
            next_message = dict(message)
            metadata = next_message.pop("metadata", None)
            if (
                next_message.get("role") == "assistant"
                and "reasoning_content" not in next_message
                and isinstance(metadata, dict)
                and isinstance(metadata.get("reasoning_content"), str)
            ):
                next_message["reasoning_content"] = metadata["reasoning_content"]
            normalized_messages.append(next_message)
        return normalized_messages
