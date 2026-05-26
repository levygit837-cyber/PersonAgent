"""Prompt-surface preparation extracted from ``chat_completion.py``.

Before the chat use case can build the system prompt and message the
LLM, it has to decide *which* surfaces are active for the current
turn:

* **Slash commands**: ``/<name>`` invocations may resolve to a user
  prompt command (loaded from disk), a builtin command, or a
  user-invocable skill. Each route produces a different reminder and
  may override tool / model / reasoning-effort defaults.

* **Context attachments**: every turn may carry one or more
  ``ContextAttachmentSpec`` entries (browser windows, file paths,
  selections) that turn into reminder blocks the model sees alongside
  the system prompt.

* **Browser target**: pulled out of the context attachments so the
  turn knows which browser window/tab to operate on.

Pulling this surface into :class:`PromptSurfacePreparer` keeps the
chat use case smaller and gives every prompt-surface override rule
one named home. The class is stateless and safe to share across
requests -- everything it needs is passed in via :meth:`prepare`.

Backward compatibility: the public output type is the same
:class:`~personagent.application.use_cases.chat.state.PromptPreparation`
the use case already passes around, so all downstream callers
(``_build_prompt_package``, ``_user_message_metadata``, etc.) keep
working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.helpers import (
    browser_target_from_context_attachments,
)
from personagent.application.use_cases.chat.messaging.state import PromptPreparation
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.prompts.commands import (
    BuiltinCommandResolution,
    CommandService,
    SlashCommandResolution,
    parse_slash_invocation,
)
from personagent.domain.prompts.context_attachments import resolve_context_attachments
from personagent.domain.prompts.skills import (
    SkillDefinition,
    find_skill,
    is_skill_enabled,
)

# Reasoning levels honored by ``apply_surface_overrides``. Anything
# outside this set is treated as "no override" so callers can't
# silently pin the model to a non-existent effort level.
_ALLOWED_REASONING_LEVELS: frozenset[str] = frozenset(
    {"low", "medium", "high", "xhigh", "max"}
)


class PromptSurfacePreparer:
    """Resolve the prompt-surface state for a single chat turn.

    Takes one collaborator (:class:`CommandService`) plus a callable
    that returns the extra skill-search roots. The callable indirection
    lets the use case keep ownership of its ``ToolRuntimeConfig`` and
    derive skill roots from it lazily; passing a plain ``tuple`` would
    snapshot the value at construction time, which is wrong when the
    runtime config can change between requests (it can't today, but
    cheap to support).

    Concurrency: stateless. Safe to share across requests.
    """

    def __init__(
        self,
        *,
        command_service: CommandService,
        skill_roots_provider: Callable[[], tuple[str | Path, ...]],
    ) -> None:
        self._command_service = command_service
        self._skill_roots_provider = skill_roots_provider

    # ---- Public API -----------------------------------------------------

    def prepare(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
    ) -> PromptPreparation:
        """Produce the :class:`PromptPreparation` for ``request``.

        Routing rules (preserved verbatim from the legacy
        ``_prepare_prompt_surfaces``):

        1. If the message doesn't start with a slash, return a
           preparation with just context attachments.
        2. Try a user-defined prompt command, then a user-invocable
           skill, then a builtin command -- first match wins.
        3. Unknown slash command -> ``ValueError`` (lets the caller
           surface a useful error to the UI).
        """

        workspace_root = context_result.system_context.workspace_root
        context_cwd = context_result.system_context.cwd or workspace_root
        skill_roots = self._skill_roots_provider()

        attachment_context = resolve_context_attachments(
            request.context_attachments,
            workspace_root=workspace_root,
            cwd=context_cwd,
            extra_skill_roots=skill_roots,
        )

        parsed = parse_slash_invocation(request.message)
        if parsed is None:
            return PromptPreparation(
                request=request,
                context_reminders=attachment_context.reminders,
                context_attachment_metadata=attachment_context.metadata,
                browser_target=browser_target_from_context_attachments(
                    attachment_context.metadata
                ),
            )

        prompt_resolution = self._command_service.resolve_prompt_command(
            request.message, workspace_root
        )
        if prompt_resolution is not None:
            return self._with_context_attachments(
                self._from_command(request, prompt_resolution),
                attachment_context.reminders,
                attachment_context.metadata,
            )

        skill = find_skill(
            parsed[0],
            workspace_root=workspace_root,
            cwd=context_cwd,
            extra_roots=skill_roots,
        )
        if skill is not None:
            if not is_skill_enabled(
                skill,
                workspace_root=workspace_root,
                cwd=context_cwd,
                extra_roots=skill_roots,
            ):
                raise ValueError(f"Skill is disabled: /{parsed[0]}")
            if skill.user_invocable:
                return self._with_context_attachments(
                    self._from_skill(request, skill, parsed[1]),
                    attachment_context.reminders,
                    attachment_context.metadata,
                )

        builtin = self._command_service.resolve_builtin(request.message)
        if builtin is not None:
            return self._with_context_attachments(
                self._from_builtin(request, builtin),
                attachment_context.reminders,
                attachment_context.metadata,
            )

        raise ValueError(f"Unknown slash command: /{parsed[0]}")

    def user_message_metadata(
        self, preparation: PromptPreparation
    ) -> dict[str, Any]:
        """Bundle the metadata that travels with the *user* message.

        Returned dict is meant for ``Message.metadata`` -- the system
        prompt's own metadata is built inside ``_build_prompt_package``.
        """

        metadata: dict[str, Any] = {}
        if preparation.slash_metadata:
            metadata["slash_command"] = preparation.slash_metadata
        if preparation.context_attachment_metadata:
            metadata["context_attachments"] = preparation.context_attachment_metadata
        return metadata

    # ---- Surface-specific builders --------------------------------------

    def _from_command(
        self,
        request: ChatRequestDTO,
        resolution: SlashCommandResolution,
    ) -> PromptPreparation:
        command = resolution.command
        prepared = self.apply_surface_overrides(
            request,
            allowed_tools=command.allowed_tools,
            model=command.model,
            effort=command.effort,
        )
        return PromptPreparation(
            request=prepared,
            slash_reminder=resolution.reminder(),
            slash_metadata=resolution.metadata(),
        )

    def _from_builtin(
        self,
        request: ChatRequestDTO,
        resolution: BuiltinCommandResolution,
    ) -> PromptPreparation:
        command = resolution.command
        prepared = self.apply_surface_overrides(
            request,
            allowed_tools=command.allowed_tools,
            model=command.model,
            effort=command.effort,
        )
        metadata = resolution.metadata()
        # Mark builtins explicitly so downstream telemetry can
        # distinguish "user shipped this command" from "system ships
        # this command".
        metadata["source"] = "builtin"
        return PromptPreparation(
            request=prepared,
            slash_reminder=resolution.reminder(),
            slash_metadata=metadata,
        )

    def _from_skill(
        self,
        request: ChatRequestDTO,
        skill: SkillDefinition,
        raw_arguments: str,
    ) -> PromptPreparation:
        prepared = self.apply_surface_overrides(
            request,
            allowed_tools=skill.allowed_tools,
            model=skill.model,
            effort=None,
        )
        reminder = (
            "# Slash Skill Context\n\n"
            f"Skill: {skill.slash_name}\n"
            f"Arguments: {raw_arguments or '(none)'}\n"
            f"Source: {skill.path}\n\n"
            "The user invoked a user-invocable skill. Treat the skill body below as "
            "procedural guidance for this turn and load additional resources only when needed.\n\n"
            f"{skill.body.strip()}"
        )
        metadata = skill.to_inventory_dict()
        metadata["arguments"] = raw_arguments
        return PromptPreparation(
            request=prepared,
            slash_reminder=reminder,
            slash_metadata=metadata,
        )

    def _with_context_attachments(
        self,
        preparation: PromptPreparation,
        reminders: list[str],
        metadata: list[dict[str, Any]],
    ) -> PromptPreparation:
        # Mutates ``preparation`` in place to preserve the legacy
        # behavior -- callers don't expect a copy. ``PromptPreparation``
        # is the workhorse container used by the turn loop, not an
        # immutable value type.
        preparation.context_reminders = (
            list(preparation.context_reminders) + list(reminders)
        )
        preparation.context_attachment_metadata = list(metadata)
        preparation.browser_target = browser_target_from_context_attachments(metadata)
        return preparation

    # ---- Override math ---------------------------------------------------

    def apply_surface_overrides(
        self,
        request: ChatRequestDTO,
        *,
        allowed_tools: tuple[str, ...] = (),
        model: str | None = None,
        effort: str | None = None,
    ) -> ChatRequestDTO:
        """Apply slash-command / skill overrides on top of a request.

        Returns the same ``request`` when no override changes anything
        (saves a ``dataclasses.replace`` call per turn).

        Override rules:

        * ``allowed_tools`` containing ``"*"`` clears the allowlist
          entirely (skill wants everything).
        * Otherwise ``allowed_tools`` unions with the request's
          existing allowlist; passing only existing tools is a no-op.
        * ``effort`` outside the allowed set is ignored.
        * ``model`` set to ``"inherit"`` (case-insensitive) is a
          no-op so commands can opt out of forcing a specific model.
        """

        next_allowed_tools = request.allowed_tools
        if allowed_tools:
            if "*" in allowed_tools:
                next_allowed_tools = None
            elif next_allowed_tools:
                next_allowed_tools = sorted(
                    set(next_allowed_tools).union(allowed_tools)
                )
            else:
                next_allowed_tools = list(allowed_tools)

        normalized_effort = (effort or "").strip().lower()
        next_reasoning_level = request.reasoning_level
        if normalized_effort in _ALLOWED_REASONING_LEVELS:
            next_reasoning_level = normalized_effort

        next_model = request.model
        if model and model.strip() and model.strip().lower() != "inherit":
            next_model = model.strip()

        if (
            next_allowed_tools == request.allowed_tools
            and next_reasoning_level == request.reasoning_level
            and next_model == request.model
        ):
            return request
        return replace(
            request,
            allowed_tools=next_allowed_tools,
            reasoning_level=next_reasoning_level,
            model=next_model,
        )


__all__ = ["PromptSurfacePreparer"]
