"""Tests for the operational memory capture surface.

Until #N this surface lived as five private methods on
:class:`ChatCompletionUseCase`. Pulling it into
:class:`OperationalMemoryCapture` made each integration point testable
on its own. These tests pin the externally observable behavior we
relied on:

* the four capture methods short-circuit when the service is absent;
* ``capture_assistant_text`` also short-circuits when there's no
  visible content;
* project slug derivation and workspace root resolution mirror the
  legacy fallback chain (request -> tool runtime config -> cwd);
* memory extraction is debounced via a 60-second window stamped on
  the conversation, and a malformed timestamp doesn't lock the
  extractor out forever.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.jobs.memory_job import JobType, MemoryJob
from personagent.application.tools.runtime_config import ToolRuntimeConfig
from personagent.application.use_cases.chat.memory.operational_memory import (
    OperationalMemoryCapture,
)
from personagent.domain.context.models import (
    ContextBuildResult,
    SystemContext,
    UserContext,
)
from personagent.domain.conversation.models import Conversation
from personagent.domain.llm_backend.models import InferenceResult
from personagent.domain.tools import ToolCall, ToolResult, ToolUseContext

# ---------------------------------------------------------------------------
# Recorder collaborators (the real services do disk I/O / embeddings).
# ---------------------------------------------------------------------------


class _MemoryServiceRecorder:
    """Implements the subset of :class:`OperationalMemoryService` we call."""

    def __init__(self) -> None:
        self.user_messages: list[dict[str, Any]] = []
        self.assistant_messages: list[dict[str, Any]] = []
        self.tool_results: list[dict[str, Any]] = []

    async def capture_user_message(self, **kwargs: Any) -> None:
        self.user_messages.append(kwargs)

    async def capture_assistant_message(self, **kwargs: Any) -> None:
        self.assistant_messages.append(kwargs)

    async def capture_tool_result(self, **kwargs: Any) -> None:
        self.tool_results.append(kwargs)


class _JobSchedulerRecorder:
    """Records jobs without touching APScheduler."""

    def __init__(self, *, raise_on_submit: bool = False) -> None:
        self.jobs: list[MemoryJob] = []
        self.raise_on_submit = raise_on_submit

    async def submit_job(self, job: MemoryJob) -> str:
        if self.raise_on_submit:
            raise RuntimeError("scheduler down")
        self.jobs.append(job)
        return job.id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _request(**overrides: Any) -> ChatRequestDTO:
    base: dict[str, Any] = {
        "message": "build me a function",
        "provider": "nvidia",
        "model": "test-model",
        "prompt_mode": "code",
    }
    base.update(overrides)
    return ChatRequestDTO(**base)


def _context_result(workspace_root: str = "/home/user/MyProject") -> ContextBuildResult:
    return ContextBuildResult(
        system_context=SystemContext(
            workspace_root=workspace_root,
            cwd=workspace_root,
        ),
        user_context=UserContext(),
        build_duration_ms=0,
    )


def _tool_context(workspace_root: str = "/home/user/MyProject") -> ToolUseContext:
    root = Path(workspace_root)
    return ToolUseContext(
        conversation_id="conv-1",
        workspace_root=root,
        cwd=root,
        allowed_roots=(root,),
    )


# ---------------------------------------------------------------------------
# Workspace root resolution
# ---------------------------------------------------------------------------


def test_resolve_workspace_root_prefers_request_tool_context(tmp_path: Path) -> None:
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=None, tool_runtime_config=None
    )
    request = _request(tool_context={"workspace_root": str(tmp_path)})

    assert capture.resolve_workspace_root(request) == tmp_path.resolve()


def test_resolve_workspace_root_falls_back_to_runtime_config(tmp_path: Path) -> None:
    capture = OperationalMemoryCapture(
        memory_service=None,
        job_scheduler=None,
        tool_runtime_config=ToolRuntimeConfig(
            workspace_root=tmp_path, allowed_roots=(tmp_path,)
        ),
    )

    assert capture.resolve_workspace_root(_request()) == tmp_path.resolve()


def test_resolve_workspace_root_falls_back_to_cwd() -> None:
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=None, tool_runtime_config=None
    )

    assert capture.resolve_workspace_root(_request()) == Path.cwd().resolve()


# ---------------------------------------------------------------------------
# Capture short-circuits without service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_user_message_noop_without_service() -> None:
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation()

    # Must not raise. There's nothing to assert -- we just need to
    # confirm the no-op path doesn't blow up.
    await capture.capture_user_message(_request(), _context_result(), conversation)


@pytest.mark.asyncio
async def test_capture_tool_result_noop_without_service() -> None:
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation()

    await capture.capture_tool_result(
        _request(),
        conversation,
        ToolCall(id="call-1", name="read_file"),
        ToolResult(tool_call_id="call-1", tool_name="read_file", content="ok"),
        _tool_context(),
    )


# ---------------------------------------------------------------------------
# Capture forwards correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_user_message_forwards_project_slug_and_metadata() -> None:
    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation(id=uuid4(), title="t")
    request = _request(message="hi there", provider="zenmux", model="m", prompt_mode="plan")

    await capture.capture_user_message(
        request, _context_result("/home/user/MyProject"), conversation
    )

    assert len(recorder.user_messages) == 1
    call = recorder.user_messages[0]
    assert call["project_slug"] == "myproject"
    assert call["workspace_root"] == "/home/user/MyProject"
    assert call["conversation_id"] == str(conversation.id)
    assert call["message"] == "hi there"
    assert call["metadata"] == {
        "provider": "zenmux",
        "model": "m",
        "prompt_mode": "plan",
    }


@pytest.mark.asyncio
async def test_capture_assistant_message_uses_inference_result_metadata() -> None:
    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation()
    result = InferenceResult(
        content="Sure, here's the patch.",
        reasoning_content="thought a bit",
        finish_reason="stop",
        model="actual-model",
        metadata={"provider": "actual-provider"},
    )

    await capture.capture_assistant_message(
        _request(), _context_result(), conversation, result
    )

    assert len(recorder.assistant_messages) == 1
    call = recorder.assistant_messages[0]
    assert call["content"] == "Sure, here's the patch."
    assert call["reasoning_content"] == "thought a bit"
    assert call["finish_reason"] == "stop"
    # Provider / model from the inference result override the request.
    assert call["provider"] == "actual-provider"
    assert call["model"] == "actual-model"


@pytest.mark.asyncio
async def test_capture_assistant_text_skips_empty_content() -> None:
    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )

    await capture.capture_assistant_text(
        _request(),
        Conversation(),
        _context_result(),
        content="",
        reasoning_content=None,
        finish_reason="stop",
        provider="x",
        model="y",
    )

    assert recorder.assistant_messages == []


@pytest.mark.asyncio
async def test_capture_assistant_text_keeps_reasoning_only_turns() -> None:
    """Reasoning-only turns still go into operational memory."""

    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )

    await capture.capture_assistant_text(
        _request(),
        Conversation(),
        _context_result(),
        content="",
        reasoning_content="hmm",
        finish_reason="stop",
        provider="x",
        model="y",
    )

    assert len(recorder.assistant_messages) == 1


@pytest.mark.asyncio
async def test_capture_tool_result_uses_tool_context_workspace_root() -> None:
    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation()

    await capture.capture_tool_result(
        _request(message="fix it"),
        conversation,
        ToolCall(id="call-1", name="read_file"),
        ToolResult(tool_call_id="call-1", tool_name="read_file", content="ok"),
        _tool_context("/tmp/OtherProject"),
    )

    assert len(recorder.tool_results) == 1
    call = recorder.tool_results[0]
    assert call["workspace_root"] == "/tmp/OtherProject"
    assert call["project_slug"] == "otherproject"
    assert call["task"] == "fix it"


@pytest.mark.asyncio
async def test_capture_tool_result_passes_none_task_when_request_missing() -> None:
    recorder = _MemoryServiceRecorder()
    capture = OperationalMemoryCapture(
        memory_service=recorder, job_scheduler=None, tool_runtime_config=None
    )

    await capture.capture_tool_result(
        None,
        Conversation(),
        ToolCall(id="c", name="bash"),
        ToolResult(tool_call_id="c", tool_name="bash", content="done"),
        _tool_context(),
    )

    assert recorder.tool_results[0]["task"] is None


# ---------------------------------------------------------------------------
# Memory extraction trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_memory_extraction_noop_without_scheduler() -> None:
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=None, tool_runtime_config=None
    )
    conversation = Conversation()

    await capture.trigger_memory_extraction(conversation, _request())

    assert "_last_memory_extraction" not in conversation.metadata


@pytest.mark.asyncio
async def test_trigger_memory_extraction_submits_job_and_stamps_metadata(
    tmp_path: Path,
) -> None:
    scheduler = _JobSchedulerRecorder()
    capture = OperationalMemoryCapture(
        memory_service=None,
        job_scheduler=scheduler,
        tool_runtime_config=ToolRuntimeConfig(
            workspace_root=tmp_path, allowed_roots=(tmp_path,)
        ),
    )
    conversation = Conversation()

    await capture.trigger_memory_extraction(conversation, _request())

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job.type == JobType.EXTRACT_MEMORIES
    assert job.conversation_id == str(conversation.id)
    assert job.payload == {"model": "test-model", "provider": "nvidia"}
    assert "_last_memory_extraction" in conversation.metadata


@pytest.mark.asyncio
async def test_trigger_memory_extraction_debounces_recent_runs() -> None:
    scheduler = _JobSchedulerRecorder()
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=scheduler, tool_runtime_config=None
    )
    conversation = Conversation()
    # Stamp the last extraction 10 seconds ago -> within the 60s window.
    conversation.metadata["_last_memory_extraction"] = (
        datetime.now(UTC) - timedelta(seconds=10)
    ).isoformat()

    await capture.trigger_memory_extraction(conversation, _request())

    assert scheduler.jobs == []


@pytest.mark.asyncio
async def test_trigger_memory_extraction_runs_after_debounce_expires() -> None:
    scheduler = _JobSchedulerRecorder()
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=scheduler, tool_runtime_config=None
    )
    conversation = Conversation()
    # 90 seconds ago -> outside the 60s window.
    conversation.metadata["_last_memory_extraction"] = (
        datetime.now(UTC) - timedelta(seconds=90)
    ).isoformat()

    await capture.trigger_memory_extraction(conversation, _request())

    assert len(scheduler.jobs) == 1


@pytest.mark.asyncio
async def test_trigger_memory_extraction_recovers_from_garbage_timestamp() -> None:
    """A malformed debounce stamp must not lock the extractor out forever."""

    scheduler = _JobSchedulerRecorder()
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=scheduler, tool_runtime_config=None
    )
    conversation = Conversation()
    conversation.metadata["_last_memory_extraction"] = "not-a-timestamp"

    await capture.trigger_memory_extraction(conversation, _request())

    assert len(scheduler.jobs) == 1


@pytest.mark.asyncio
async def test_trigger_memory_extraction_swallows_scheduler_errors() -> None:
    """Scheduler failure -> warning logged, no exception bubbles."""

    scheduler = _JobSchedulerRecorder(raise_on_submit=True)
    capture = OperationalMemoryCapture(
        memory_service=None, job_scheduler=scheduler, tool_runtime_config=None
    )
    conversation = Conversation()

    # Must not raise.
    await capture.trigger_memory_extraction(conversation, _request())

    # The debounce stamp is also NOT set, so the next turn can retry.
    assert "_last_memory_extraction" not in conversation.metadata
