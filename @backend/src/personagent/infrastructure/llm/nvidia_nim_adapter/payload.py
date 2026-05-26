"""Payload building for NVIDIA NIM adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from personagent.infrastructure.llm.nvidia_nim_adapter.constants import (
    MAX_REASONING_BUDGET_TOKENS,
)


def _build_payload(
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    stream: bool,
    extra: dict[str, Any],
    *,
    default_model: str,
    default_max_tokens: int,
    provider_key: str,
    is_reasoning_chat_model: Callable[[str], bool],
    supports_thinking_budget: Callable[[str], bool],
    supports_thinking_template_kwargs: Callable[[str], bool],
    resolve_effective_max_tokens: Callable[..., int],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_model = str(extra.get("model") or "").strip()
    model = default_model if requested_model in {"", "local-model"} else requested_model
    request_reasoning_budget = extra.get("reasoning_budget_tokens")
    thinking_budget = (
        min(int(request_reasoning_budget), MAX_REASONING_BUDGET_TOKENS)
        if request_reasoning_budget is not None and supports_thinking_budget(model)
        else None
    )
    effective_max_tokens = resolve_effective_max_tokens(
        model=model,
        max_tokens=max_tokens,
        thinking_budget=thinking_budget,
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": effective_max_tokens,
        "stream": stream,
    }
    chat_template_kwargs = dict(extra.get("chat_template_kwargs") or {})
    if supports_thinking_template_kwargs(model):
        chat_template_kwargs.setdefault("enable_thinking", True)
    if chat_template_kwargs:
        payload["chat_template_kwargs"] = chat_template_kwargs

    if thinking_budget is not None:
        payload["nvext"] = {"max_thinking_tokens": thinking_budget}

    if extra.get("top_p"):
        payload["top_p"] = extra["top_p"]
    if extra.get("stop"):
        payload["stop"] = extra["stop"]
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    return payload
