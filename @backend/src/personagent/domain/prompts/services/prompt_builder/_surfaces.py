"""Surface detection for the prompt builder."""

from __future__ import annotations


def get_surfaces_used(
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
            "response_style_contract",
            "response_style_runtime_reminder",
            "personality_and_collaboration",
            "acting_contract",
            "final_response_contract",
            "work_management",
            "evidence_and_tool_use",
            "safety_and_user_work",
            "provider_data_boundary",
        }
    ):
        add("system")
    for mode in ("writing", "exploring", "research"):
        if f"mode_{mode}" in sections:
            add(f"mode:{mode}")
    state_sections = sorted(
        name.removeprefix("state_")
        for name in sections
        if name.startswith("state_")
    )
    if state_sections:
        add("agent_state")
        for state in state_sections:
            add(f"state:{state}")
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
