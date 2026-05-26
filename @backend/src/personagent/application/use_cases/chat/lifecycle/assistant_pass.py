"""Single assistant pass of a streaming chat turn.

A "pass" is one call to ``llm_backend.chat_completion_stream`` plus
the per-chunk bookkeeping that wires the resulting :class:`StreamChunk`
stream into the per-turn accumulator (:class:`AssistantStreamState`).
The streaming turn loop runs this pass at least once per iteration
and may run it a second time for the "empty tool response" retry
branch, so it is extracted into its own collaborator to keep both
call sites in one place.

The runner has no per-turn state of its own; everything lives on the
:class:`AssistantStreamState` object passed in by the caller. The
runner is fully synchronous to construct -- it just bundles the
collaborators it needs to forward chunks correctly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.messaging.media_policy import MediaPolicyHandler
from personagent.application.use_cases.chat.messaging.state import AssistantStreamState
from personagent.application.use_cases.chat.streaming.normalization import (
    StreamChunkNormalizer,
)
from personagent.application.use_cases.chat.tooling.tool_results import ToolResultHandler
from personagent.domain.llm_backend.models import StreamChunk
from personagent.domain.llm_backend.repositories import LLMBackendRepository


class AssistantPassRunner:
    """Runs a single assistant streaming pass and forwards chunks."""

    def __init__(
        self,
        *,
        llm_backend: LLMBackendRepository,
        stream_chunk_normalizer: StreamChunkNormalizer,
        media_policy: MediaPolicyHandler,
        tool_results: ToolResultHandler,
    ) -> None:
        self._llm_backend = llm_backend
        self._stream_chunk_normalizer = stream_chunk_normalizer
        self._media_policy = media_policy
        self._tool_results = tool_results

    async def run(
        self,
        *,
        request: ChatRequestDTO,
        conversation_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        seen_tool_call_ids: set[str],
        iteration: int,
        state: AssistantStreamState,
    ) -> AsyncIterator[StreamChunk]:
        """Stream one assistant pass, mutating *state* in place."""

        async for chunk in self._llm_backend.chat_completion_stream(
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=tools,
            tool_choice="auto" if tools else None,
            model=request.model,
            provider=request.provider,
            reasoning_level=request.reasoning_level,
            reasoning_budget_tokens=request.reasoning_budget_tokens,
        ):
            chunk = self._stream_chunk_normalizer.normalize_provider_stream_chunk(
                request, state, chunk
            )
            if chunk.images:
                chunk = replace(
                    chunk,
                    images=self._media_policy.store_generated_images(
                        conversation_id, chunk.images
                    ),
                )
            chunk_metadata = {
                "provider": request.provider,
                "model": request.model,
                **chunk.metadata,
            }
            if chunk.content:
                state.content_chunks.append(chunk.content)
            if chunk.reasoning_content:
                state.reasoning_chunks.append(chunk.reasoning_content)
            if chunk.images:
                state.images.extend(chunk.images)
            if chunk.tool_calls:
                state.tool_calls = self._tool_results.unique_call_ids(
                    chunk.tool_calls,
                    seen_tool_call_ids,
                    iteration,
                )
                state.finish_reason = "tool_calls"
            state.metadata.update(
                {
                    key: value
                    for key, value in chunk_metadata.items()
                    if key.startswith(("vertex_", "kimi_", "zenmux_", "deepseek_"))
                }
            )
            if chunk.finish_reason:
                internal_tool_stop = (
                    state.tool_calls is not None
                    and chunk.finish_reason != "tool_calls"
                    and not chunk.content
                    and not chunk.reasoning_content
                    and not chunk.images
                )
                if not internal_tool_stop:
                    state.finish_reason = chunk.finish_reason
            if chunk.usage:
                state.usage = chunk.usage
            state.model = str(chunk_metadata.get("model") or request.model)
            state.provider = str(chunk_metadata.get("provider") or request.provider)
            forwarded_finish_reason = self._tool_results.forwarded_finish_reason(
                chunk,
                has_pending_tool_calls=state.tool_calls is not None,
            )
            if (
                chunk.content
                or chunk.reasoning_content
                or chunk.images
                or forwarded_finish_reason
            ):
                yield StreamChunk(
                    content=chunk.content,
                    reasoning_content=chunk.reasoning_content,
                    finish_reason=forwarded_finish_reason,
                    usage=chunk.usage,
                    images=chunk.images,
                    is_thinking=chunk.is_thinking,
                    metadata=chunk_metadata,
                )


__all__ = ["AssistantPassRunner"]
