"""Tests for :class:`AssistantPassRunner`.

The pass runner streams one ``chat_completion_stream`` call and mutates
the per-turn :class:`AssistantStreamState`, then forwards a filtered
subset of chunks. These tests exercise:

* the backend kwargs are forwarded verbatim;
* per-chunk content / reasoning / image / tool-call accumulation;
* the finish_reason gating (internal-tool-stop swallowing and the
  ``has_pending_tool_calls`` forwarding contract);
* provider-passthrough metadata filtering (vertex_/kimi_/zenmux_/deepseek_);
* DeepSeek reasoning rewriting via :class:`StreamChunkNormalizer`;
* image storage delegation to :class:`MediaPolicyHandler`;
* duplicate tool-call-id deduplication via :class:`ToolResultHandler`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.lifecycle.assistant_pass import AssistantPassRunner
from personagent.application.use_cases.chat.messaging.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.messaging.state import AssistantStreamState
from personagent.application.use_cases.chat.streaming.normalization import (
    StreamChunkNormalizer,
)
from personagent.application.use_cases.chat.tooling.tool_results import ToolResultHandler
from personagent.domain.llm_backend.models import GeneratedImage, StreamChunk


async def _aiter(chunks: list[StreamChunk]) -> AsyncIterator[StreamChunk]:
    for chunk in chunks:
        yield chunk


def _backend(chunks: list[StreamChunk]) -> MagicMock:
    backend = MagicMock()
    backend.chat_completion_stream = MagicMock(return_value=_aiter(chunks))
    return backend


def _tool_results() -> ToolResultHandler:
    return ToolResultHandler(
        orchestrator_factory=lambda: MagicMock(),  # type: ignore[arg-type, return-value]
        operational_memory=MagicMock(),  # type: ignore[arg-type]
    )


def _runner(
    *,
    chunks: list[StreamChunk] | None = None,
    media_policy: MediaPolicyHandler | None = None,
    tool_results: ToolResultHandler | None = None,
) -> tuple[AssistantPassRunner, MagicMock]:
    backend = _backend(chunks or [])
    runner = AssistantPassRunner(
        llm_backend=backend,
        stream_chunk_normalizer=StreamChunkNormalizer(),
        media_policy=media_policy
        or MediaPolicyHandler(artifact_root=None, artifact_ttl_seconds=None),
        tool_results=tool_results or _tool_results(),
    )
    return runner, backend


async def _drain(runner: AssistantPassRunner, **kwargs: Any) -> list[StreamChunk]:
    return [chunk async for chunk in runner.run(**kwargs)]


def _request(**overrides: Any) -> ChatRequestDTO:
    defaults: dict[str, Any] = {
        "message": "hi",
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.5,
        "max_tokens": 128,
    }
    defaults.update(overrides)
    return ChatRequestDTO(**defaults)


def _run_kwargs(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "request": _request(),
        "conversation_id": "conv-1",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [],
        "seen_tool_call_ids": set(),
        "iteration": 0,
        "state": AssistantStreamState(),
    }
    defaults.update(overrides)
    return defaults


# -- backend wiring -------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_kwargs_are_forwarded_verbatim() -> None:
    runner, backend = _runner(chunks=[])

    await _drain(
        runner,
        **_run_kwargs(
            request=_request(
                temperature=0.9,
                max_tokens=42,
                reasoning_level="high",
                reasoning_budget_tokens=2048,
            ),
            tools=[{"name": "noop"}],
        ),
    )

    call_kwargs = backend.chat_completion_stream.call_args.kwargs
    assert call_kwargs["temperature"] == 0.9
    assert call_kwargs["max_tokens"] == 42
    assert call_kwargs["tools"] == [{"name": "noop"}]
    assert call_kwargs["tool_choice"] == "auto"
    assert call_kwargs["model"] == "gpt-4o"
    assert call_kwargs["provider"] == "openai"
    assert call_kwargs["reasoning_level"] == "high"
    assert call_kwargs["reasoning_budget_tokens"] == 2048


@pytest.mark.asyncio
async def test_tool_choice_is_none_when_tools_list_is_empty() -> None:
    runner, backend = _runner(chunks=[])

    await _drain(runner, **_run_kwargs(tools=[]))

    assert backend.chat_completion_stream.call_args.kwargs["tool_choice"] is None


# -- accumulation ---------------------------------------------------------


@pytest.mark.asyncio
async def test_content_chunks_accumulate_into_state() -> None:
    state = AssistantStreamState()
    chunks = [StreamChunk(content="hel"), StreamChunk(content="lo")]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.content == "hello"
    assert state.content_chunks == ["hel", "lo"]


@pytest.mark.asyncio
async def test_reasoning_chunks_accumulate_into_state() -> None:
    state = AssistantStreamState()
    chunks = [StreamChunk(reasoning_content="abc"), StreamChunk(reasoning_content="def")]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.reasoning_content == "abcdef"


@pytest.mark.asyncio
async def test_images_extend_state() -> None:
    state = AssistantStreamState()
    img1 = GeneratedImage(mime_type="image/png", url="https://x/1.png")
    img2 = GeneratedImage(mime_type="image/png", url="https://x/2.png")
    chunks = [StreamChunk(images=[img1]), StreamChunk(images=[img2])]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.images == [img1, img2]


@pytest.mark.asyncio
async def test_usage_is_kept_as_last_seen() -> None:
    state = AssistantStreamState()
    chunks = [
        StreamChunk(usage={"prompt_tokens": 10}),
        StreamChunk(usage={"prompt_tokens": 20, "completion_tokens": 5}),
    ]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.usage == {"prompt_tokens": 20, "completion_tokens": 5}


# -- tool calls -----------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_calls_set_tool_calls_finish_reason() -> None:
    state = AssistantStreamState()
    chunks = [
        StreamChunk(
            tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}]
        )
    ]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.tool_calls is not None
    assert state.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_duplicate_tool_call_ids_are_deduplicated_across_iterations() -> None:
    seen: set[str] = {"c1"}
    chunks = [
        StreamChunk(
            tool_calls=[
                {"id": "c1", "function": {"name": "x", "arguments": "{}"}},
                {"id": "c2", "function": {"name": "y", "arguments": "{}"}},
            ]
        )
    ]
    state = AssistantStreamState()
    runner, _ = _runner(chunks=chunks)

    await _drain(
        runner,
        **_run_kwargs(state=state, seen_tool_call_ids=seen, iteration=2),
    )

    assert state.tool_calls is not None
    ids = [call.get("id") for call in state.tool_calls]
    assert "c2" in ids
    assert "c1" not in ids


# -- finish reason gating -------------------------------------------------


@pytest.mark.asyncio
async def test_internal_tool_stop_does_not_overwrite_tool_calls_finish() -> None:
    """A finish_reason='stop' chunk with NO content/reasoning/images
    must not overwrite an already-set 'tool_calls' finish reason."""

    state = AssistantStreamState()
    chunks = [
        StreamChunk(
            tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}]
        ),
        StreamChunk(finish_reason="stop"),
    ]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_finish_reason_with_content_is_committed_to_state() -> None:
    state = AssistantStreamState()
    chunks = [StreamChunk(content="done", finish_reason="length")]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.finish_reason == "length"


# -- provider metadata ----------------------------------------------------


@pytest.mark.asyncio
async def test_provider_passthrough_metadata_is_collected_on_state() -> None:
    state = AssistantStreamState()
    chunks = [
        StreamChunk(
            content="hi",
            metadata={
                "vertex_safety": "low",
                "kimi_x": 1,
                "zenmux_y": 2,
                "deepseek_z": 3,
                "unrelated_key": "ignored",
            },
        )
    ]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.metadata == {
        "vertex_safety": "low",
        "kimi_x": 1,
        "zenmux_y": 2,
        "deepseek_z": 3,
    }


@pytest.mark.asyncio
async def test_state_model_and_provider_fall_back_to_request() -> None:
    state = AssistantStreamState()
    chunks = [StreamChunk(content="hi")]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.model == "gpt-4o"
    assert state.provider == "openai"


@pytest.mark.asyncio
async def test_state_model_is_overridden_by_chunk_metadata() -> None:
    state = AssistantStreamState()
    chunks = [StreamChunk(content="hi", metadata={"model": "actual-model"})]
    runner, _ = _runner(chunks=chunks)

    await _drain(runner, **_run_kwargs(state=state))

    assert state.model == "actual-model"


# -- forwarding -----------------------------------------------------------


@pytest.mark.asyncio
async def test_forwarded_chunks_carry_provider_and_model_metadata() -> None:
    chunks = [StreamChunk(content="hi")]
    runner, _ = _runner(chunks=chunks)

    out = await _drain(runner, **_run_kwargs())

    assert len(out) == 1
    assert out[0].content == "hi"
    assert out[0].metadata["provider"] == "openai"
    assert out[0].metadata["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_empty_chunks_with_no_finish_reason_are_dropped() -> None:
    chunks = [
        StreamChunk(),  # empty
        StreamChunk(content="hi"),
    ]
    runner, _ = _runner(chunks=chunks)

    out = await _drain(runner, **_run_kwargs())

    assert len(out) == 1
    assert out[0].content == "hi"


@pytest.mark.asyncio
async def test_tool_call_only_chunk_is_not_forwarded() -> None:
    chunks = [
        StreamChunk(
            tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}],
        )
    ]
    runner, _ = _runner(chunks=chunks)

    out = await _drain(runner, **_run_kwargs())

    assert out == []


# -- image storage delegation --------------------------------------------


@pytest.mark.asyncio
async def test_image_chunks_are_routed_through_media_policy() -> None:
    img = GeneratedImage(mime_type="image/png", url="https://x/y.png")
    media_policy = MagicMock(spec=MediaPolicyHandler)
    media_policy.store_generated_images.return_value = [img]
    chunks = [StreamChunk(images=[img])]
    runner, _ = _runner(chunks=chunks, media_policy=media_policy)

    out = await _drain(runner, **_run_kwargs(conversation_id="conv-xyz"))

    media_policy.store_generated_images.assert_called_once_with("conv-xyz", [img])
    assert out[0].images == [img]


# -- deepseek reroute -----------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_tail_reasoning_is_rerouted_into_content() -> None:
    state = AssistantStreamState()
    state.content_chunks.append("partial")
    chunks = [StreamChunk(reasoning_content="late reasoning")]
    runner, _ = _runner(chunks=chunks)

    out = await _drain(
        runner,
        **_run_kwargs(
            state=state,
            request=_request(provider="deepseek", model="r1"),
        ),
    )

    assert state.content_chunks[-1] == "late reasoning"
    assert any(c.content == "late reasoning" for c in out)


# -- error propagation ----------------------------------------------------


@pytest.mark.asyncio
async def test_backend_exception_propagates() -> None:
    backend = MagicMock()
    backend.chat_completion_stream = MagicMock(
        side_effect=RuntimeError("boom"),
    )
    runner = AssistantPassRunner(
        llm_backend=backend,
        stream_chunk_normalizer=StreamChunkNormalizer(),
        media_policy=MediaPolicyHandler(artifact_root=None, artifact_ttl_seconds=None),
        tool_results=_tool_results(),
    )

    with pytest.raises(RuntimeError, match="boom"):
        await _drain(runner, **_run_kwargs())


@pytest.mark.asyncio
async def test_backend_called_once_per_pass() -> None:
    runner, backend = _runner(chunks=[StreamChunk(content="x")])

    await _drain(runner, **_run_kwargs())

    assert backend.chat_completion_stream.call_count == 1


# -- runner instance reuse -----------------------------------------------


@pytest.mark.asyncio
async def test_runner_can_be_used_for_multiple_passes() -> None:
    """The runner has no own state; two passes share nothing."""

    backend = MagicMock()
    backend.chat_completion_stream = MagicMock(
        side_effect=[_aiter([StreamChunk(content="a")]), _aiter([StreamChunk(content="b")])],
    )
    runner = AssistantPassRunner(
        llm_backend=backend,
        stream_chunk_normalizer=StreamChunkNormalizer(),
        media_policy=MediaPolicyHandler(artifact_root=None, artifact_ttl_seconds=None),
        tool_results=_tool_results(),
    )

    state1 = AssistantStreamState()
    state2 = AssistantStreamState()

    out1 = await _drain(runner, **_run_kwargs(state=state1))
    out2 = await _drain(runner, **_run_kwargs(state=state2))

    assert state1.content == "a"
    assert state2.content == "b"
    assert [c.content for c in out1] == ["a"]
    assert [c.content for c in out2] == ["b"]


# -- ToolResultHandler.forwarded_finish_reason --------------------------


@pytest.mark.asyncio
async def test_pending_tool_call_finish_reason_is_suppressed_in_forwarded_chunk() -> None:
    """When state has pending tool calls the forwarded chunk should
    carry finish_reason=None even if the upstream chunk had one."""

    state = AssistantStreamState()
    tool_results = _tool_results()
    tool_results.forwarded_finish_reason = MagicMock(return_value=None)  # type: ignore[method-assign]
    chunks = [
        StreamChunk(
            content="x",
            tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}],
            finish_reason="tool_calls",
        )
    ]
    runner, _ = _runner(chunks=chunks, tool_results=tool_results)

    out = await _drain(runner, **_run_kwargs(state=state))

    assert out[0].finish_reason is None
    tool_results.forwarded_finish_reason.assert_called_once()


# -- empty stream --------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_stream_leaves_state_in_default() -> None:
    state = AssistantStreamState()
    runner, _ = _runner(chunks=[])

    out = await _drain(runner, **_run_kwargs(state=state))

    assert out == []
    assert state.content == ""
    assert state.tool_calls is None
    assert state.finish_reason is None
    # Empty stream means no per-chunk write; state model/provider stay
    # at the AssistantStreamState default ("").
    assert state.model == ""
    assert state.provider == ""


# -- AsyncMock-based collaborator ----------------------------------------


@pytest.mark.asyncio
async def test_tool_results_unique_call_ids_is_called_with_iteration() -> None:
    seen: set[str] = set()
    chunks = [
        StreamChunk(
            tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}],
        )
    ]
    tool_results = _tool_results()
    tool_results.unique_call_ids = MagicMock(  # type: ignore[method-assign]
        return_value=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}],
    )
    runner, _ = _runner(chunks=chunks, tool_results=tool_results)

    await _drain(
        runner,
        **_run_kwargs(seen_tool_call_ids=seen, iteration=7),
    )

    tool_results.unique_call_ids.assert_called_once()
    call_args = tool_results.unique_call_ids.call_args.args
    assert call_args[1] is seen
    assert call_args[2] == 7


def _ensure_async_mock_typed() -> None:
    """No-op sanity check for the helper import shape."""

    assert AsyncMock is not None
