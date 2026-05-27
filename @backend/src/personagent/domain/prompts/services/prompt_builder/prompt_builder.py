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
    AgentStateProfile,
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
    response_style_runtime_reminder_section,
    todo_write_policy_section,
)
from personagent.domain.prompts.sections import (
    get_agent_sections,
    get_agent_state_sections,
    get_execution_sections,
    get_frontloaded_agent_sections,
    get_tool_sections,
)
from personagent.domain.prompts.sections.tool_prompts import get_rich_tool_prompt_sections
from personagent.domain.prompts.services.agent_state_resolver import (
    fallback_agent_state_profile,
)
from personagent.domain.prompts.skills import SkillDefinition
from personagent.domain.prompts.surfaces import PromptSurfaceRegistry
from personagent.domain.tools import ToolDefinition

from ._formatting import (
    build_user_context_message,
    format_system_context,
    format_user_context,
)
from ._sections import (
    build_command_sections,
    build_context_lifecycle_section,
    build_relevant_memories_section,
    build_session_memory_section,
    build_skill_sections,
)
from ._surfaces import get_surfaces_used
from ._tokens import estimate_text_tokens

__all__ = [
    "PromptBuilder",
    "build_user_context_message",
    "estimate_text_tokens",
    "format_system_context",
    "format_user_context",
]


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
        agent_state_profile: AgentStateProfile | None = None,
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
        state_profile = agent_state_profile or fallback_agent_state_profile(
            prompt_profile=profile,
            available_tools=sorted(all_tool_names),
            has_memory=bool(session_memory and session_memory.strip()) or bool(relevant_memories),
        )
        can_use_todos = "TodoWrite" in all_tool_names
        can_use_parallel_tools = (
            bool(supports_parallel_tool_calls)
            or len(all_tool_names) > 1
        )

        # Obtém seções base
        base_sections = get_default_prompt_sections()
        if self._enable_agent_sections:
            base_sections = self._with_frontloaded_agent_sections(base_sections)

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
            build_context_lifecycle_section(),
        )

        # Obtém seções do agente
        agent_sections = tuple(get_mode_prompt_section(mode) for mode in profile.all_modes)
        state_sections = get_agent_state_sections(state_profile.states)
        agent_sections += state_sections
        if self._enable_agent_sections:
            agent_sections += get_agent_sections()
        agent_sections += build_command_sections(command_inventory)
        agent_sections += build_skill_sections(skill_inventory)
        if session_memory and session_memory.strip():
            agent_sections += (build_session_memory_section(session_memory),)
        if relevant_memories:
            agent_sections += (build_relevant_memories_section(relevant_memories),)
        agent_sections += (response_style_runtime_reminder_section(),)

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
            agent_states=state_profile.states,
            provider=provider,
            model=model,
        )
        resolved_sections = await self._resolve_sections(parts, cache_scope)

        # Monta prompt completo
        content, dynamic_sections = self._assemble_system_prompt(
            resolved_sections,
            system_context,
        )
        user_context_message = build_user_context_message(user_context, runtime_reminders)
        resolved_section_names = tuple(section.name for section, _content in resolved_sections)
        surfaces_used = get_surfaces_used(
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
                "agent_states": list(state_profile.states),
                "agent_state_source": state_profile.source,
                "agent_state_reason": state_profile.reason,
                "agent_state_confidence": state_profile.confidence,
                "agent_state_profile": {
                    "states": list(state_profile.states),
                    "source": state_profile.source,
                    "reason": state_profile.reason,
                    "confidence": state_profile.confidence,
                    "raw": state_profile.raw,
                },
                "state_sections_used": [
                    section.name
                    for section, _content in resolved_sections
                    if section.name.startswith("state_")
                ],
                "has_persona_md": user_context.has_persona_md,
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

    def _with_frontloaded_agent_sections(
        self,
        base_sections: tuple[SystemPromptSection, ...],
    ) -> tuple[SystemPromptSection, ...]:
        """Insert stable persona sections immediately after response style."""

        frontloaded = get_frontloaded_agent_sections()
        if not frontloaded:
            return base_sections
        if not base_sections:
            return frontloaded
        return (base_sections[0], *frontloaded, *base_sections[1:])

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
        system_context_str = format_system_context(system_context)
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

    def _cache_scope(
        self,
        *,
        system_context: SystemContext,
        available_tools: list[str] | None,
        prompt_mode: PromptMode,
        agent_states: tuple[str, ...],
        provider: str,
        model: str,
    ) -> str:
        tools = ",".join(sorted(available_tools or ()))
        states = ",".join(agent_states)
        workspace = system_context.workspace_root or ""
        raw = (
            f"{workspace}|{prompt_mode}|{states}|"
            f"{self._permission_mode}|{provider}|{model}|{tools}"
        )
        digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"system-prompt:{digest}"
