"""Memory-recall coordination extracted from ``chat_completion.py``.

The chat use case asked two different memory subsystems for relevant
context on every turn:

* **Classic recall** -- the long-term, file-backed memory pipeline
  (:class:`~personagent.application.use_cases.memory.recall_memory.RecallMemoryUseCase`
  + :class:`~personagent.domain.memory.repositories.memory_repository.MemoryRepository`).
  It returns curated ``RelevantMemory`` objects formatted by
  :class:`~personagent.domain.memory.services.memory_formatter.MemoryFormatter`
  and tracks ``_surfaced_memory_paths`` on the conversation so the
  same memories aren't redrawn on consecutive turns.

* **Operational recall** -- the short-term, execution-history pipeline
  (:class:`~personagent.application.services.operational_memory.OperationalMemoryService`).
  It returns a single formatted block and stamps
  ``_operational_memory_prompt`` on the conversation so the UI can
  show what was used. When the primary recall returns nothing the
  coordinator falls back to a ``latest_only=True`` query so the agent
  always sees *something* from recent execution context.

Both subsystems are optional and are wired together here into a single
:class:`MemoryRecallCoordinator` that returns a
:class:`~personagent.application.use_cases.chat.state.MemoryRecallResult`
ready to slot into the prompt package. Pulling this out of the chat
use case keeps it small and gives memory recall a single testable
collaborator instead of a 100-line method buried inside an orchestrator.

The coordinator never raises -- subsystem failures are logged and
recall degrades to "no memories available", which mirrors the legacy
behavior.
"""

from __future__ import annotations

import structlog

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.services import OperationalMemoryService
from personagent.application.services.operational_memory import (
    project_slug_from_workspace,
)
from personagent.application.use_cases.chat.helpers import (
    detect_memory_file_paths,
    detect_memory_source_types,
)
from personagent.application.use_cases.chat.state import MemoryRecallResult
from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.memory.models.operational import StructuredMemoryPackage
from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.repositories.memory_repository import MemoryRepository
from personagent.domain.memory.services.memory_formatter import MemoryFormatter
from personagent.domain.memory.services.memory_trace import MemoryTraceBuilder
from personagent.domain.models.conversation import Conversation

logger = structlog.get_logger(__name__)


# Keys we stamp on ``conversation.metadata`` so the UI / next turn can
# read recall state. Stable across refactors -- existing conversations
# continue to dedupe and surface the same memories after the migration.
_SURFACED_MEMORY_PATHS_KEY = "_surfaced_memory_paths"
_OPERATIONAL_MEMORY_PROMPT_KEY = "_operational_memory_prompt"


class MemoryRecallCoordinator:
    """Coordinate classic and operational memory recall for one turn.

    Stateless; every collaborator is captured at construction. Each
    of ``recall_memory_use_case``, ``memory_repository``, and
    ``operational_memory_service`` is optional -- when missing, the
    corresponding sub-pipeline is skipped silently. The empty result
    (no prompt memories, no trace) is itself a valid recall outcome.

    ``context_window_tokens`` is forwarded to the operational recall
    so it can budget its own prompt block.
    """

    def __init__(
        self,
        *,
        recall_memory_use_case: RecallMemoryUseCase | None,
        memory_repository: MemoryRepository | None,
        operational_memory_service: OperationalMemoryService | None,
        context_window_tokens: int,
    ) -> None:
        self._recall_memory_use_case = recall_memory_use_case
        self._memory_repository = memory_repository
        self._operational_memory_service = operational_memory_service
        # Forwarded to the operational recall so it can size its own
        # prompt block against the same budget the use case uses.
        self._context_window_tokens = max(1, int(context_window_tokens))

    async def recall(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
    ) -> MemoryRecallResult:
        """Run both recall subsystems and return their combined output.

        Side effects (intentional, mirror the legacy method):

        * Clears any previous ``_operational_memory_prompt`` stamp on
          the conversation before running operational recall.
        * Stamps the new ``_operational_memory_prompt`` metadata when
          operational recall produces a package.
        * Updates ``_surfaced_memory_paths`` with the file paths of
          newly surfaced classic memories so future turns don't
          re-surface the same items.

        Failures in either subsystem are logged at WARNING and treated
        as "nothing to recall" -- recall must never crash the turn.
        """

        workspace_root = context_result.system_context.workspace_root
        project_slug = project_slug_from_workspace(workspace_root)
        formatted_memories: list[str] = []
        classic_memories: list[RelevantMemory] = []
        operational_package: StructuredMemoryPackage | None = None

        # Always clear the previous operational stamp before recall so
        # a failed run doesn't leave a stale prompt metadata block
        # behind on the conversation.
        conversation.metadata.pop(_OPERATIONAL_MEMORY_PROMPT_KEY, None)

        await self._run_classic_recall(
            request=request,
            project_slug=project_slug,
            conversation=conversation,
            classic_memories=classic_memories,
            formatted_memories=formatted_memories,
        )

        operational_package = await self._run_operational_recall(
            request=request,
            project_slug=project_slug,
            workspace_root=workspace_root,
            conversation=conversation,
            formatted_memories=formatted_memories,
        )

        return MemoryRecallResult(
            prompt_memories=formatted_memories,
            trace=MemoryTraceBuilder.build(
                classic_memories=classic_memories,
                operational_package=operational_package,
                prompt_blocks=formatted_memories,
            ),
        )

    # ---- Classic recall --------------------------------------------------

    async def _run_classic_recall(
        self,
        *,
        request: ChatRequestDTO,
        project_slug: str,
        conversation: Conversation,
        classic_memories: list[RelevantMemory],
        formatted_memories: list[str],
    ) -> None:
        """Recall + dedupe classic file-backed memories.

        Skipped silently when either ``recall_memory_use_case`` or
        ``memory_repository`` is missing -- they're paired in practice
        (the use case needs the repository to resolve memory dirs).
        """

        if (
            self._recall_memory_use_case is None
            or self._memory_repository is None
        ):
            return

        try:
            memory_dir = await self._memory_repository.get_memory_dir(project_slug)

            already_surfaced = set(
                conversation.metadata.get(_SURFACED_MEMORY_PATHS_KEY, [])
            )

            # The chat use case used to feed in recent tool names here;
            # the inlined implementation was a TODO stub that always
            # returned []. Preserve that behavior verbatim until the
            # real recent-tool tracking lands -- changing recall input
            # belongs in its own PR.
            recent_tools: list[str] = []

            memories = await self._recall_memory_use_case.execute(
                query=request.message,
                memory_dir=memory_dir,
                recent_tools=recent_tools,
                already_surfaced=already_surfaced,
            )

            if memories:
                new_paths = [m.path for m in memories]
                existing = set(
                    conversation.metadata.get(_SURFACED_MEMORY_PATHS_KEY, [])
                )
                existing.update(new_paths)
                conversation.metadata[_SURFACED_MEMORY_PATHS_KEY] = list(existing)

            classic_memories.extend(memories)
            formatted_memories.extend(
                MemoryFormatter.format_relevant_memories(memories)
            )
        except Exception:
            logger.warning("memory_recall_failed", exc_info=True)

    # ---- Operational recall ---------------------------------------------

    async def _run_operational_recall(
        self,
        *,
        request: ChatRequestDTO,
        project_slug: str,
        workspace_root: str,
        conversation: Conversation,
        formatted_memories: list[str],
    ) -> StructuredMemoryPackage | None:
        """Recall operational execution history, with a latest-only fallback.

        Returns the resulting :class:`StructuredMemoryPackage` (or
        ``None`` when the subsystem isn't wired) so the caller can
        hand it to :class:`MemoryTraceBuilder`.
        """

        if self._operational_memory_service is None:
            return None

        try:
            detected_file_paths = detect_memory_file_paths(request.message)
            detected_source_types = detect_memory_source_types(request.message)

            package = await self._operational_memory_service.recall_package_for_prompt(
                project_slug=project_slug,
                query=request.message,
                provider=request.provider,
                model=request.model,
                conversation_id=None,
                current_conversation_id=str(conversation.id),
                workspace_root=workspace_root,
                source_types=detected_source_types,
                file_paths=detected_file_paths,
                context_window_tokens=self._context_window_tokens,
            )
            conversation.metadata[_OPERATIONAL_MEMORY_PROMPT_KEY] = package.metadata()
            operational_memory = package.formatted

            if not operational_memory:
                # Primary recall returned nothing -- fall back to the
                # newest events so the agent always has *some*
                # execution context to work from.
                package = await self._operational_memory_service.recall_package_for_prompt(
                    project_slug=project_slug,
                    query=request.message,
                    provider=request.provider,
                    model=request.model,
                    conversation_id=None,
                    current_conversation_id=str(conversation.id),
                    workspace_root=workspace_root,
                    source_types=detected_source_types,
                    file_paths=detected_file_paths,
                    latest_only=True,
                    context_window_tokens=self._context_window_tokens,
                )
                conversation.metadata[_OPERATIONAL_MEMORY_PROMPT_KEY] = (
                    package.metadata()
                )
                operational_memory = package.formatted

            if operational_memory:
                formatted_memories.append(operational_memory)
            return package
        except Exception:
            logger.warning("operational_memory_recall_failed", exc_info=True)
            return None


__all__ = ["MemoryRecallCoordinator"]
