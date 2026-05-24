"""Tests for :class:`ToolContextBuilder`.

The builder turns the per-request ``tool_context`` payload plus the
:class:`ToolRuntimeConfig` defaults into a :class:`ToolUseContext`
ready to hand to the tool orchestrator. The tests pin every branch
of the assembly:

* workspace-root resolution (config default vs. per-request override),
* allowed-roots resolution (config default vs. per-request override,
  with sandboxing against the effective workspace root),
* cwd resolution (workspace default vs. per-request override; must be
  a directory),
* permission-mode source priority (request payload > conversation
  metadata > ``ask_for_risk`` fallback) and validation,
* plan-mode propagation,
* limits + metadata payload shape.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.application.use_cases.chat.state import PromptPreparation
from personagent.application.use_cases.chat.tool_context_builder import (
    VALID_PERMISSION_MODES,
    ToolContextBuilder,
)
from personagent.domain.models.conversation import Conversation

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture()
def other_root(tmp_path: Path) -> Path:
    other = tmp_path / "other"
    other.mkdir()
    return other


def _config(workspace_root: Path, allowed_roots: tuple[Path, ...] | None = None) -> ToolRuntimeConfig:
    return ToolRuntimeConfig(
        workspace_root=workspace_root,
        allowed_roots=allowed_roots or (workspace_root,),
        skill_roots=(),
    )


def _request(tool_context: dict | None = None) -> ChatRequestDTO:
    return ChatRequestDTO(
        message="hi",
        tool_context=tool_context or {},
        provider="llama",
    )


def _conversation(metadata: dict | None = None) -> Conversation:
    return Conversation(id=uuid4(), title="t", messages=[], metadata=dict(metadata or {}))


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_build_raises_when_runtime_config_is_missing() -> None:
    builder = ToolContextBuilder(tool_runtime_config=None)
    with pytest.raises(RuntimeError, match="Tool runtime is not configured"):
        builder.build(_request(), _conversation())


def test_valid_permission_modes_set_is_frozen() -> None:
    # The legacy import path expects this exact set; tests pin it so
    # accidental edits surface immediately.
    expected = {
        "ask_for_risk",
        "manual",
        "read_only",
        "readonly",
        "accept_edits",
        "full",
        "bypass",
        "dont_ask",
    }
    assert expected == VALID_PERMISSION_MODES


# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------


def test_build_uses_config_workspace_when_request_does_not_override(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request(), _conversation())

    assert ctx.workspace_root == workspace
    assert ctx.cwd == workspace
    assert ctx.allowed_roots == (workspace,)


def test_build_uses_request_workspace_when_provided(workspace: Path, tmp_path: Path) -> None:
    override = tmp_path / "override"
    override.mkdir()
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request({"workspace_root": str(override)}), _conversation())

    assert ctx.workspace_root == override.resolve()
    # When the request overrides the workspace, the root scope is
    # restricted to *only* that workspace.
    assert ctx.allowed_roots == (override.resolve(),)


def test_resolve_workspace_root_rejects_non_directories(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("not-a-dir")
    builder = ToolContextBuilder(tool_runtime_config=_config(tmp_path))

    with pytest.raises(ValueError, match="Workspace root is not a directory"):
        builder.resolve_workspace_root(str(file_path))


def test_resolve_workspace_root_expands_user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    builder = ToolContextBuilder(tool_runtime_config=_config(tmp_path))

    resolved = builder.resolve_workspace_root("~")

    assert resolved == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Allowed roots resolution
# ---------------------------------------------------------------------------


def test_build_uses_config_allowed_roots_by_default(workspace: Path, other_root: Path) -> None:
    builder = ToolContextBuilder(
        tool_runtime_config=_config(workspace, allowed_roots=(workspace, other_root))
    )

    ctx = builder.build(_request(), _conversation())

    assert ctx.allowed_roots == (workspace, other_root)


def test_build_resolves_request_allowed_roots_against_root_scope(workspace: Path, other_root: Path) -> None:
    builder = ToolContextBuilder(
        tool_runtime_config=_config(workspace, allowed_roots=(workspace, other_root))
    )

    ctx = builder.build(
        _request({"allowed_roots": [str(other_root)]}),
        _conversation(),
    )

    assert ctx.allowed_roots == (other_root.resolve(),)


def test_build_ignores_empty_request_allowed_roots_list(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request({"allowed_roots": []}), _conversation())

    assert ctx.allowed_roots == (workspace,)


def test_resolve_allowed_path_rejects_paths_outside_roots(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    with pytest.raises(ValueError, match="Tool path is outside configured roots"):
        builder.resolve_allowed_path(str(outside), workspace, (workspace,))


def test_resolve_allowed_path_accepts_relative_paths_under_base_root(workspace: Path) -> None:
    sub = workspace / "sub"
    sub.mkdir()
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    resolved = builder.resolve_allowed_path("sub", workspace, (workspace,))

    assert resolved == sub.resolve()


# ---------------------------------------------------------------------------
# CWD resolution
# ---------------------------------------------------------------------------


def test_build_defaults_cwd_to_workspace_root(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request(), _conversation())

    assert ctx.cwd == workspace


def test_build_resolves_request_cwd_inside_allowed_roots(workspace: Path) -> None:
    sub = workspace / "src"
    sub.mkdir()
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request({"cwd": str(sub)}), _conversation())

    assert ctx.cwd == sub.resolve()


def test_build_rejects_cwd_that_is_not_a_directory(workspace: Path) -> None:
    file_path = workspace / "file.txt"
    file_path.write_text("x")
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    with pytest.raises(ValueError, match="Tool cwd is not a directory"):
        builder.build(_request({"cwd": str(file_path)}), _conversation())


# ---------------------------------------------------------------------------
# Permission mode
# ---------------------------------------------------------------------------


def test_build_defaults_permission_mode_to_ask_for_risk(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request(), _conversation())

    assert ctx.permissions["mode"] == "ask_for_risk"


def test_build_uses_request_permission_mode_when_valid(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request({"permission_mode": "FULL"}), _conversation())

    assert ctx.permissions["mode"] == "full"


def test_build_falls_back_when_request_permission_mode_is_invalid(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request({"permission_mode": "bogus"}), _conversation())

    assert ctx.permissions["mode"] == "ask_for_risk"


def test_build_falls_back_to_conversation_permission_mode(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(
        _request(),
        _conversation(metadata={"permission_mode": "manual"}),
    )

    assert ctx.permissions["mode"] == "manual"


# ---------------------------------------------------------------------------
# Plan-mode propagation
# ---------------------------------------------------------------------------


def test_build_reports_plan_active_from_conversation_metadata(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))
    conv = _conversation(metadata={"plan_mode": {"active": True, "status": "draft"}})

    ctx = builder.build(_request(), conv)

    assert ctx.permissions["plan_mode"] is True
    assert ctx.metadata["plan_mode_active"] is True
    assert ctx.metadata["plan_mode"]["status"] == "draft"


def test_build_plan_mode_inactive_by_default(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request(), _conversation())

    assert ctx.permissions["plan_mode"] is False
    assert ctx.metadata["plan_mode_active"] is False


# ---------------------------------------------------------------------------
# Metadata + limits payload
# ---------------------------------------------------------------------------


def test_build_propagates_browser_target_from_preparation(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))
    prep = PromptPreparation(
        request=ChatRequestDTO(message="hi"),
        browser_target={"selector": "#btn"},
    )

    ctx = builder.build(_request(), _conversation(), prep)

    assert ctx.metadata["browser_target"] == {"selector": "#btn"}


def test_build_browser_target_is_none_without_preparation(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))

    ctx = builder.build(_request(), _conversation())

    assert ctx.metadata["browser_target"] is None


def test_build_metadata_includes_todos_and_browser_keys(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))
    conv = _conversation(
        metadata={
            "todos": [{"task": "foo"}],
            "browser_cooperation": {"browser-1": {"x": 1}},
            "browser_workspace": {"foo": "bar"},
        }
    )

    ctx = builder.build(_request({"structured_output_schema": {"type": "object"}}), conv)

    assert ctx.metadata["todos"] == [{"task": "foo"}]
    assert ctx.metadata["browser_cooperation"] == {"browser-1": {"x": 1}}
    assert ctx.metadata["browser_workspace"] == {"foo": "bar"}
    assert ctx.metadata["structured_output_schema"] == {"type": "object"}


def test_build_propagates_runtime_limits(workspace: Path) -> None:
    config = ToolRuntimeConfig(
        workspace_root=workspace,
        allowed_roots=(workspace,),
        read_max_bytes=4096,
        read_default_limit=1024,
        read_max_lines=2048,
        search_timeout_ms=1_000,
        shell_timeout_ms=2_000,
        web_timeout_ms=3_000,
        web_max_bytes=5_000,
        max_tool_iterations=12,
        max_concurrency=3,
        result_max_chars=999,
        tool_result_storage_root=workspace,
        web_allowed_domains=("example.com",),
        web_blocked_domains=("blocked.com",),
        web_allow_private_hosts=True,
        skill_roots=(workspace / "skills",),
    )
    builder = ToolContextBuilder(tool_runtime_config=config)

    ctx = builder.build(_request(), _conversation())

    assert ctx.limits["read_max_bytes"] == 4096
    assert ctx.limits["read_default_limit"] == 1024
    assert ctx.limits["read_max_lines"] == 2048
    assert ctx.limits["search_timeout_ms"] == 1_000
    assert ctx.limits["shell_timeout_ms"] == 2_000
    assert ctx.limits["web_timeout_ms"] == 3_000
    assert ctx.limits["web_max_bytes"] == 5_000
    assert ctx.limits["max_tool_iterations"] == 12
    assert ctx.limits["max_concurrency"] == 3
    assert ctx.limits["result_max_chars"] == 999
    assert ctx.limits["tool_result_storage_root"] == str(workspace)
    assert ctx.limits["web_allowed_domains"] == ("example.com",)
    assert ctx.limits["web_blocked_domains"] == ("blocked.com",)
    assert ctx.limits["web_allow_private_hosts"] is True
    assert ctx.limits["skill_roots"] == (str(workspace / "skills"),)


def test_build_tool_result_storage_root_is_none_when_config_has_none(workspace: Path) -> None:
    config = ToolRuntimeConfig(
        workspace_root=workspace,
        allowed_roots=(workspace,),
        tool_result_storage_root=None,
    )
    builder = ToolContextBuilder(tool_runtime_config=config)

    ctx = builder.build(_request(), _conversation())

    assert ctx.limits["tool_result_storage_root"] is None


def test_build_propagates_raw_request_tool_context(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))
    raw = {"workspace_root": str(workspace), "extra": "carryover"}

    ctx = builder.build(_request(raw), _conversation())

    assert ctx.metadata["request"] == raw


def test_build_sets_conversation_id_from_conversation(workspace: Path) -> None:
    builder = ToolContextBuilder(tool_runtime_config=_config(workspace))
    conv = _conversation()

    ctx = builder.build(_request(), conv)

    assert ctx.conversation_id == str(conv.id)
