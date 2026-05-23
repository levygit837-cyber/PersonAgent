"""Tests for ``RequestContext``.

The purpose of this type is to replace the StateManager singleton with a
per-request immutable snapshot. These tests pin the invariants that make
the replacement safe to use across the call chain.
"""

from __future__ import annotations

import dataclasses

import pytest

from personagent.application.state import RequestContext
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)


def _stub_build_result() -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(),
        user_context=UserContext(),
        build_duration_ms=0,
        metadata={"source": "built"},
    )


def test_default_request_context_has_a_fresh_request_id() -> None:
    """Two default constructions must not share a request_id."""

    first = RequestContext()
    second = RequestContext()

    assert first.request_id
    assert second.request_id
    assert first.request_id != second.request_id


def test_request_context_is_frozen() -> None:
    """Attribute assignment must fail loudly on the frozen dataclass."""

    ctx = RequestContext(conversation_id="c-1")

    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.conversation_id = "tampered"  # type: ignore[misc]


def test_from_build_result_populates_all_fields() -> None:
    """``from_build_result`` is the canonical construction path."""

    ctx = RequestContext.from_build_result(
        conversation_id="c-1",
        workspace_root="/tmp/work",
        result=_stub_build_result(),
        permission_mode="auto",
        tenant_id="acme",
        user_id="levy",
        request_id="req-42",
    )

    assert ctx.conversation_id == "c-1"
    assert ctx.workspace_root == "/tmp/work"
    assert ctx.permission_mode == "auto"
    assert ctx.tenant_id == "acme"
    assert ctx.user_id == "levy"
    assert ctx.request_id == "req-42"
    assert ctx.system_context is not None
    assert ctx.user_context is not None


def test_with_overrides_swaps_only_the_named_fields() -> None:
    """All other fields must survive the copy verbatim."""

    base = RequestContext.from_build_result(
        conversation_id="c-1",
        workspace_root="/tmp/work",
        result=_stub_build_result(),
        permission_mode="manual",
        tenant_id="acme",
        user_id="levy",
        request_id="req-1",
    )

    refined = base.with_overrides(permission_mode="ask")

    assert refined.permission_mode == "ask"
    assert refined.request_id == base.request_id
    assert refined.conversation_id == base.conversation_id
    assert refined.workspace_root == base.workspace_root
    assert refined.tenant_id == base.tenant_id
    assert refined.user_id == base.user_id
    assert refined.created_at == base.created_at


def test_with_overrides_clones_the_extra_dict() -> None:
    """Mutating one context's ``extra`` cannot leak to a sibling."""

    base = RequestContext(extra={"flag": True})
    sibling = base.with_overrides()

    sibling.extra["flag"] = False

    assert base.extra["flag"] is True


def test_default_permission_mode_is_manual() -> None:
    """The most conservative permission mode is the default."""

    ctx = RequestContext()

    assert ctx.permission_mode == "manual"


def test_default_tenant_and_user_are_none() -> None:
    """Multi-tenant fields stay opt-in until later phases populate them."""

    ctx = RequestContext()

    assert ctx.tenant_id is None
    assert ctx.user_id is None
