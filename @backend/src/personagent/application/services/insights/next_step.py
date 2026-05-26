"""Next-step suggestion service."""

from __future__ import annotations

import structlog

from personagent.domain.conversation.models import Conversation
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.domain.prompts.compact import NEXT_STEP_SUGGESTION_PROMPT

logger = structlog.get_logger(__name__)


class NextStepSuggestionService:
    """Generates short post-turn suggestions for the desktop composer."""

    def __init__(self, llm_backend: LLMBackendRepository | None = None) -> None:
        self._llm_backend = llm_backend

    async def suggest(
        self,
        conversation: Conversation,
        *,
        model: str,
        provider: str,
        finish_reason: str | None = None,
        suppressed: bool = False,
    ) -> str | None:
        if self._llm_backend is None or suppressed:
            return None
        if finish_reason in {"permission_required", "plan_approval_requested", "error"}:
            return None
        rendered = _render_recent(conversation)
        if not rendered.strip():
            return None
        try:
            result = await self._llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": NEXT_STEP_SUGGESTION_PROMPT},
                    {"role": "user", "content": rendered},
                ],
                temperature=0,
                max_tokens=64,
                stream=False,
                tools=None,
                tool_choice=None,
                model=model,
                provider=provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
        except Exception:
            logger.warning("next_step_suggestion_failed", exc_info=True)
            return None
        suggestion = " ".join(result.content.strip().strip('"').strip("'").split())
        if not suggestion:
            return None
        if len(suggestion.split()) > 12:
            suggestion = " ".join(suggestion.split()[:12])
        return suggestion


def _render_recent(conversation: Conversation) -> str:
    lines: list[str] = []
    for message in conversation.messages[-8:]:
        content = " ".join(message.content.split())
        if content:
            lines.append(f"{message.role.value}: {content[:1200]}")
    return "\n".join(lines)
