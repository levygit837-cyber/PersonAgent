"""Post-turn bookkeeping extracted from ``chat_completion.py``.

After the assistant has finished producing a response (whether
streaming or not), the chat use case has to:

1. Run the optional :class:`NextStepSuggestionService` to attach a
   short "what to do next" suggestion to ``conversation.metadata``
   (suppressed when plan mode is active).
2. Run the optional :class:`SessionMemoryService` to refresh the
   per-conversation Markdown memory file; if it actually changed,
   stamp ``session_memory_updated_at`` on the conversation metadata.
3. Refresh the conversation title -- either via the optional
   :class:`SessionTitleService` (LLM-backed) or by falling back to the
   pure :meth:`Conversation.generate_title` helper when the
   conversation was freshly created on this turn.

Each step is independent and tolerates a missing collaborator (the
service can be ``None`` -- the step becomes a no-op). The trio is
extracted as :class:`AfterTurnCoordinator` so the chat use case is
left with a single ``self._after_turn.run(...)`` call.

Backward compatibility: the order of the steps, the conditions under
which each side effect fires, and the metadata keys written are
preserved verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.plan_mode import is_plan_mode_active
from personagent.application.services.next_step import NextStepSuggestionService
from personagent.application.services.session_memory import SessionMemoryService
from personagent.application.services.session_titles import SessionTitleService
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import (
    ConversationRepository,
)


class AfterTurnCoordinator:
    """Run post-turn bookkeeping in a single, ordered pass.

    The coordinator is stateless except for the four collaborators
    captured in :meth:`__init__`. Any of the service collaborators can
    be ``None`` -- the corresponding step then becomes a no-op so the
    chat use case does not need conditional logic around each one.
    """

    def __init__(
        self,
        *,
        conversation_repo: ConversationRepository,
        next_step_suggestion_service: NextStepSuggestionService | None,
        session_memory_service: SessionMemoryService | None,
        session_title_service: SessionTitleService | None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._next_step_suggestion_service = next_step_suggestion_service
        self._session_memory_service = session_memory_service
        self._session_title_service = session_title_service

    async def run_services(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
        *,
        finish_reason: str | None,
    ) -> str | None:
        """Run next-step suggestion + session memory, return suggestion text."""

        next_step: str | None = None
        if self._next_step_suggestion_service is not None:
            next_step = await self._next_step_suggestion_service.suggest(
                conversation,
                model=request.model,
                provider=request.provider,
                finish_reason=finish_reason,
                suppressed=is_plan_mode_active(conversation.metadata),
            )
            if next_step:
                conversation.metadata["next_step_suggestion"] = next_step

        if self._session_memory_service is not None:
            updated = await self._session_memory_service.update(
                conversation,
                model=request.model,
                provider=request.provider,
            )
            if updated:
                conversation.metadata["session_memory_updated_at"] = datetime.now(
                    UTC
                ).isoformat()

        return next_step

    async def refresh_session_title(
        self,
        conversation: Conversation,
        *,
        was_empty: bool,
    ) -> None:
        """Refresh the conversation title.

        When a :class:`SessionTitleService` is wired, defer entirely to
        it. Otherwise fall back to the deterministic
        :meth:`Conversation.generate_title` helper, but only when the
        conversation was freshly created on this turn -- i.e.
        ``was_empty`` is ``True``.
        """

        if self._session_title_service is not None:
            await self._session_title_service.refresh_title(
                self._conversation_repo,
                conversation,
            )
            return
        if was_empty:
            conversation.title = conversation.generate_title()
            await self._conversation_repo.update(conversation)


__all__ = ["AfterTurnCoordinator"]
