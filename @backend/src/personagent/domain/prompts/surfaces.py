"""Prompt surface registry.

Claude Code-like prompt construction is easier to reason about when every
prompt contributor is named as a surface. The registry here is intentionally
small: it records what can participate in the prompt and lets the builder emit
metadata for observability and tests.
"""

from __future__ import annotations

from personagent.domain.prompts.models import PromptProfile, PromptSurface


class PromptSurfaceRegistry:
    """Registry of prompt surfaces used by the main chat prompt builder."""

    def __init__(self, surfaces: list[PromptSurface] | None = None) -> None:
        self._surfaces: dict[str, PromptSurface] = {}
        for surface in surfaces or default_prompt_surfaces():
            self.register(surface)

    def register(self, surface: PromptSurface) -> None:
        self._surfaces[surface.name] = surface

    def list_all(self) -> tuple[PromptSurface, ...]:
        return tuple(self._surfaces.values())

    def resolve_active(self, profile: PromptProfile) -> tuple[PromptSurface, ...]:
        hints = {hint.strip().lower() for hint in profile.surface_hints}
        active: list[PromptSurface] = []
        for surface in self._surfaces.values():
            if surface.always_active or surface.name in hints or surface.category in hints:
                active.append(surface)
        for mode in profile.all_modes:
            surface = self._surfaces.get(f"mode:{mode}")
            if surface and surface not in active:
                active.append(surface)
        return tuple(active)


def default_prompt_surfaces() -> list[PromptSurface]:
    return [
        PromptSurface("system", "system", cacheable=True, always_active=True),
        PromptSurface("mode:writing", "mode", cacheable=True),
        PromptSurface("mode:exploring", "mode", cacheable=True),
        PromptSurface("mode:research", "mode", cacheable=True),
        PromptSurface("tool", "tool", cacheable=True, always_active=True),
        PromptSurface("command", "command", cacheable=True),
        PromptSurface("skill", "skill", cacheable=True),
        PromptSurface("slash", "slash", cacheable=False, dynamic=True),
        PromptSurface("memory", "memory", cacheable=False, dynamic=True),
        PromptSurface("compact", "compact", cacheable=True, always_active=True),
        PromptSurface("next_step", "next_step", cacheable=True),
        PromptSurface("reminder", "reminder", cacheable=False, dynamic=True, always_active=True),
    ]
