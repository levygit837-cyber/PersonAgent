"""Prompts domain models.

Este módulo define as entidades para montagem dinâmica de system prompts.
Seguindo os princípios da Arquitetura Clean, estas entidades não dependem
de infraestrutura (filesystem, banco, APIs externas).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

ComputeFn = Callable[[], str | None | Awaitable[str | None]]
PromptMode = Literal["auto", "writing", "exploring", "research"]
ConcretePromptMode = Literal["writing", "exploring", "research"]


@dataclass(frozen=True, slots=True)
class SystemPromptSection:
    """Seção do system prompt.

    Uma seção pode ser memoizada (cacheada por sessão) ou volátil
    (recomputada a cada turn). Seções voláteis quebram o cache de prompt
    quando o valor muda.
    """

    name: str
    compute: ComputeFn
    cache_break: bool = False  # True = recompute every turn (breaks cache)

    def __post_init__(self) -> None:
        """Valida a seção após criação."""
        if not self.name or not isinstance(self.name, str):
            raise ValueError("name must be a non-empty string")
        if not callable(self.compute):
            raise TypeError("compute must be a callable")


@dataclass(frozen=True, slots=True)
class PromptProfile:
    """Resolved prompt profile for a single turn.

    The profile is intentionally separate from the builder. A caller may obtain
    it from an LLM analysis, an explicit API override, or a safe fallback.
    """

    primary_mode: ConcretePromptMode = "exploring"
    secondary_modes: tuple[ConcretePromptMode, ...] = ()
    intent: str = ""
    surface_hints: tuple[str, ...] = ()
    confidence: float = 0.0
    source: str = "fallback"
    requested_mode: PromptMode = "auto"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def all_modes(self) -> tuple[ConcretePromptMode, ...]:
        """Return primary mode followed by unique secondary modes."""

        seen = {self.primary_mode}
        modes = [self.primary_mode]
        for mode in self.secondary_modes:
            if mode not in seen:
                seen.add(mode)
                modes.append(mode)
        return tuple(modes)


@dataclass(frozen=True, slots=True)
class PromptSurface:
    """Metadata describing a prompt surface available to the builder."""

    name: str
    category: str
    cacheable: bool = True
    dynamic: bool = False
    always_active: bool = False
    activated_by_hint: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("surface name must be non-empty")
        if not self.category:
            raise ValueError("surface category must be non-empty")


@dataclass(frozen=True, slots=True)
class SystemPromptParts:
    """Partas componentes do system prompt.

    Organiza as seções por responsabilidade para facilitar montagem
    dinâmica e cache inteligente.
    """

    base_sections: tuple[SystemPromptSection, ...] = ()
    tool_sections: tuple[SystemPromptSection, ...] = ()
    execution_sections: tuple[SystemPromptSection, ...] = ()
    agent_sections: tuple[SystemPromptSection, ...] = ()

    def all_sections(self) -> tuple[SystemPromptSection, ...]:
        """Retorna todas as seções em ordem."""
        return (
            self.base_sections + self.tool_sections + self.execution_sections + self.agent_sections
        )

    def with_base_section(self, section: SystemPromptSection) -> SystemPromptParts:
        """Retorna uma cópia com uma seção base adicional."""
        return type(self)(
            base_sections=self.base_sections + (section,),
            tool_sections=self.tool_sections,
            execution_sections=self.execution_sections,
            agent_sections=self.agent_sections,
        )

    def with_tool_section(self, section: SystemPromptSection) -> SystemPromptParts:
        """Retorna uma cópia com uma seção de ferramentas adicional."""
        return type(self)(
            base_sections=self.base_sections,
            tool_sections=self.tool_sections + (section,),
            execution_sections=self.execution_sections,
            agent_sections=self.agent_sections,
        )

    def with_execution_section(self, section: SystemPromptSection) -> SystemPromptParts:
        """Retorna uma cópia com uma seção de execução adicional."""
        return type(self)(
            base_sections=self.base_sections,
            tool_sections=self.tool_sections,
            execution_sections=self.execution_sections + (section,),
            agent_sections=self.agent_sections,
        )

    def with_agent_section(self, section: SystemPromptSection) -> SystemPromptParts:
        """Retorna uma cópia com uma seção de agente adicional."""
        return type(self)(
            base_sections=self.base_sections,
            tool_sections=self.tool_sections,
            execution_sections=self.execution_sections,
            agent_sections=self.agent_sections + (section,),
        )


@dataclass(frozen=True, slots=True)
class BuiltSystemPrompt:
    """System prompt completamente montado."""

    content: str
    user_context_message: str | None = None
    sections_used: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    build_duration_ms: int = 0
    estimated_tokens: int = 0

    @property
    def size_chars(self) -> int:
        """Retorna o tamanho do prompt em caracteres."""
        return len(self.content)

    def append_section(self, section: str) -> BuiltSystemPrompt:
        """Retorna uma cópia com uma seção adicional."""
        return type(self)(
            content=self.content + "\n\n" + section,
            user_context_message=self.user_context_message,
            sections_used=self.sections_used + (section,),
            metadata=self.metadata,
            build_duration_ms=self.build_duration_ms,
            estimated_tokens=self.estimated_tokens,
        )
