"""Per-turn context-build resolution for ``ChatCompletionUseCase``.

Wraps the small ``_build_context_result`` helper that the streaming
turn loop and the synchronous ``preview_prompt`` entry point both call
at the top of a turn. The fallback path needs the operational-memory
workspace-root resolver, so the collaborator owns a reference to it.

Concurrency: stateless besides constructor refs. Safe to share across
requests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.build_context import BuildContextUseCase
from personagent.application.use_cases.chat.memory.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.conversation.models import Conversation

logger = structlog.get_logger(__name__)


class TurnContextResolver:
    """Resolve the :class:`ContextBuildResult` for a single chat turn.

    Tries the configured :class:`BuildContextUseCase` first. Any
    exception is logged at WARNING and treated as "no context" -- the
    fallback emits a minimal :class:`ContextBuildResult` sourced from
    the operational-memory workspace-root resolver so the rest of the
    turn pipeline always has a valid result to consume.
    """

    def __init__(
        self,
        *,
        build_context_use_case: BuildContextUseCase | None,
        operational_memory: OperationalMemoryCapture,
    ) -> None:
        self._build_context_use_case = build_context_use_case
        self._operational_memory = operational_memory

    async def build(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
    ) -> ContextBuildResult:
        """Return the per-turn :class:`ContextBuildResult`."""

        if self._build_context_use_case:
            try:
                return await self._build_context_use_case.execute(
                    conversation_id=str(conversation.id),
                    use_cache=True,
                )
            except Exception:
                logger.warning("context_build_failed", exc_info=True)

        workspace_root = self._operational_memory.resolve_workspace_root(request)
        return ContextBuildResult(
            system_context=SystemContext(
                workspace_root=str(workspace_root),
                cwd=str(workspace_root),
            ),
            user_context=UserContext(
                current_date=datetime.now(UTC).strftime("%Y-%m-%d")
            ),
            build_duration_ms=0,
            metadata={"source": "fallback"},
        )
