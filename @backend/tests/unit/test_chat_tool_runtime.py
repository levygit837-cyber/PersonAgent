"""Tests for :class:`ToolRuntime`.

The class bundles four queries that the streaming chat turn issues
against the configured :class:`ToolRegistry` and
:class:`ToolRuntimeConfig`. Each query is tested in isolation:

* ``resolve_schemas`` — including the planning-tool filter that depends
  on the conversation's plan-mode metadata.
* ``new_orchestrator`` — including the ``RuntimeError`` raised when the
  registry / runtime config are missing.
* ``effective_max_tool_iterations`` — request precedence over config.
* ``tool_iteration_limit_source`` — string description of which input
  determined the cap (``"request"`` / ``"runtime_config"`` /
  ``"safety_ceiling"``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools import ToolRuntimeConfig
from personagent.application.use_cases.chat.tool_runtime import ToolRuntime
from personagent.domain.models.conversation import Conversation


def _request(**overrides: Any) -> ChatRequestDTO:
    defaults: dict[str, Any] = {
        "message": "hi",
        "provider": "openai",
        "model": "gpt-4o",
        "tools_enabled": True,
    }
    defaults.update(overrides)
    return ChatRequestDTO(**defaults)


def _runtime_config(*, max_tool_iterations: int | None = None) -> ToolRuntimeConfig:
    return ToolRuntimeConfig(
        workspace_root=Path("/tmp"),
        allowed_roots=(Path("/tmp"),),
        max_tool_iterations=max_tool_iterations,
    )


# -- resolve_schemas ------------------------------------------------------


def test_resolve_schemas_returns_empty_when_tools_disabled() -> None:
    registry = MagicMock()
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=None)

    schemas = runtime.resolve_schemas(_request(tools_enabled=False))

    assert schemas == []
    registry.openai_schemas.assert_not_called()


def test_resolve_schemas_returns_empty_when_registry_missing() -> None:
    runtime = ToolRuntime(tool_registry=None, tool_runtime_config=None)

    assert runtime.resolve_schemas(_request()) == []


def test_resolve_schemas_passes_allowed_tools_and_cache_scope() -> None:
    registry = MagicMock()
    registry.openai_schemas = MagicMock(return_value=[{"function": {"name": "Shell"}}])
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=None)
    req = _request(allowed_tools=["Shell", "Read"])

    schemas = runtime.resolve_schemas(req)

    assert schemas == [{"function": {"name": "Shell"}}]
    registry.openai_schemas.assert_called_once_with(
        allowed_tools={"Shell", "Read"},
        cache_scope="openai:gpt-4o",
    )


def test_resolve_schemas_filters_exit_plan_mode_when_plan_inactive() -> None:
    registry = MagicMock()
    registry.openai_schemas = MagicMock(
        return_value=[
            {"function": {"name": "EnterPlanMode"}},
            {"function": {"name": "ExitPlanMode"}},
            {"function": {"name": "Shell"}},
        ]
    )
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=None)
    conv = Conversation()
    # plan mode metadata absent / inactive

    schemas = runtime.resolve_schemas(_request(), conv)

    names = {s["function"]["name"] for s in schemas}
    assert names == {"EnterPlanMode", "Shell"}


def test_resolve_schemas_filters_enter_plan_mode_when_plan_active() -> None:
    registry = MagicMock()
    registry.openai_schemas = MagicMock(
        return_value=[
            {"function": {"name": "EnterPlanMode"}},
            {"function": {"name": "ExitPlanMode"}},
        ]
    )
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=None)
    conv = Conversation()
    conv.metadata["plan_mode"] = {
        "active": True,
        "status": "draft",
        "plan_id": "plan-1",
        "approval_id": "",
        "plan_content": "",
    }

    schemas = runtime.resolve_schemas(_request(), conv)

    names = {s["function"]["name"] for s in schemas}
    assert names == {"ExitPlanMode"}


def test_resolve_schemas_no_conversation_returns_unfiltered_schemas() -> None:
    registry = MagicMock()
    registry.openai_schemas = MagicMock(
        return_value=[
            {"function": {"name": "EnterPlanMode"}},
            {"function": {"name": "ExitPlanMode"}},
        ]
    )
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=None)

    schemas = runtime.resolve_schemas(_request())

    assert len(schemas) == 2


# -- new_orchestrator -----------------------------------------------------


def test_new_orchestrator_raises_when_registry_missing() -> None:
    runtime = ToolRuntime(
        tool_registry=None,
        tool_runtime_config=_runtime_config(),
    )

    with pytest.raises(RuntimeError, match="Tool runtime is not configured"):
        runtime.new_orchestrator()


def test_new_orchestrator_raises_when_runtime_config_missing() -> None:
    runtime = ToolRuntime(tool_registry=MagicMock(), tool_runtime_config=None)

    with pytest.raises(RuntimeError, match="Tool runtime is not configured"):
        runtime.new_orchestrator()


def test_new_orchestrator_returns_orchestrator_with_registry_and_config() -> None:
    registry = MagicMock()
    config = _runtime_config()
    runtime = ToolRuntime(tool_registry=registry, tool_runtime_config=config)

    orchestrator = runtime.new_orchestrator()

    # Each call must produce a fresh orchestrator (no caching)
    assert orchestrator is not runtime.new_orchestrator()


# -- effective_max_tool_iterations ---------------------------------------


def test_effective_max_iterations_uses_request_value_when_set() -> None:
    runtime = ToolRuntime(
        tool_registry=None,
        tool_runtime_config=_runtime_config(max_tool_iterations=10),
    )

    assert runtime.effective_max_tool_iterations(_request(max_tool_iterations=5)) == 5


def test_effective_max_iterations_falls_back_to_runtime_config_value() -> None:
    runtime = ToolRuntime(
        tool_registry=None,
        tool_runtime_config=_runtime_config(max_tool_iterations=10),
    )

    assert runtime.effective_max_tool_iterations(_request()) == 10


def test_effective_max_iterations_uses_safety_ceiling_when_nothing_set() -> None:
    runtime = ToolRuntime(tool_registry=None, tool_runtime_config=None)

    value = runtime.effective_max_tool_iterations(_request())

    assert value >= 1  # safety ceiling is always positive


# -- tool_iteration_limit_source -----------------------------------------


def test_tool_iteration_limit_source_returns_request_when_set() -> None:
    runtime = ToolRuntime(
        tool_registry=None,
        tool_runtime_config=_runtime_config(max_tool_iterations=10),
    )

    assert (
        runtime.tool_iteration_limit_source(_request(max_tool_iterations=5))
        == "request"
    )


def test_tool_iteration_limit_source_returns_runtime_config_when_only_config_set() -> None:
    runtime = ToolRuntime(
        tool_registry=None,
        tool_runtime_config=_runtime_config(max_tool_iterations=10),
    )

    assert runtime.tool_iteration_limit_source(_request()) == "runtime_config"


def test_tool_iteration_limit_source_returns_safety_ceiling_when_nothing_set() -> None:
    runtime = ToolRuntime(tool_registry=None, tool_runtime_config=None)

    assert runtime.tool_iteration_limit_source(_request()) == "safety_ceiling"
