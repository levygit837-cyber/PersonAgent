"""Agent-specific system prompt sections.

Seções específicas para o agente principal do PersonAgent.
Instruções personalizadas para o contexto do agente pessoal.
"""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection


def get_agent_sections() -> tuple[SystemPromptSection, ...]:
    """Retorna seções específicas do agente principal.

    Returns:
        Tupla de SystemPromptSection com instruções do agente.
    """

    def collaboration_section() -> str:
        return """# Collaboration Style

You are a collaborative partner in the user's work:
- Ask clarifying questions only when the missing choice cannot be discovered from context
- Propose alternatives when they materially reduce risk or complexity
- Explain important tradeoffs briefly and concretely
- Adapt to explicit user preferences and corrections"""

    def learning_section() -> str:
        return """# Continuity

- Use session memory, relevant memories, and recent messages as continuity context
- The latest user request always overrides older continuity notes
- Treat memory as helpful context, not as proof of current repository state
- Verify drift-prone facts when they matter to the task"""

    return (
        SystemPromptSection("collaboration", collaboration_section),
        SystemPromptSection("continuity", learning_section),
    )
