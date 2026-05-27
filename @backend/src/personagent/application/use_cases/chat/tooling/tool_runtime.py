"""Per-turn tool-runtime helpers for ``ChatCompletionUseCase``.

Wraps the small cluster of methods that depend on both the
:class:`ToolRegistry` and the :class:`ToolRuntimeConfig`. Keeping them
on a single collaborator removes four private methods from
``chat_completion.py`` and gives the streaming-turn executor a single
typed handle to call instead of four callable-style injections.

The class is intentionally tiny: no caching, no per-turn state, just
the four queries that ``ChatCompletionUseCase`` used to expose as
private methods. Concurrency: stateless. Safe to share across requests.
"""

from __future__ import annotations

from typing import Any, cast

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import is_plan_mode_active
from personagent.application.ports.artifact_storage import ArtifactStoragePort
from personagent.application.tools import (
    ToolOrchestrator,
    ToolRegistry,
    ToolRuntimeConfig,
)
from personagent.application.tools.runtime_config import (
    resolve_effective_tool_iterations,
)
from personagent.domain.conversation.models import Conversation


class ToolRuntime:
    """Bundle of tool-runtime queries used by the streaming turn loop.

    Parameters
    ----------
    tool_registry:
        Optional ``ToolRegistry`` — when ``None``, every method behaves
        as if tools are completely disabled.
    tool_runtime_config:
        Optional ``ToolRuntimeConfig`` — supplies the configured
        iteration cap and is required to spawn a ``ToolOrchestrator``.
    """

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None,
        tool_runtime_config: ToolRuntimeConfig | None,
        artifact_storage: ArtifactStoragePort | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._tool_runtime_config = tool_runtime_config
        self._artifact_storage = artifact_storage

    def resolve_schemas(
        self,
        request: ChatRequestDTO,
        conversation: Conversation | None = None,
    ) -> list[dict[str, Any]]:
        """Return the OpenAI-style tool schemas allowed for ``request``.

        When ``tools_enabled`` is ``False`` or no registry is configured,
        the result is the empty list. When a ``conversation`` is given
        the planning-tool pair (``EnterPlanMode`` / ``ExitPlanMode``) is
        filtered based on the conversation's current plan-mode state so
        the model only ever sees the move that is legal *right now*.
        """

        if not request.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        schemas = cast(
            list[dict[str, Any]],
            self._tool_registry.openai_schemas(
                allowed_tools=allowed_tools,
                cache_scope=f"{request.provider}:{request.model}",
            ),
        )
        if conversation is None:
            return schemas

        plan_active = is_plan_mode_active(conversation.metadata)
        filtered: list[dict[str, Any]] = []
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if name == "ExitPlanMode" and not plan_active:
                continue
            if name == "EnterPlanMode" and plan_active:
                continue
            filtered.append(schema)
        return filtered

    def new_orchestrator(self) -> ToolOrchestrator:
        """Spawn a fresh ``ToolOrchestrator``.

        Raises :class:`RuntimeError` when either the registry or the
        runtime config is missing -- both are required to execute a
        tool. Callers must only call this once they've decided there
        *is* tool work to do (``resolve_schemas`` returned a non-empty
        list).
        """

        if self._tool_registry is None or self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")
        return ToolOrchestrator(
            self._tool_registry,
            self._tool_runtime_config,
            self._artifact_storage,
        )

    def effective_max_tool_iterations(self, request: ChatRequestDTO) -> int:
        """Return the bounded tool-iteration cap for ``request``.

        Delegates the precedence logic to
        :func:`resolve_effective_tool_iterations` so the rule lives in
        exactly one place.
        """

        config_max = (
            self._tool_runtime_config.max_tool_iterations
            if self._tool_runtime_config is not None
            else None
        )
        return int(
            resolve_effective_tool_iterations(
                request_max=request.max_tool_iterations,
                config_max=config_max,
            )
        )

    def tool_iteration_limit_source(self, request: ChatRequestDTO) -> str:
        """Describe which input determined the active iteration cap.

        Returns one of ``"request"``, ``"runtime_config"``, or
        ``"safety_ceiling"`` so the UI can attribute the limit to the
        right place when emitting ``tool_loop_limit_exceeded`` events.
        """

        if request.max_tool_iterations is not None:
            return "request"
        config_max = (
            self._tool_runtime_config.max_tool_iterations
            if self._tool_runtime_config is not None
            else None
        )
        if config_max is not None:
            return "runtime_config"
        return "safety_ceiling"
