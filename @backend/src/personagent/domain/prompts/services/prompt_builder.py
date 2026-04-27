"""Prompt builder service.

Este serviço monta o system prompt completo a partir das seções disponíveis,
aplicando contexto de sistema e usuário quando apropriado.
"""

from __future__ import annotations

import time
from hashlib import sha256
from typing import Any

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.prompts.commands import PromptCommand
from personagent.domain.prompts.models import (
    BuiltSystemPrompt,
    PromptMode,
    PromptProfile,
    SystemPromptParts,
    SystemPromptSection,
)
from personagent.domain.prompts.prompt import (
    PROMPT_DYNAMIC_BOUNDARY,
    get_default_prompt_sections,
    get_mode_prompt_section,
    normalize_prompt_mode,
    parallel_tool_use_section,
    provider_boundary_section,
    provider_data_boundary,
    todo_write_policy_section,
)
from personagent.domain.prompts.sections import (
    get_agent_sections,
    get_execution_sections,
    get_tool_sections,
)
from personagent.domain.prompts.sections.tool_prompts import get_rich_tool_prompt_sections
from personagent.domain.prompts.skills import SkillDefinition
from personagent.domain.prompts.surfaces import PromptSurfaceRegistry
from personagent.domain.tools import ToolDefinition


class PromptBuilder:
    """Monta o system prompt completo.

    Combina seções base, de ferramentas, execução e agente, aplicando
    contexto de sistema e usuário quando apropriado.
    """

    def __init__(
        self,
        permission_mode: str = "manual",
        enable_agent_sections: bool = True,
        surface_registry: PromptSurfaceRegistry | None = None,
    ) -> None:
        """Inicializa o builder.

        Args:
            permission_mode: Modo de permissão (auto, manual, ask).
            enable_agent_sections: Se False, omite seções específicas do agente.
        """
        self._permission_mode = permission_mode
        self._enable_agent_sections = enable_agent_sections
        self._surface_registry = surface_registry or PromptSurfaceRegistry()
        self._section_cache: dict[str, str] = {}

    async def build(
        self,
        system_context: SystemContext,
        user_context: UserContext,
        available_tools: list[str] | None = None,
        *,
        prompt_mode: str | None = "auto",
        prompt_profile: PromptProfile | None = None,
        user_message: str = "",
        conversation_id: str | None = None,
        available_tool_definitions: list[ToolDefinition] | None = None,
        command_inventory: list[PromptCommand] | None = None,
        skill_inventory: list[SkillDefinition] | None = None,
        session_memory: str | None = None,
        runtime_reminders: list[str] | None = None,
        relevant_memories: list[str] | None = None,
        provider: str = "llama",
        model: str = "local-model",
        supports_parallel_tool_calls: bool | None = None,
    ) -> BuiltSystemPrompt:
        """Monta o system prompt completo.

        Args:
            system_context: Contexto de sistema.
            user_context: Contexto de usuário.
            available_tools: Lista de ferramentas disponíveis (opcional).
            prompt_mode: writing, exploring, research, or auto.
            user_message: Mensagem usada para inferir prompt_mode quando auto.
            conversation_id: ID opcional usado em metadata/cache.

        Returns:
            BuiltSystemPrompt com o prompt montado.
        """
        start_time = time.time()
        normalized_mode = normalize_prompt_mode(prompt_mode)
        profile = self._resolve_profile(normalized_mode, prompt_profile)
        resolved_mode = profile.primary_mode
        all_tool_names = self._prompt_tool_names(available_tools, available_tool_definitions)
        can_use_todos = "TodoWrite" in all_tool_names
        can_use_parallel_tools = (
            bool(supports_parallel_tool_calls)
            or len(all_tool_names) > 1
        )

        # Obtém seções base
        base_sections = get_default_prompt_sections()

        # Obtém seções de ferramentas
        tool_sections = get_tool_sections(available_tools) + get_rich_tool_prompt_sections(
            available_tool_definitions,
            available_tools,
        )

        # Obtém seções de execução
        execution_sections = (provider_boundary_section(provider, model),)
        if can_use_todos:
            execution_sections += (todo_write_policy_section(),)
        if can_use_parallel_tools:
            execution_sections += (parallel_tool_use_section(),)
        execution_sections += get_execution_sections(self._permission_mode) + (
            self._context_lifecycle_section(),
        )

        # Obtém seções do agente
        agent_sections = tuple(get_mode_prompt_section(mode) for mode in profile.all_modes)
        if self._enable_agent_sections:
            agent_sections += get_agent_sections()
        agent_sections += self._command_sections(command_inventory)
        agent_sections += self._skill_sections(skill_inventory)
        if session_memory and session_memory.strip():
            agent_sections += (self._session_memory_section(session_memory),)
        if relevant_memories:
            agent_sections += (self._relevant_memories_section(relevant_memories),)

        # Cria SystemPromptParts
        parts = SystemPromptParts(
            base_sections=base_sections,
            tool_sections=tool_sections,
            execution_sections=execution_sections,
            agent_sections=agent_sections,
        )

        # Resolve seções
        cache_scope = self._cache_scope(
            system_context=system_context,
            available_tools=sorted(all_tool_names),
            prompt_mode=resolved_mode,
            provider=provider,
            model=model,
        )
        resolved_sections = await self._resolve_sections(parts, cache_scope)

        # Monta prompt completo
        content, dynamic_sections = self._assemble_system_prompt(
            resolved_sections,
            system_context,
        )
        user_context_message = self.build_user_context_message(user_context, runtime_reminders)
        resolved_section_names = tuple(section.name for section, _content in resolved_sections)
        surfaces_used = self._surfaces_used(
            section_names=resolved_section_names,
            runtime_reminders=runtime_reminders,
        )

        build_duration_ms = int((time.time() - start_time) * 1000)
        estimated_tokens = estimate_text_tokens(
            "\n\n".join(part for part in (content, user_context_message) if part)
        )
        line_count = len(content.splitlines())
        char_count = len(content)

        return BuiltSystemPrompt(
            content=content,
            user_context_message=user_context_message,
            sections_used=resolved_section_names,
            metadata={
                "permission_mode": self._permission_mode,
                "prompt_mode": resolved_mode,
                "requested_prompt_mode": normalized_mode,
                "provider": provider,
                "model": model,
                "provider_data_boundary": provider_data_boundary(provider),
                "prompt_analysis_source": profile.source,
                "prompt_analysis_confidence": profile.confidence,
                "prompt_profile": {
                    "primary_mode": profile.primary_mode,
                    "secondary_modes": list(profile.secondary_modes),
                    "intent": profile.intent,
                    "surface_hints": list(profile.surface_hints),
                    "confidence": profile.confidence,
                    "source": profile.source,
                    "requested_mode": profile.requested_mode,
                },
                "prompt_surfaces_used": surfaces_used,
                "has_claude_md": user_context.has_claude_md,
                "has_memory_files": user_context.has_memory_files,
                "has_session_memory": bool(session_memory and session_memory.strip()),
                "is_git_repo": system_context.git_status is not None,
                "dynamic_sections_used": dynamic_sections,
                "line_count": line_count,
                "char_count": char_count,
                "estimated_tokens": estimated_tokens,
                "cache_scope": cache_scope,
                "conversation_id": conversation_id,
            },
            build_duration_ms=build_duration_ms,
            estimated_tokens=estimated_tokens,
        )

    def _surfaces_used(
        self,
        *,
        section_names: tuple[str, ...],
        runtime_reminders: list[str] | None,
    ) -> list[str]:
        """Return the actual prompt surfaces present in this built prompt."""

        names: list[str] = []

        def add(name: str) -> None:
            if name not in names:
                names.append(name)

        sections = set(section_names)
        if sections.intersection(
            {
                "identity_and_objective",
                "work_management",
                "evidence_and_tool_use",
                "safety_and_user_work",
                "final_response_contract",
                "provider_data_boundary",
            }
        ):
            add("system")
        for mode in ("writing", "exploring", "research"):
            if f"mode_{mode}" in sections:
                add(f"mode:{mode}")
        if sections.intersection({"tool_usage", "file_operations", "shell"}):
            add("tool")
        if "tool_prompts" in sections:
            add("tool")
            add("tool_prompts")
        if "todo_write_policy" in sections:
            add("todo")
        if "parallel_tool_use" in sections:
            add("parallel_tool_use")
        if "command_inventory" in sections:
            add("command")
        if "skill_inventory" in sections:
            add("skill")
        if "session_memory" in sections:
            add("memory")
        if "relevant_memories" in sections:
            add("relevant_memory")
        if "context_lifecycle" in sections:
            add("context_lifecycle")
        if any(item.strip() for item in runtime_reminders or []):
            add("slash")
            add("reminder")
        return names

    def _prompt_tool_names(
        self,
        available_tools: list[str] | None,
        available_tool_definitions: list[ToolDefinition] | None,
    ) -> set[str]:
        names = {name for name in available_tools or [] if name}
        names.update(definition.name for definition in available_tool_definitions or [])
        return names

    async def _resolve_sections(
        self,
        parts: SystemPromptParts,
        cache_scope: str,
    ) -> list[tuple[SystemPromptSection, str]]:
        """Resolve todas as seções do prompt.

        Args:
            parts: SystemPromptParts com seções a resolver.

        Returns:
            Lista de strings com o conteúdo de cada seção.
        """
        resolved: list[tuple[SystemPromptSection, str]] = []

        for section in parts.all_sections():
            try:
                cache_key = f"{cache_scope}:{section.name}"
                if not section.cache_break and cache_key in self._section_cache:
                    content = self._section_cache[cache_key]
                else:
                    content = await self._resolve_section(section)
                    if content and not section.cache_break:
                        self._section_cache[cache_key] = content
                if content and content.strip():
                    resolved.append((section, content))
            except Exception:
                # Falha silenciosa na resolução de seção
                pass

        return resolved

    async def _resolve_section(self, section: Any) -> str | None:
        """Resolve uma única seção.

        Args:
            section: SystemPromptSection a resolver.

        Returns:
            Conteúdo da seção ou None se falhar.
        """
        result = section.compute()

        # Handle async compute functions
        if result is not None and hasattr(result, "__await__"):
            # It's a coroutine, await it
            try:
                result = await result
            except Exception:
                return None

        if isinstance(result, str):
            return result
        return None

    def _assemble_system_prompt(
        self,
        sections: list[tuple[SystemPromptSection, str]],
        system_context: SystemContext,
    ) -> tuple[str, tuple[str, ...]]:
        """Monta o prompt completo a partir das seções e contexto.

        Args:
            sections: Lista de seções resolvidas.
            system_context: Contexto de sistema.

        Returns:
            String com o system prompt e os nomes das seções dinâmicas.
        """
        parts: list[str] = []
        dynamic_sections: list[str] = []

        deferred_dynamic_parts: list[str] = []
        for section, content in sections:
            if section.cache_break:
                deferred_dynamic_parts.append(content)
                dynamic_sections.append(section.name)
            else:
                parts.append(content)

        parts.append(PROMPT_DYNAMIC_BOUNDARY)

        parts.extend(deferred_dynamic_parts)

        # Adiciona contexto de sistema se disponível
        system_context_str = self._format_system_context(system_context)
        if system_context_str:
            parts.append(f"\n# System Context\n\n{system_context_str}")
            dynamic_sections.append("system_context")

        return "\n\n".join(parts), tuple(dynamic_sections)

    def _resolve_profile(
        self,
        normalized_mode: PromptMode,
        prompt_profile: PromptProfile | None,
    ) -> PromptProfile:
        if normalized_mode != "auto":
            return PromptProfile(
                primary_mode=normalized_mode,  # type: ignore[arg-type]
                requested_mode=normalized_mode,
                confidence=1.0,
                source="override",
                intent="explicit prompt_mode override",
                surface_hints=("system", "mode", "tool", "memory", "next_step", "reminder"),
            )
        if prompt_profile is not None:
            return prompt_profile
        return PromptProfile(
            primary_mode="exploring",
            requested_mode="auto",
            confidence=0.0,
            source="fallback",
            intent="analysis unavailable",
            surface_hints=("system", "mode", "tool", "reminder"),
        )

    def _context_lifecycle_section(self) -> SystemPromptSection:
        def render() -> str:
            return """# Context Lifecycle Surfaces

- Prompt construction uses cacheable stable sections before the dynamic boundary and runtime sections after it.
- Session memory, slash command reminders, system context, and user context can change per turn and must be treated as current.
- Conversation compaction may replace older messages with a structured reminder. Use the reminder for continuity and recent messages for exact state.
- Next-step suggestions are generated outside the main answer and must not affect the final answer unless the user explicitly follows them."""

        return SystemPromptSection("context_lifecycle", render)

    def _command_sections(
        self,
        commands: list[PromptCommand] | None,
    ) -> tuple[SystemPromptSection, ...]:
        visible = [command for command in commands or [] if not command.disable_model_invocation]
        if not visible:
            return ()

        def render() -> str:
            lines = [
                "# Prompt Commands",
                "",
                "Markdown slash commands can provide reusable prompt instructions. If the user invokes one, the expanded command content appears as a runtime reminder.",
            ]
            for command in visible[:80]:
                detail = f"- {command.slash_name}: {command.description or 'Prompt command'}"
                if command.argument_hint:
                    detail += f" Args: {command.argument_hint}"
                if command.when_to_use:
                    detail += f" When: {command.when_to_use}"
                lines.append(detail)
            return "\n".join(lines)

        return (SystemPromptSection("command_inventory", render),)

    def _skill_sections(
        self,
        skills: list[SkillDefinition] | None,
    ) -> tuple[SystemPromptSection, ...]:
        visible = [skill for skill in skills or [] if skill.model_invocable]
        if not visible:
            return ()

        def render() -> str:
            lines = [
                "# Skill Inventory",
                "",
                "Skills are progressive-disclosure instruction packs. Load a skill with the Skill tool only when its description matches the current task.",
            ]
            for skill in visible[:100]:
                detail = f"- {skill.name}: {skill.description or 'Local skill'}"
                if skill.when_to_use:
                    detail += f" When: {skill.when_to_use}"
                if skill.user_invocable:
                    detail += f" User slash: {skill.slash_name}"
                lines.append(detail)
            return "\n".join(lines)

        return (SystemPromptSection("skill_inventory", render),)

    def _session_memory_section(self, memory: str) -> SystemPromptSection:
        def render() -> str:
            return (
                "# Session Memory\n\n"
                "The following memory was maintained for this conversation. Treat it as "
                "continuity context, not as a replacement for the latest user request.\n\n"
                f"{memory.strip()}"
            )

        return SystemPromptSection("session_memory", render, cache_break=True)

    def _relevant_memories_section(self, memories: list[str]) -> SystemPromptSection:
        def render() -> str:
            lines = [
                "# Relevant Memories",
                "",
                "The following memories were selected as relevant to the current query. "
                "Use them as context, but the user's latest request still defines the immediate task.",
                "",
            ]
            for i, memory in enumerate(memories, 1):
                if memory.strip():
                    lines.append(f"## Memory {i}")
                    lines.append(memory.strip())
                    lines.append("")
            return "\n".join(lines)

        return SystemPromptSection("relevant_memories", render, cache_break=True)

    def build_user_context_message(
        self,
        context: UserContext,
        runtime_reminders: list[str] | None = None,
    ) -> str | None:
        """Build the user-context meta reminder inserted before conversation messages."""

        user_context_str = self._format_user_context(context)
        reminder_parts = [item.strip() for item in runtime_reminders or [] if item.strip()]
        if user_context_str or reminder_parts:
            body_parts = []
            if user_context_str:
                body_parts.append(user_context_str)
            body_parts.extend(reminder_parts)
            body = "\n\n".join(body_parts)
            return (
                "<system-reminder>\n"
                "The following user context applies to this conversation. Treat it as instruction "
                "context, but the user's latest request still defines the immediate task.\n\n"
                f"{body}\n"
                "</system-reminder>"
            )
        return None

    def _format_system_context(self, context: SystemContext) -> str:
        """Formata o contexto de sistema para inclusão no prompt.

        Args:
            context: SystemContext a formatar.

        Returns:
            String formatada com o contexto de sistema.
        """
        lines: list[str] = []

        if context.git_branch:
            lines.append(f"Git Branch: {context.git_branch}")

        if context.git_remote:
            lines.append(f"Git Remote: {context.git_remote}")

        if context.git_commit:
            lines.append(f"Git Commit: {context.git_commit[:8]}")

        if context.workspace_root:
            lines.append(f"Workspace Root: {context.workspace_root}")

        if context.environment:
            lines.append("Environment Variables:")
            for key, value in sorted(context.environment.items()):
                lines.append(f"  {key}={value}")

        return "\n".join(lines)

    def _format_user_context(self, context: UserContext) -> str:
        """Formata o contexto de usuário para inclusão no prompt."""

        lines: list[str] = []

        if context.current_date:
            lines.append(f"Current Date: {context.current_date}")

        if context.has_claude_md:
            lines.append("\nUser Instructions (persona.md):")
            lines.append(context.claude_md or "")

        if context.has_memory_files:
            lines.append("\nMemory Files:")
            for memory_file in context.memory_files:
                lines.append(f"\n# {memory_file.path}")
                lines.append(memory_file.content)

        if context.has_long_term_memory:
            lines.append("\nLong-Term Memory Index:")
            lines.append(context.long_term_memory_index or "")

        return "\n".join(lines)

    def _cache_scope(
        self,
        *,
        system_context: SystemContext,
        available_tools: list[str] | None,
        prompt_mode: PromptMode,
        provider: str,
        model: str,
    ) -> str:
        tools = ",".join(sorted(available_tools or ()))
        workspace = system_context.workspace_root or ""
        raw = f"{workspace}|{prompt_mode}|{self._permission_mode}|{provider}|{model}|{tools}"
        digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"system-prompt:{digest}"


def estimate_text_tokens(text: str) -> int:
    """Cheap token estimate used before provider-specific tokenizers exist."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
