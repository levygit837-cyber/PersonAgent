"""Compatibility entrypoint for base system prompt sections."""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection
from personagent.domain.prompts.prompt import core_system_prompt_sections


def get_base_sections() -> tuple[SystemPromptSection, ...]:
    """Return the shared manual base sections used by the PromptBuilder."""

    return core_system_prompt_sections()
