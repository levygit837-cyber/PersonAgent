"""Resolver helpers for chat completion routes."""

from typing import Any

# Late-binding module reference.  See module docstring for rationale.
import personagent.adapters.api.routes.chat as _chat
from personagent.adapters.api.routes.chat.helpers import (
    ChatRequest,
    resolve_tool_context,
)
from personagent.adapters.composition import DIContainer


def resolve_model(provider: str, model: str) -> str:
    """Resolve the default model per provider without breaking the existing local default."""
    if provider == "nvidia" and (not model or model == "local-model"):
        return _chat.get_container().settings.nvidia_default_model
    if provider == "deepseek" and (not model or model == "local-model"):
        return _chat.get_container().settings.deepseek_default_model
    if provider == "zenmux" and (not model or model == "local-model"):
        return _chat.get_container().settings.zenmux_default_model
    if provider == "vertex" and (not model or model == "local-model"):
        return _chat.get_container().settings.vertex_default_model
    if provider == "kimi" and (not model or model == "local-model"):
        return _chat.get_container().settings.kimi_default_model
    if provider == "codex" and (not model or model == "local-model"):
        return _chat.get_container().settings.codex_default_model
    return model


def resolve_context_window_tokens(container: DIContainer, provider: str) -> int:
    """Resolve the context window used for provider-specific budgeting/compaction."""
    if provider == "kimi":
        return container.settings.kimi_context_window
    if provider == "deepseek":
        return container.settings.deepseek_context_window
    if provider == "zenmux":
        return container.settings.zenmux_context_window
    if provider == "vertex":
        return container.settings.vertex_context_window
    if provider == "codex":
        return container.settings.codex_context_window
    return container.settings.llama_ctx_size


def resolve_default_output_tokens(container: DIContainer, provider: str) -> int:
    """Resolve the default output budget per provider."""
    if provider == "nvidia":
        return container.settings.nvidia_max_tokens
    if provider == "deepseek":
        return container.settings.deepseek_max_tokens
    if provider == "zenmux":
        return container.settings.zenmux_max_tokens
    if provider == "vertex":
        return container.settings.vertex_max_tokens
    if provider == "kimi":
        return container.settings.kimi_max_tokens
    if provider == "codex":
        return container.settings.codex_max_tokens
    return container.settings.llama_max_tokens


def resolve_context_workspace_root_from_tool_context(tool_context: dict[str, Any]) -> str:
    """Resolve the workspace for flows that already have persisted tool_context."""
    workspace_root = tool_context.get("workspace_root")
    if isinstance(workspace_root, str) and workspace_root.strip():
        return workspace_root
    return str(_chat.get_container().settings.tool_workspace_root_path)


def resolve_context_workspace_root(request: ChatRequest) -> str:
    """Resolve the workspace that should feed context and prompts."""
    tool_context = resolve_tool_context(request)
    return resolve_context_workspace_root_from_tool_context(tool_context)
