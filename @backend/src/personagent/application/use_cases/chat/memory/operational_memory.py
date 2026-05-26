"""Operational memory capture extracted from ``chat_completion.py``.

The chat use case writes operational memory at four points in every
turn:

* ``capture_user_message`` -- right after the user message is appended.
* ``capture_assistant_message`` -- after a non-streaming completion.
* ``capture_assistant_text`` -- after every streaming pass that
  produced visible content (called from inside the streaming loop).
* ``capture_tool_result`` -- after each tool call resolves.

And once at the end of each turn it asks the memory job scheduler to
run an asynchronous extraction pass:

* ``trigger_memory_extraction`` -- enqueues a background job, debounced
  to at most one per 60 seconds per conversation.

All five methods used to live as private methods on
:class:`ChatCompletionUseCase`. Pulling them into
:class:`OperationalMemoryCapture` makes the use case smaller and gives
each call site a single, named collaborator with explicit dependencies
(memory service, job scheduler, tool runtime config) instead of poking
through ``self._operational_memory_service`` / ``self._memory_job_scheduler``
from the middle of the turn loop.

The class is a thin orchestrator -- the heavy lifting still lives in
:class:`~personagent.application.services.operational_memory.OperationalMemoryService`
and the memory job scheduler. This module owns three things:

* project-slug derivation (workspace path -> normalized slug);
* the workspace-root fallback chain (request -> tool runtime config ->
  ``Path.cwd()``);
* the 60-second debounce around memory extraction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from personagent.application.dto import ChatRequestDTO
from personagent.application.jobs.memory_job import JobType, MemoryJob
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.services import OperationalMemoryService
from personagent.application.services.operational_memory import (
    project_slug_from_workspace,
)
from personagent.application.tools import ToolRuntimeConfig
from personagent.domain.context.models import ContextBuildResult
from personagent.domain.conversation.models import Conversation
from personagent.domain.llm_backend.models import InferenceResult
from personagent.domain.tools import ToolCall, ToolResult, ToolUseContext

logger = structlog.get_logger(__name__)


# Debounce window for memory extraction. The chat use case calls
# ``trigger_memory_extraction`` at the end of every turn; we don't
# actually want a background pass per turn -- once per minute per
# conversation is plenty for the indexer to catch up.
_MEMORY_EXTRACTION_DEBOUNCE_SECONDS = 60.0


class OperationalMemoryCapture:
    """Operational-memory bookkeeping for a single chat completion turn.

    Stateless except for the three collaborators captured in
    :meth:`__init__`. Safe to share across requests (the methods accept
    everything they need by argument).

    When either ``memory_service`` or ``job_scheduler`` is ``None`` the
    corresponding methods become no-ops -- this mirrors the legacy
    behavior where the chat use case checked ``is None`` before each
    call.
    """

    def __init__(
        self,
        *,
        memory_service: OperationalMemoryService | None,
        job_scheduler: MemoryJobScheduler | None,
        tool_runtime_config: ToolRuntimeConfig | None,
    ) -> None:
        self._memory_service = memory_service
        self._job_scheduler = job_scheduler
        self._tool_runtime_config = tool_runtime_config

    # ---- Internals -------------------------------------------------------

    def _project_slug(self, workspace_root: str | None) -> str:
        """Normalize ``workspace_root`` into a project slug."""

        return str(project_slug_from_workspace(workspace_root))

    def resolve_workspace_root(self, request: ChatRequestDTO) -> Path:
        """Resolve the workspace root for ``request``.

        Precedence:
          1. ``request.tool_context["workspace_root"]`` if set.
          2. ``self._tool_runtime_config.workspace_root`` if a runtime
             config was provided.
          3. ``Path.cwd()`` as the final fallback.

        The use case still calls this same helper at a handful of
        non-memory sites (e.g. context fallback). Exposing it here
        keeps the resolution rule in exactly one place.
        """

        raw_context = request.tool_context or {}
        raw_workspace_root = raw_context.get("workspace_root")
        if raw_workspace_root:
            return Path(str(raw_workspace_root)).expanduser().resolve()
        if self._tool_runtime_config is not None:
            return Path(self._tool_runtime_config.workspace_root).resolve()
        return Path.cwd().resolve()

    # ---- Capture API -----------------------------------------------------

    async def capture_user_message(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
    ) -> None:
        if self._memory_service is None:
            return
        workspace_root = context_result.system_context.workspace_root
        await self._memory_service.capture_user_message(
            project_slug=self._project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            message=request.message,
            metadata={
                "provider": request.provider,
                "model": request.model,
                "prompt_mode": request.prompt_mode,
            },
        )

    async def capture_assistant_message(
        self,
        request: ChatRequestDTO,
        context_result: ContextBuildResult,
        conversation: Conversation,
        result: InferenceResult,
    ) -> None:
        """Convenience wrapper around :meth:`capture_assistant_text`.

        Used at the end of non-streaming completions where the full
        ``InferenceResult`` is available. The streaming path calls
        :meth:`capture_assistant_text` directly because it accumulates
        the content as it goes.
        """

        await self.capture_assistant_text(
            request,
            conversation,
            context_result,
            content=result.content,
            reasoning_content=result.reasoning_content,
            finish_reason=result.finish_reason,
            provider=str(result.metadata.get("provider") or request.provider),
            model=result.model or request.model,
        )

    async def capture_assistant_text(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        context_result: ContextBuildResult,
        *,
        content: str,
        reasoning_content: str | None,
        finish_reason: str | None,
        provider: str | None,
        model: str | None,
    ) -> None:
        """Capture an assistant text turn.

        Skipped silently when both ``content`` and ``reasoning_content``
        are empty -- there's nothing useful to index.
        """

        if self._memory_service is None:
            return
        if not content and not reasoning_content:
            return
        workspace_root = context_result.system_context.workspace_root
        await self._memory_service.capture_assistant_message(
            project_slug=self._project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            content=content,
            reasoning_content=reasoning_content,
            provider=provider or request.provider,
            model=model or request.model,
            finish_reason=finish_reason,
        )

    async def capture_tool_result(
        self,
        request: ChatRequestDTO | None,
        conversation: Conversation,
        call: ToolCall,
        result: ToolResult,
        tool_context: ToolUseContext,
    ) -> None:
        if self._memory_service is None:
            return
        workspace_root = str(tool_context.workspace_root)
        await self._memory_service.capture_tool_result(
            project_slug=self._project_slug(workspace_root),
            workspace_root=workspace_root,
            conversation_id=str(conversation.id),
            call=call,
            result=result,
            context=tool_context,
            task=request.message if request is not None else None,
        )

    # ---- Extraction job --------------------------------------------------

    async def trigger_memory_extraction(
        self,
        conversation: Conversation,
        request: ChatRequestDTO,
    ) -> None:
        """Dispatch a background memory extraction job.

        Debounced to at most one job per
        :data:`_MEMORY_EXTRACTION_DEBOUNCE_SECONDS` per conversation.
        The debounce timestamp is stored on
        ``conversation.metadata["_last_memory_extraction"]`` -- the
        same key the legacy in-class method used so existing
        conversations keep their debounce window across the migration.
        """

        if self._job_scheduler is None:
            return

        last_extract = conversation.metadata.get("_last_memory_extraction")
        if last_extract:
            try:
                last_dt = datetime.fromisoformat(str(last_extract))
                elapsed = (datetime.now(UTC) - last_dt).total_seconds()
                if elapsed < _MEMORY_EXTRACTION_DEBOUNCE_SECONDS:
                    return
            except (ValueError, TypeError):
                # Garbage in the metadata field is treated as "never
                # extracted" so a corrupted timestamp can't lock the
                # extractor out forever.
                pass

        workspace_root = self.resolve_workspace_root(request)
        project_slug = self._project_slug(str(workspace_root))

        job = MemoryJob(
            id=f"extract_{conversation.id}_{uuid.uuid4().hex}",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id=str(conversation.id),
            project_slug=project_slug,
            payload={
                "model": request.model,
                "provider": request.provider,
            },
        )
        try:
            await self._job_scheduler.submit_job(job)
            conversation.metadata["_last_memory_extraction"] = datetime.now(
                UTC
            ).isoformat()
            logger.info(
                "memory_extraction_triggered",
                conversation_id=str(conversation.id),
                project_slug=project_slug,
            )
        except Exception:
            logger.warning("memory_extraction_trigger_failed", exc_info=True)


__all__ = ["OperationalMemoryCapture"]
