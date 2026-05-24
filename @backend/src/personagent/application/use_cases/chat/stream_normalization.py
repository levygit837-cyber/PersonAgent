"""Provider-aware streaming chunk normalisation + empty-response notice.

Two thin, stateless transforms that were previously private helpers
on :class:`ChatCompletionUseCase`:

* ``_normalize_provider_stream_chunk`` -- DeepSeek tail-end reasoning
  reroute. When the provider is DeepSeek and the assistant has
  already streamed content, but the current chunk only carries
  ``reasoning_content`` (no content / no tool calls / no images), the
  reasoning text is moved into ``content`` and the chunk is marked
  with ``deepseek_reasoning_rerouted_to_content=True`` in metadata.
  Every other provider / chunk shape is passed through verbatim.
* ``_empty_model_response_notice`` -- the canonical user-facing
  string the chat use case appends when a provider returns an empty
  terminal response after tool execution.

These are pure functions with no dependencies, so they're grouped
into :class:`StreamChunkNormalizer` to keep the slice-extraction
pattern consistent with the rest of ``chat/``. The class has no
runtime state; it exists to keep the collaborator-injection wiring
uniform with the other extracted handlers.
"""

from __future__ import annotations

from dataclasses import replace

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.use_cases.chat.state import AssistantStreamState
from personagent.domain.models.inference_result import StreamChunk


class StreamChunkNormalizer:
    """Provider-aware stream-chunk shaping (currently DeepSeek-only)."""

    def normalize_provider_stream_chunk(
        self,
        request: ChatRequestDTO,
        state: AssistantStreamState,
        chunk: StreamChunk,
    ) -> StreamChunk:
        """Reroute DeepSeek tail-end reasoning into ``content``.

        Only applies when *all* of the following hold:

        * the provider is ``"deepseek"``;
        * the assistant has already streamed some ``state.content``;
        * the incoming chunk carries ``reasoning_content`` but no
          ``content``, no ``tool_calls``, and no ``images``.

        In every other case the chunk is returned unchanged.
        """

        if (
            request.provider != "deepseek"
            or not state.content
            or not chunk.reasoning_content
            or chunk.content
            or chunk.tool_calls
            or chunk.images
        ):
            return chunk
        return replace(
            chunk,
            content=chunk.reasoning_content,
            reasoning_content="",
            is_thinking=False,
            metadata={
                **chunk.metadata,
                "deepseek_reasoning_rerouted_to_content": True,
            },
        )

    def empty_model_response_notice(self, *, provider: str, model: str) -> str:
        """Canonical notice for an empty terminal response after tool execution."""

        return (
            "The model stopped after tool execution without producing a visible final "
            f"answer. Provider: {provider}; model: {model}. The tool results were preserved, "
            "but the provider returned an empty terminal response."
        )


__all__ = ["StreamChunkNormalizer"]
