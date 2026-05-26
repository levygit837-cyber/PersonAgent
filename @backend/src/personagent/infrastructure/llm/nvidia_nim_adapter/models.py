"""Model catalog helpers for NVIDIA NIM adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from personagent.infrastructure.llm.nvidia_nim_adapter.constants import (
    KNOWN_REASONING_CHAT_MODELS,
    THINKING_TEMPLATE_KWARGS_MODELS,
)


def _model_label(model_id: str) -> str:
    name = model_id.split("/", 1)[-1]
    return " ".join(
        part.upper() if part.isdigit() else part.capitalize() for part in name.split("-")
    )


def _is_reasoning_chat_model(model_id: str) -> bool:
    lower = model_id.lower()
    return lower in KNOWN_REASONING_CHAT_MODELS


def _supports_thinking_budget(model_id: str) -> bool:
    lower = model_id.lower()
    return "nemotron-3-nano-30b-a3b" in lower or "nemotron-nano-9b-v2" in lower


def _supports_thinking_template_kwargs(model_id: str) -> bool:
    return model_id.lower() in THINKING_TEMPLATE_KWARGS_MODELS


def _normalize_model(
    item: dict[str, Any],
    provider_key: str,
    *,
    is_reasoning_chat_model: Callable[[str], bool] = _is_reasoning_chat_model,
    supports_thinking_budget: Callable[[str], bool] = _supports_thinking_budget,
) -> dict[str, Any]:
    model_id = str(item["id"])
    supports_reasoning = is_reasoning_chat_model(model_id)
    supports_thinking_budget_flag = supports_thinking_budget(model_id)
    capabilities = ["chat"]
    if supports_reasoning:
        capabilities.append("reasoning_chat")
    if supports_thinking_budget_flag:
        capabilities.append("thinking_budget")

    return {
        "id": model_id,
        "provider": provider_key,
        "label": _model_label(model_id),
        "owned_by": item.get("owned_by") or model_id.split("/", 1)[0],
        "capabilities": capabilities,
        "supports_streaming": True,
        "supports_reasoning": supports_reasoning,
        "supports_thinking_budget": supports_thinking_budget_flag,
        "raw": item,
    }


def _normalize_model_response(
    data: dict[str, Any],
    provider_key: str,
    *,
    normalize_model: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    raw_models = data.get("data", []) if isinstance(data, dict) else []
    models_by_id: dict[str, dict[str, Any]] = {}
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        model = normalize_model(item)
        models_by_id[model_id] = model

    return {
        "object": "list",
        "provider": provider_key,
        "data": list(models_by_id.values()),
    }


def _filter_model_response(
    response: dict[str, Any],
    capability: str | None,
    provider_key: str,
) -> dict[str, Any]:
    models = list(response.get("data") or [])
    if capability:
        models = [model for model in models if capability in model.get("capabilities", [])]
    return {
        "object": "list",
        "provider": provider_key,
        "data": models,
    }
