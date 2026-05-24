"""Prompt-package assembly extracted from ``chat_completion.py``.

After the surrounding pipeline has resolved the system context, recalled
relevant memories, and prepared any slash-command / context-attachment
surfaces, the chat use case still has to produce the materialized
system prompt (and bookkeeping metadata) that goes to the LLM. The
legacy ``_build_prompt_package`` orchestrated:

* Prompt-profile analysis (with the ``llama`` / ``zenmux`` auto-mode
  fallback and the no-analyzer branch that runs the analyzer with a
  ``None`` provider).
* Available-tool inventory (schema names + ``ToolDefinition`` list +
  parallel-tool support detection).
* Slash command / skill discovery against the current workspace.
* Session-memory lookup.
* Runtime reminders from prompt preparation, browser cooperation, and
  shared-browser-workspace state.
* Final :class:`PromptBuilder.build` call plus the custom-system-prompt
  append, the user-context fold, and the 25+ memory_* metadata fields
  that downstream layers (UI, telemetry) read from.

Pulling all of that into :class:`PromptPackageBuilder` keeps the chat
use case slim and gives every prompt-package contributor one named
home. The class is stateless and safe to share across requests --
everything it needs is passed via :meth:`build`.

Backward compatibility: the public output type is still
:class:`~personagent.application.use_cases.chat.state.PromptPackage`,
so all downstream callers
(``_prepare_messages_for_llm``, ``_enforce_provider_data_policy``, the
``preview_prompt`` endpoint, etc.) keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.services import SessionMemoryService
from personagent.application.services.browser_cooperation import (
    browser_agent_context_reminder,
    shared_browser_workspace_reminder,
)
from personagent.application.tools import ToolRegistry
from personagent.application.use_cases.chat.helpers import (
    browser_target_reminder as _browser_target_reminder,
)
from personagent.application.use_cases.chat.state import (
    PromptPackage,
    PromptPreparation,
)
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.models.conversation import Conversation, Role
from personagent.domain.prompts.commands import CommandRegistry
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.domain.prompts.services.agent_state_resolver import AgentStateResolver
from personagent.domain.prompts.services.prompt_builder import estimate_text_tokens
from personagent.domain.prompts.skills import (
    SkillDefinition,
    discover_enabled_skills,
)
from personagent.domain.tools import ToolDefinition


class PromptPackageBuilder:
    """Assemble the full :class:`PromptPackage` for a single chat turn.

    All collaborators are captured at construction; the only per-call
    inputs are the request, the conversation, the resolved context
    build result, the schema-tool list, the prompt preparation, and
    the recalled memories. ``session_memory_service`` and
    ``prompt_context_analyzer`` are optional -- when ``None``, the
    corresponding lookup is skipped exactly as the legacy method did.

    ``skill_roots_provider`` is a callable rather than a snapshotted
    tuple so the use case keeps ownership of its
    :class:`ToolRuntimeConfig` (the roots could in principle vary
    across requests). This mirrors the contract already used by
    :class:`PromptSurfacePreparer`.

    Concurrency: stateless. Safe to share across requests.
    """

    def __init__(
        self,
        *,
        prompt_builder: PromptBuilder,
        prompt_context_analyzer: PromptContextAnalyzer | None,
        agent_state_resolver: AgentStateResolver,
        command_registry: CommandRegistry,
        tool_registry: ToolRegistry | None,
        session_memory_service: SessionMemoryService | None,
        skill_roots_provider: Callable[[], tuple[str | Path, ...]],
    ) -> None:
        self._prompt_builder = prompt_builder
        self._prompt_context_analyzer = prompt_context_analyzer
        self._agent_state_resolver = agent_state_resolver
        self._command_registry = command_registry
        self._tool_registry = tool_registry
        self._session_memory_service = session_memory_service
        self._skill_roots_provider = skill_roots_provider

    # ---- Public API -----------------------------------------------------

    async def build(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        context_result: ContextBuildResult,
        tools: list[dict[str, Any]],
        preparation: PromptPreparation | None = None,
        relevant_memories: list[str] | None = None,
        memory_trace: dict[str, Any] | None = None,
    ) -> PromptPackage:
        """Build the materialized prompt package for ``request``.

        Side effects (preserved verbatim from the legacy method):

        * Reads ``conversation.metadata['_operational_memory_prompt']``
          to populate the 13 ``memory_*`` metadata fields.
        * Reads ``conversation.metadata['context_compaction']`` to flag
          the agent-state resolver that the context was just compacted.
        * Reads ``conversation.metadata`` for shared-browser-workspace
          and browser cooperation reminders.
        """

        schema_tool_names = self._available_tool_names(tools)
        tool_definitions = self._prompt_tool_definitions(request)
        prompt_tool_names = (
            [definition.name for definition in tool_definitions] or schema_tool_names
        )
        workspace_root = context_result.system_context.workspace_root
        prompt_context_size_chars = context_result.total_context_size + sum(
            len(message.content or "") for message in conversation.messages
        )
        prompt_profile = await self._analyze_prompt_profile(
            request,
            available_tools=prompt_tool_names,
            workspace_root=workspace_root,
            context_size_chars=prompt_context_size_chars,
            conversation_message_count=len(conversation.messages),
        )
        commands = self._command_registry.list_commands(workspace_root)
        skills = self._skill_inventory(context_result)
        session_memory = (
            self._session_memory_service.load(str(conversation.id))
            if self._session_memory_service is not None
            else None
        )
        runtime_reminders: list[str] = []
        if preparation and preparation.slash_reminder:
            runtime_reminders.append(preparation.slash_reminder)
        if preparation:
            runtime_reminders.extend(preparation.context_reminders)
            target_context = _browser_target_reminder(preparation.browser_target)
            if target_context:
                runtime_reminders.append(target_context)
        shared_browser_context = shared_browser_workspace_reminder(conversation.metadata)
        if shared_browser_context:
            runtime_reminders.append(shared_browser_context)
        browser_context = browser_agent_context_reminder(conversation.metadata)
        if browser_context:
            runtime_reminders.append(browser_context)
        agent_state_profile = self._agent_state_resolver.resolve(
            message=request.message,
            prompt_profile=prompt_profile,
            available_tools=prompt_tool_names,
            conversation_metadata=conversation.metadata,
            context_size_chars=prompt_context_size_chars,
            conversation_message_count=len(conversation.messages),
            recent_tool_names=self._conversation_recent_tool_names(conversation),
            recent_error_count=self._conversation_recent_error_count(conversation),
            has_session_memory=bool(session_memory and session_memory.strip()),
            has_relevant_memories=bool(relevant_memories),
            context_compacted=bool(conversation.metadata.get("context_compaction")),
        )
        built_prompt = await self._prompt_builder.build(
            context_result.system_context,
            context_result.user_context,
            available_tools=schema_tool_names,
            prompt_mode=request.prompt_mode,
            prompt_profile=prompt_profile,
            agent_state_profile=agent_state_profile,
            user_message=request.message,
            conversation_id=str(conversation.id),
            available_tool_definitions=tool_definitions,
            command_inventory=commands,
            skill_inventory=skills,
            session_memory=session_memory,
            runtime_reminders=runtime_reminders,
            relevant_memories=relevant_memories,
            provider=request.provider,
            model=request.model,
            supports_parallel_tool_calls=self._supports_parallel_tool_calls(request, tools),
        )
        system_prompt = built_prompt.content
        user_context_message = built_prompt.user_context_message
        sections_used = list(built_prompt.sections_used)
        has_custom_system_prompt = bool(request.system_prompt and request.system_prompt.strip())
        if has_custom_system_prompt:
            system_prompt = (
                f"{system_prompt}\n\n"
                "# Custom System Instructions\n\n"
                "The caller provided the following additional system instructions. "
                "Apply them inside the PersonAgent dynamic prompt architecture above; "
                "they do not replace the default dynamic prompt, tool policy, agent-state policy, "
                "context policy, or safety constraints.\n\n"
                f"{request.system_prompt.strip()}"
            )
            sections_used.append("custom_system_instructions")
        if user_context_message:
            system_prompt = (
                f"{system_prompt}\n\n"
                "# User Context and Runtime Reminders\n\n"
                f"{self._clean_user_context_for_system_prompt(user_context_message)}"
            )
            sections_used.append("user_context_runtime")
        final_prompt_tokens = estimate_text_tokens(system_prompt)
        memory_metadata = conversation.metadata.get("_operational_memory_prompt") or {}
        return PromptPackage(
            system_prompt=system_prompt,
            user_context_message=None,
            metadata={
                "prompt_mode": built_prompt.metadata.get("prompt_mode"),
                "requested_prompt_mode": built_prompt.metadata.get("requested_prompt_mode"),
                "prompt_analysis_source": built_prompt.metadata.get("prompt_analysis_source"),
                "prompt_analysis_confidence": built_prompt.metadata.get(
                    "prompt_analysis_confidence"
                ),
                "prompt_profile": built_prompt.metadata.get("prompt_profile"),
                "prompt_surfaces_used": built_prompt.metadata.get("prompt_surfaces_used"),
                "agent_states": built_prompt.metadata.get("agent_states"),
                "agent_state_source": built_prompt.metadata.get("agent_state_source"),
                "agent_state_reason": built_prompt.metadata.get("agent_state_reason"),
                "agent_state_confidence": built_prompt.metadata.get("agent_state_confidence"),
                "agent_state_profile": built_prompt.metadata.get("agent_state_profile"),
                "state_sections_used": built_prompt.metadata.get("state_sections_used") or [],
                "prompt_sections_used": sections_used,
                "dynamic_sections_used": list(
                    built_prompt.metadata.get("dynamic_sections_used") or ()
                ),
                "provider_data_boundary": built_prompt.metadata.get("provider_data_boundary"),
                "line_count": len(system_prompt.splitlines()),
                "char_count": len(system_prompt),
                "slash_command": preparation.slash_metadata if preparation else None,
                "context_attachments": (
                    preparation.context_attachment_metadata if preparation else []
                ),
                "context_attachment_count": (
                    len(preparation.context_attachment_metadata) if preparation else 0
                ),
                "context_source": context_result.metadata.get("source"),
                "prompt_tokens_estimated": final_prompt_tokens,
                "prompt_build_duration_ms": built_prompt.build_duration_ms,
                "memory_budget_tokens": memory_metadata.get("memory_budget_tokens"),
                "memory_budget_used": memory_metadata.get("memory_budget_used"),
                "memory_items_injected": memory_metadata.get("memory_items_injected"),
                "memory_items_omitted": memory_metadata.get("memory_items_omitted"),
                "memory_latency_ms": memory_metadata.get("memory_latency_ms"),
                "memory_filters_applied": memory_metadata.get("memory_filters_applied"),
                "memory_recall_scope": memory_metadata.get("memory_recall_scope"),
                "memory_query_intent": memory_metadata.get("memory_query_intent"),
                "memory_candidate_count": memory_metadata.get("memory_candidate_count"),
                "memory_discarded_candidates": memory_metadata.get(
                    "memory_discarded_candidates"
                ),
                "memory_included_reasons": memory_metadata.get("memory_included_reasons"),
                "memory_ranking_breakdown": memory_metadata.get("memory_ranking_breakdown"),
                "memory_token_usage": memory_metadata.get("memory_token_usage"),
                "memory_trace": memory_trace,
                "has_custom_system_prompt": has_custom_system_prompt,
                "custom_system_prompt_policy": "append_to_dynamic_system_prompt",
                "user_context_in_system_prompt": bool(user_context_message),
                "has_browser_cooperation_context": bool(browser_context),
                "has_shared_browser_workspace_context": bool(shared_browser_context),
                "browser_target": preparation.browser_target if preparation else None,
            },
        )

    # ---- Internal helpers ----------------------------------------------

    async def _analyze_prompt_profile(
        self,
        request: ChatRequestDTO,
        *,
        available_tools: list[str],
        workspace_root: str,
        context_size_chars: int = 0,
        conversation_message_count: int = 0,
    ) -> Any:
        if request.provider in {"llama", "zenmux"} and request.prompt_mode == "auto":
            from personagent.domain.prompts.services.context_analyzer import (
                fallback_prompt_profile,
            )

            return fallback_prompt_profile(
                message=request.message,
                available_tools=available_tools,
                workspace_root=workspace_root,
                context_size_chars=context_size_chars,
                reason=f"{request.provider}_auto_prompt_analysis_skipped",
            )
        if self._prompt_context_analyzer is None:
            from personagent.domain.prompts.services.context_analyzer import (
                fallback_prompt_profile,
            )

            if request.prompt_mode != "auto":
                return await PromptContextAnalyzer(None).analyze(
                    message=request.message,
                    requested_mode=request.prompt_mode,
                    available_tools=available_tools,
                    workspace_root=workspace_root,
                    model=request.model,
                    provider=request.provider,
                    context_size_chars=context_size_chars,
                    conversation_message_count=conversation_message_count,
                )
            return fallback_prompt_profile()
        return await self._prompt_context_analyzer.analyze(
            message=request.message,
            requested_mode=request.prompt_mode,
            available_tools=available_tools,
            workspace_root=workspace_root,
            model=request.model,
            provider=request.provider,
            context_size_chars=context_size_chars,
            conversation_message_count=conversation_message_count,
        )

    def _prompt_tool_definitions(self, request: ChatRequestDTO) -> list[ToolDefinition]:
        if not request.tools_enabled or self._tool_registry is None:
            return []
        allowed_tools = set(request.allowed_tools) if request.allowed_tools else None
        return [
            tool.definition
            for tool in self._tool_registry.list_enabled(allowed_tools, include_deferred=True)
        ]

    def _skill_inventory(self, context_result: ContextBuildResult) -> list[SkillDefinition]:
        workspace_root = context_result.system_context.workspace_root
        cwd = context_result.system_context.cwd or workspace_root
        # ``discover_enabled_skills`` is correctly annotated in the
        # domain layer, but its loader helpers pass through ``Any`` so
        # mypy --strict treats the call site as ``Any``. The cast keeps
        # the strict gate green without changing runtime behavior.
        return cast(
            list[SkillDefinition],
            discover_enabled_skills(
                workspace_root=workspace_root,
                cwd=cwd,
                extra_roots=self._skill_roots_provider(),
            ),
        )

    def _supports_parallel_tool_calls(
        self,
        request: ChatRequestDTO,
        tools: list[dict[str, Any]],
    ) -> bool:
        if not request.tools_enabled:
            return False
        if request.provider == "codex":
            return True
        return len(tools) > 1

    @staticmethod
    def _available_tool_names(tools: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict):
                name = function.get("name")
                if isinstance(name, str) and name:
                    names.append(name)
        return names

    @staticmethod
    def _conversation_recent_tool_names(conversation: Conversation) -> list[str]:
        """Return recent tool names visible in the conversation transcript."""

        names: list[str] = []
        for message in conversation.messages[-16:]:
            if message.role == Role.ASSISTANT and message.tool_calls:
                for raw_call in message.tool_calls:
                    function = raw_call.get("function") if isinstance(raw_call, dict) else None
                    name = function.get("name") if isinstance(function, dict) else None
                    if isinstance(name, str) and name and name not in names:
                        names.append(name)
            if message.role == Role.TOOL:
                name = message.metadata.get("tool_name")
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _conversation_recent_error_count(conversation: Conversation) -> int:
        """Return a compact count of recent tool/runtime error signals."""

        count = 1 if conversation.metadata.get("last_request_error") else 0
        for message in conversation.messages[-16:]:
            if message.role == Role.TOOL and (
                message.metadata.get("is_error")
                or message.metadata.get("status") in {"error", "permission_required"}
            ):
                count += 1
            finish_reason = message.metadata.get("finish_reason")
            if finish_reason in {"error", "empty_model_response"}:
                count += 1
        return count

    @staticmethod
    def _clean_user_context_for_system_prompt(content: str) -> str:
        """Remove legacy reminder tags before folding user context into system."""

        cleaned = content.strip()
        start_tag = "<system-reminder>"
        end_tag = "</system-reminder>"
        if cleaned.startswith(start_tag) and cleaned.endswith(end_tag):
            cleaned = cleaned[len(start_tag) : -len(end_tag)].strip()
        return cleaned


__all__ = ["PromptPackageBuilder"]
