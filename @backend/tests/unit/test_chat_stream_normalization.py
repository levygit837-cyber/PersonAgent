"""Tests for :class:`StreamChunkNormalizer`.

Two purely-functional transforms covered branch-by-branch:

* ``normalize_provider_stream_chunk`` -- DeepSeek tail-end reasoning
  reroute. Every guard condition must short-circuit and return the
  chunk unchanged; only the exact "DeepSeek + already-streamed
  content + reasoning-only chunk" combination triggers the rewrite.
* ``empty_model_response_notice`` -- canonical user-facing string
  format pinned via a substring contract.
"""
from __future__ import annotations

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.state import AssistantStreamState
from personagent.application.use_cases.chat.stream_normalization import (
    StreamChunkNormalizer,
)
from personagent.domain.models.inference_result import GeneratedImage, StreamChunk


def _state(*, content: str = "") -> AssistantStreamState:
    state = AssistantStreamState()
    if content:
        state.content_chunks.append(content)
    return state


def _request(provider: str = "deepseek") -> ChatRequestDTO:
    return ChatRequestDTO(message="hi", provider=provider)


# -- normalize_provider_stream_chunk: positive path ------------------------


def test_normalize_reroutes_deepseek_reasoning_into_content_when_state_has_content() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking...", is_thinking=True)

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="hello"), chunk
    )

    assert result.content == "thinking..."
    assert result.reasoning_content == ""
    assert result.is_thinking is False
    assert result.metadata.get("deepseek_reasoning_rerouted_to_content") is True


def test_normalize_preserves_existing_metadata_when_rerouting() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="more", metadata={"trace_id": "abc"})

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result.metadata["trace_id"] == "abc"
    assert result.metadata["deepseek_reasoning_rerouted_to_content"] is True


def test_normalize_returns_new_chunk_instance() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking")

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result is not chunk


# -- normalize_provider_stream_chunk: guard conditions --------------------


def test_normalize_short_circuits_for_non_deepseek_provider() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking", is_thinking=True)

    result = normalizer.normalize_provider_stream_chunk(
        _request(provider="openai"), _state(content="hi"), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_state_has_no_content() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking", is_thinking=True)

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content=""), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_chunk_has_no_reasoning_content() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="")

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_chunk_already_has_content() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(content="answer", reasoning_content="extra")

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_chunk_has_tool_calls() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(
        reasoning_content="extra",
        tool_calls=[{"id": "c1", "function": {"name": "x", "arguments": "{}"}}],
    )

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_chunk_has_images() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(
        reasoning_content="extra",
        images=[GeneratedImage(mime_type="image/png", url="https://x/y.png")],
    )

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result is chunk


def test_normalize_short_circuits_when_provider_is_none() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking")
    req = ChatRequestDTO(message="hi", provider=None)

    result = normalizer.normalize_provider_stream_chunk(
        req, _state(content="x"), chunk
    )

    assert result is chunk


def test_normalize_handles_empty_metadata_safely() -> None:
    normalizer = StreamChunkNormalizer()
    chunk = StreamChunk(reasoning_content="thinking", metadata={})

    result = normalizer.normalize_provider_stream_chunk(
        _request(), _state(content="x"), chunk
    )

    assert result.metadata == {"deepseek_reasoning_rerouted_to_content": True}


# -- empty_model_response_notice -------------------------------------------


def test_empty_model_response_notice_includes_provider_and_model() -> None:
    normalizer = StreamChunkNormalizer()

    notice = normalizer.empty_model_response_notice(provider="deepseek", model="r1")

    assert "Provider: deepseek" in notice
    assert "model: r1" in notice


def test_empty_model_response_notice_mentions_tool_execution() -> None:
    normalizer = StreamChunkNormalizer()

    notice = normalizer.empty_model_response_notice(provider="p", model="m")

    assert "tool execution" in notice
    assert "empty terminal response" in notice


def test_empty_model_response_notice_handles_empty_provider() -> None:
    normalizer = StreamChunkNormalizer()

    notice = normalizer.empty_model_response_notice(provider="", model="")

    assert "Provider: ;" in notice
    assert "model: ;" in notice or "model: ." in notice or "model:" in notice
    assert notice  # non-empty


def test_empty_model_response_notice_is_deterministic() -> None:
    normalizer = StreamChunkNormalizer()

    first = normalizer.empty_model_response_notice(provider="p", model="m")
    second = normalizer.empty_model_response_notice(provider="p", model="m")

    assert first == second
