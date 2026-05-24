"""Tests for the chat prompt-surface preparer.

The preparer routes every chat request through three optional
surfaces before the system prompt is built:

* slash-invocation -> prompt command / skill / builtin;
* context attachments -> reminder blocks + browser target;
* per-surface request overrides (allowed_tools / model / effort).

These tests pin the externally observable behavior we rely on. The
prompt-command + skill resolution lookups touch the filesystem, so
we cover them with light doubles that stand in for ``CommandService``
and ``find_skill`` -- the goal here isn't to re-test the underlying
loaders, it's to pin the routing rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.prompt_surfaces import (
    PromptSurfacePreparer,
)
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.prompts.commands import (
    BuiltinCommand,
    BuiltinCommandResolution,
    PromptCommand,
    SlashCommandResolution,
)
from personagent.domain.prompts.skills import SkillDefinition

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _CommandServiceStub:
    """Stand-in for :class:`CommandService`.

    Configure the optional resolutions the preparer will see; the
    methods just hand them back without parsing.
    """

    def __init__(
        self,
        *,
        prompt_resolution: SlashCommandResolution | None = None,
        builtin_resolution: BuiltinCommandResolution | None = None,
    ) -> None:
        self.prompt_resolution = prompt_resolution
        self.builtin_resolution = builtin_resolution
        self.prompt_calls: list[tuple[str, Any]] = []
        self.builtin_calls: list[str] = []

    def resolve_prompt_command(
        self, message: str, workspace_root: Any
    ) -> SlashCommandResolution | None:
        self.prompt_calls.append((message, workspace_root))
        return self.prompt_resolution

    def resolve_builtin(self, message: str) -> BuiltinCommandResolution | None:
        self.builtin_calls.append(message)
        return self.builtin_resolution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _request(
    message: str = "do the thing",
    *,
    allowed_tools: list[str] | None = None,
    reasoning_level: str | None = None,
    model: str = "test-model",
    context_attachments: list[dict[str, Any]] | None = None,
) -> ChatRequestDTO:
    return ChatRequestDTO(
        message=message,
        provider="nvidia",
        model=model,
        prompt_mode="code",
        reasoning_level=reasoning_level,
        allowed_tools=allowed_tools,
        context_attachments=context_attachments or [],
    )


def _context(workspace_root: str = "/home/user/MyProject") -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(
            workspace_root=workspace_root,
            cwd=workspace_root,
        ),
        user_context=UserContext(),
        build_duration_ms=0,
    )


def _preparer(
    *,
    prompt_resolution: SlashCommandResolution | None = None,
    builtin_resolution: BuiltinCommandResolution | None = None,
    skill_roots: tuple[str | Path, ...] = (),
) -> tuple[PromptSurfacePreparer, _CommandServiceStub]:
    service = _CommandServiceStub(
        prompt_resolution=prompt_resolution,
        builtin_resolution=builtin_resolution,
    )
    preparer = PromptSurfacePreparer(
        command_service=service,
        skill_roots_provider=lambda: skill_roots,
    )
    return preparer, service


def _make_prompt_command(
    *,
    name: str = "doit",
    allowed_tools: tuple[str, ...] = (),
    model: str | None = None,
    effort: str | None = None,
) -> PromptCommand:
    return PromptCommand(
        name=name,
        body="Do the thing.",
        path=Path(f"/tmp/{name}.md"),
        description="test",
        allowed_tools=allowed_tools,
        model=model,
        effort=effort,
    )


def _make_skill(
    *,
    name: str = "review",
    user_invocable: bool = True,
    allowed_tools: tuple[str, ...] = (),
    model: str | None = None,
    body: str = "Review the code.",
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        body=body,
        path=Path(f"/tmp/{name}/SKILL.md"),
        description="test",
        allowed_tools=allowed_tools,
        model=model,
        user_invocable=user_invocable,
    )


def _make_builtin(
    *,
    name: str = "compact",
    allowed_tools: tuple[str, ...] = (),
    model: str | None = None,
    effort: str | None = None,
) -> BuiltinCommand:
    return BuiltinCommand(
        name=name,
        description="test",
        allowed_tools=allowed_tools,
        model=model,
        effort=effort,
    )


# ---------------------------------------------------------------------------
# Non-slash messages
# ---------------------------------------------------------------------------


def test_prepare_returns_plain_preparation_for_non_slash_message() -> None:
    preparer, service = _preparer()

    preparation = preparer.prepare(_request("hello world"), _context())

    assert preparation.slash_reminder is None
    assert preparation.slash_metadata is None
    assert preparation.context_reminders == []
    assert preparation.browser_target is None
    # Neither resolver is consulted for non-slash messages.
    assert service.prompt_calls == []
    assert service.builtin_calls == []


# ---------------------------------------------------------------------------
# Prompt-command routing
# ---------------------------------------------------------------------------


def test_prepare_routes_prompt_command_with_overrides() -> None:
    command = _make_prompt_command(
        name="ship",
        allowed_tools=("git", "bash"),
        model="big-model",
        effort="high",
    )
    resolution = SlashCommandResolution(
        command=command, raw_arguments="now", expanded_prompt="Ship it."
    )
    preparer, service = _preparer(prompt_resolution=resolution)

    preparation = preparer.prepare(
        _request("/ship now", allowed_tools=["git"]),
        _context(),
    )

    assert service.prompt_calls == [("/ship now", "/home/user/MyProject")]
    # Resolution overrides feed into the prepared request.
    assert preparation.request.allowed_tools == sorted({"git", "bash"})
    assert preparation.request.model == "big-model"
    assert preparation.request.reasoning_level == "high"
    assert preparation.slash_reminder is not None
    assert "Ship it." in preparation.slash_reminder
    # Builtin resolver is not consulted once prompt path wins.
    assert service.builtin_calls == []


def test_prepare_prompt_command_carries_user_metadata() -> None:
    command = _make_prompt_command(name="ship")
    resolution = SlashCommandResolution(
        command=command, raw_arguments="now", expanded_prompt="Ship it."
    )
    preparer, _ = _preparer(prompt_resolution=resolution)

    preparation = preparer.prepare(_request("/ship now"), _context())
    user_metadata = preparer.user_message_metadata(preparation)

    assert "slash_command" in user_metadata
    assert user_metadata["slash_command"]["arguments"] == "now"
    assert user_metadata["slash_command"]["name"] == "ship"


# ---------------------------------------------------------------------------
# Skill routing
# ---------------------------------------------------------------------------


def test_prepare_routes_user_invocable_skill_with_overrides() -> None:
    skill = _make_skill(
        name="review",
        allowed_tools=("bash",),
        model="skill-model",
        body="Review checklist:\n1. tests\n2. types",
    )
    preparer, service = _preparer()

    with patch(
        "personagent.application.use_cases.chat.prompt_surfaces.find_skill",
        return_value=skill,
    ), patch(
        "personagent.application.use_cases.chat.prompt_surfaces.is_skill_enabled",
        return_value=True,
    ):
        preparation = preparer.prepare(_request("/review src/"), _context())

    assert preparation.request.allowed_tools == ["bash"]
    assert preparation.request.model == "skill-model"
    assert preparation.slash_reminder is not None
    assert "Review checklist:" in preparation.slash_reminder
    assert "src/" in preparation.slash_reminder
    assert preparation.slash_metadata["arguments"] == "src/"
    # Skill path doesn't fall through to the builtin resolver.
    assert service.builtin_calls == []


def test_prepare_raises_for_disabled_skill() -> None:
    skill = _make_skill(name="review")
    preparer, _ = _preparer()

    with patch(
        "personagent.application.use_cases.chat.prompt_surfaces.find_skill",
        return_value=skill,
    ), patch(
        "personagent.application.use_cases.chat.prompt_surfaces.is_skill_enabled",
        return_value=False,
    ), pytest.raises(ValueError, match="Skill is disabled"):
        preparer.prepare(_request("/review"), _context())


def test_prepare_falls_through_to_builtin_when_skill_is_not_user_invocable() -> None:
    skill = _make_skill(name="autodebug", user_invocable=False)
    builtin = _make_builtin(name="autodebug", allowed_tools=("bash",))
    resolution = BuiltinCommandResolution(command=builtin, raw_arguments="")
    preparer, service = _preparer(builtin_resolution=resolution)

    with patch(
        "personagent.application.use_cases.chat.prompt_surfaces.find_skill",
        return_value=skill,
    ), patch(
        "personagent.application.use_cases.chat.prompt_surfaces.is_skill_enabled",
        return_value=True,
    ):
        preparation = preparer.prepare(_request("/autodebug"), _context())

    # Builtin resolver was consulted and the builtin's overrides won.
    assert service.builtin_calls == ["/autodebug"]
    assert preparation.request.allowed_tools == ["bash"]


# ---------------------------------------------------------------------------
# Builtin routing
# ---------------------------------------------------------------------------


def test_prepare_routes_builtin_when_no_prompt_or_skill_match() -> None:
    builtin = _make_builtin(
        name="compact",
        allowed_tools=("bash",),
        effort="medium",
    )
    resolution = BuiltinCommandResolution(command=builtin, raw_arguments="")
    preparer, _ = _preparer(builtin_resolution=resolution)

    with patch(
        "personagent.application.use_cases.chat.prompt_surfaces.find_skill",
        return_value=None,
    ):
        preparation = preparer.prepare(_request("/compact"), _context())

    assert preparation.request.allowed_tools == ["bash"]
    assert preparation.request.reasoning_level == "medium"
    # Builtin source tag is set in metadata so telemetry can
    # distinguish builtin from user-shipped commands.
    assert preparation.slash_metadata.get("source") == "builtin"


def test_prepare_raises_for_unknown_slash_command() -> None:
    preparer, _ = _preparer()

    with patch(
        "personagent.application.use_cases.chat.prompt_surfaces.find_skill",
        return_value=None,
    ), pytest.raises(ValueError, match="Unknown slash command"):
        preparer.prepare(_request("/nope"), _context())


# ---------------------------------------------------------------------------
# apply_surface_overrides
# ---------------------------------------------------------------------------


def test_apply_surface_overrides_returns_same_request_when_no_change() -> None:
    preparer, _ = _preparer()
    request = _request(allowed_tools=["bash"], reasoning_level="medium")

    out = preparer.apply_surface_overrides(
        request, allowed_tools=("bash",), model="inherit", effort="medium"
    )

    # No change -> exact same request reference, not a copy.
    assert out is request


def test_apply_surface_overrides_wildcard_clears_allowlist() -> None:
    preparer, _ = _preparer()
    request = _request(allowed_tools=["bash", "read"])

    out = preparer.apply_surface_overrides(request, allowed_tools=("*",))

    assert out.allowed_tools is None


def test_apply_surface_overrides_unions_allowed_tools() -> None:
    preparer, _ = _preparer()
    request = _request(allowed_tools=["bash"])

    out = preparer.apply_surface_overrides(
        request, allowed_tools=("git", "bash")
    )

    assert out.allowed_tools == sorted({"bash", "git"})


def test_apply_surface_overrides_seeds_allowlist_when_request_has_none() -> None:
    preparer, _ = _preparer()
    request = _request()  # allowed_tools defaults to None

    out = preparer.apply_surface_overrides(
        request, allowed_tools=("bash", "git")
    )

    assert out.allowed_tools == ["bash", "git"]


def test_apply_surface_overrides_ignores_invalid_effort() -> None:
    preparer, _ = _preparer()
    request = _request(reasoning_level="medium")

    out = preparer.apply_surface_overrides(request, effort="invalid")

    assert out.reasoning_level == "medium"


def test_apply_surface_overrides_normalizes_effort() -> None:
    preparer, _ = _preparer()
    request = _request(reasoning_level="medium")

    out = preparer.apply_surface_overrides(request, effort="  HIGH  ")

    assert out.reasoning_level == "high"


def test_apply_surface_overrides_inherit_model_is_noop() -> None:
    preparer, _ = _preparer()
    request = _request(model="test-model")

    out = preparer.apply_surface_overrides(request, model="  Inherit  ")

    assert out.model == "test-model"


# ---------------------------------------------------------------------------
# Context attachments / browser target
# ---------------------------------------------------------------------------


def test_prepare_extracts_browser_target_from_attachment_metadata() -> None:
    preparer, _ = _preparer()
    attachment = {
        "type": "browser_tab",
        "browser_id": "browser-1",
        "page_id": "page-9",
        "url": "https://example.com",
        "title": "Example",
    }

    preparation = preparer.prepare(
        _request("hello", context_attachments=[attachment]),
        _context(),
    )

    assert preparation.context_attachment_metadata, (
        "resolve_context_attachments should have surfaced the browser tab"
    )
    assert preparation.context_attachment_metadata[0]["type"] == "browser_tab"
    # Browser target gets normalized out of the attachment list.
    assert preparation.browser_target is not None
    assert preparation.browser_target["browser_id"] == "browser-1"
    assert preparation.browser_target["page_id"] == "page-9"


def test_prepare_falls_through_attachments_for_slash_command() -> None:
    """Slash commands keep context attachments stamped on the preparation."""

    command = _make_prompt_command(name="ship")
    resolution = SlashCommandResolution(
        command=command, raw_arguments="", expanded_prompt="Ship it."
    )
    preparer, _ = _preparer(prompt_resolution=resolution)
    attachment = {
        "type": "browser_tab",
        "browser_id": "browser-1",
        "page_id": "page-9",
        "url": "https://example.com",
    }

    preparation = preparer.prepare(
        _request("/ship", context_attachments=[attachment]),
        _context(),
    )

    assert preparation.slash_reminder is not None
    # Attachments survive the command route -- they're appended, not
    # replaced, so both surfaces feed into the system prompt.
    assert preparation.context_attachment_metadata
    assert preparation.browser_target is not None
