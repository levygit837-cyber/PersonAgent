"""Tests for :class:`TurnContextResolver`.

Three branches matter:

* ``BuildContextUseCase`` succeeds  → its result is returned verbatim.
* ``BuildContextUseCase`` raises    → fallback path is taken, exception
  is logged and swallowed.
* ``BuildContextUseCase`` is ``None`` → fallback path is taken without
  invoking the use case.

The fallback emits a minimal :class:`ContextBuildResult` whose
``system_context.workspace_root`` is whatever
``OperationalMemoryCapture.resolve_workspace_root`` returns, and whose
metadata is ``{"source": "fallback"}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.turn_context import TurnContextResolver
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.conversation.models import Conversation


def _request(**overrides: Any) -> ChatRequestDTO:
    defaults: dict[str, Any] = {
        "message": "hi",
        "provider": "openai",
        "model": "gpt-4o",
    }
    defaults.update(overrides)
    return ChatRequestDTO(**defaults)


def _operational_memory(workspace_root: str = "/tmp/work") -> MagicMock:
    mock = MagicMock()
    mock.resolve_workspace_root = MagicMock(return_value=Path(workspace_root))
    return mock


@pytest.mark.asyncio
async def test_uses_build_context_use_case_result_on_success() -> None:
    sentinel = ContextBuildResult(
        system_context=SystemContext(workspace_root="/sentinel", cwd="/sentinel"),
        user_context=UserContext(current_date="2025-01-01"),
        build_duration_ms=42,
        metadata={"source": "real"},
    )
    bcu = MagicMock()
    bcu.execute = AsyncMock(return_value=sentinel)
    resolver = TurnContextResolver(
        build_context_use_case=bcu,
        operational_memory=_operational_memory(),
    )
    conv = Conversation()

    result = await resolver.build(_request(), conv)

    assert result is sentinel
    bcu.execute.assert_awaited_once_with(
        conversation_id=str(conv.id),
        use_cache=True,
    )


@pytest.mark.asyncio
async def test_falls_back_when_build_context_use_case_is_none() -> None:
    op_mem = _operational_memory(workspace_root="/tmp/fallback")
    resolver = TurnContextResolver(
        build_context_use_case=None,
        operational_memory=op_mem,
    )

    result = await resolver.build(_request(), Conversation())

    assert result.metadata == {"source": "fallback"}
    assert result.system_context.workspace_root == "/tmp/fallback"
    assert result.system_context.cwd == "/tmp/fallback"
    assert result.build_duration_ms == 0


@pytest.mark.asyncio
async def test_falls_back_when_build_context_use_case_raises() -> None:
    bcu = MagicMock()
    bcu.execute = AsyncMock(side_effect=RuntimeError("boom"))
    op_mem = _operational_memory(workspace_root="/tmp/safety")
    resolver = TurnContextResolver(
        build_context_use_case=bcu,
        operational_memory=op_mem,
    )

    result = await resolver.build(_request(), Conversation())

    assert result.metadata == {"source": "fallback"}
    assert result.system_context.workspace_root == "/tmp/safety"
    bcu.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_current_date_is_iso_yyyy_mm_dd() -> None:
    resolver = TurnContextResolver(
        build_context_use_case=None,
        operational_memory=_operational_memory(),
    )

    result = await resolver.build(_request(), Conversation())

    # "YYYY-MM-DD" => 10 chars, dashes at positions 4 and 7
    assert len(result.user_context.current_date) == 10
    assert result.user_context.current_date[4] == "-"
    assert result.user_context.current_date[7] == "-"


@pytest.mark.asyncio
async def test_fallback_uses_workspace_root_resolver_with_request() -> None:
    op_mem = _operational_memory()
    resolver = TurnContextResolver(
        build_context_use_case=None,
        operational_memory=op_mem,
    )
    req = _request()

    await resolver.build(req, Conversation())

    op_mem.resolve_workspace_root.assert_called_once_with(req)
