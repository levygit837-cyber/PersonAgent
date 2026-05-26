"""Stream parsing helpers for Kimi Code Anthropic-compatible API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from personagent.domain.exceptions import LLMBackendError
from personagent.domain.models.inference_result import StreamChunk
from personagent.infrastructure.llm.kimi_history import (
    anthropic_history_blocks,
    attach_anthropic_history_blocks,
    tool_call_from_anthropic_block,
)


@dataclass(slots=True)
class _AnthropicStreamState:
    model: str
    content_blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    thinking_signatures: list[str] = field(default_factory=list)
    finish_reason: str | None = None


class KimiStreamParser:
    """Parses Anthropic-compatible stream events and content blocks from Kimi."""

    def parse_stream_event(
        self,
        data: dict[str, Any],
        state: _AnthropicStreamState,
    ) -> tuple[StreamChunk, bool]:
        """Parse a single SSE event into a StreamChunk and done flag."""
        event_type = data.get("type")
        metadata = {"provider": "kimi", "model": state.model}

        if event_type == "error" or data.get("error"):
            raise LLMBackendError(
                f"Kimi Code stream error: {data.get('error') or data}"
            )

        if event_type == "message_start":
            message = data.get("message") or {}
            if message.get("model"):
                state.model = str(message["model"])
            return StreamChunk(), False

        if event_type == "content_block_start":
            index = int(data.get("index", 0))
            block = dict(data.get("content_block") or {})
            block.setdefault("_partial_json", "")
            state.content_blocks[index] = block
            return StreamChunk(), False

        if event_type == "content_block_delta":
            index = int(data.get("index", 0))
            block = state.content_blocks.setdefault(index, {})
            delta = data.get("delta") or {}
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                text = str(delta.get("text") or "")
                block["text"] = str(block.get("text") or "") + text
                return StreamChunk(content=text, metadata=metadata), False
            if delta_type == "thinking_delta":
                thinking = str(delta.get("thinking") or "")
                block["thinking"] = str(block.get("thinking") or "") + thinking
                return (
                    StreamChunk(
                        reasoning_content=thinking,
                        is_thinking=True,
                        metadata=metadata,
                    ),
                    False,
                )
            if delta_type == "signature_delta":
                signature = str(delta.get("signature") or "")
                if signature:
                    block["signature"] = signature
                    state.thinking_signatures.append(signature)
                    return (
                        StreamChunk(
                            metadata={
                                **metadata,
                                "kimi_thinking_signatures": [signature],
                            }
                        ),
                        False,
                    )
            if delta_type == "input_json_delta":
                block["_partial_json"] = str(block.get("_partial_json") or "") + str(
                    delta.get("partial_json") or ""
                )
            return StreamChunk(), False

        if event_type == "content_block_stop":
            return StreamChunk(), False

        if event_type == "message_delta":
            delta = data.get("delta") or {}
            state.finish_reason = self._finish_reason(
                delta.get("stop_reason"), False
            )
            if state.thinking_signatures:
                metadata["kimi_thinking_signatures"] = list(
                    state.thinking_signatures
                )
            tool_calls = (
                self._tool_calls_from_stream_state(state)
                if state.finish_reason == "tool_calls"
                else None
            )
            return (
                StreamChunk(
                    finish_reason=state.finish_reason,
                    tool_calls=tool_calls,
                    usage=data.get("usage"),
                    metadata=metadata,
                ),
                False,
            )

        if event_type == "message_stop":
            return StreamChunk(), True

        return StreamChunk(), False

    def parse_content_blocks(self, blocks: list[Any]) -> dict[str, Any]:
        """Extract text, reasoning, signatures and tool calls from content blocks."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        signatures: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for raw_block in blocks:
            if not isinstance(raw_block, dict):
                continue
            block_type = raw_block.get("type")
            if block_type == "text":
                content_parts.append(str(raw_block.get("text") or ""))
            elif block_type == "thinking":
                thinking = raw_block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    reasoning_parts.append(thinking)
                signature = raw_block.get("signature")
                if isinstance(signature, str) and signature:
                    signatures.append(signature)
            elif block_type == "tool_use":
                tool_calls.append(tool_call_from_anthropic_block(raw_block))

        history_blocks = anthropic_history_blocks(
            {
                index: block
                for index, block in enumerate(blocks)
                if isinstance(block, dict)
            }
        )
        attach_anthropic_history_blocks(tool_calls, history_blocks)

        return {
            "content": "".join(content_parts),
            "reasoning": "".join(reasoning_parts),
            "thinking_signatures": signatures,
            "tool_calls": tool_calls,
        }

    def _tool_calls_from_stream_state(
        self,
        state: _AnthropicStreamState,
    ) -> list[dict[str, Any]]:
        history_blocks = anthropic_history_blocks(state.content_blocks)
        tool_calls = [
            tool_call_from_anthropic_block(block)
            for _, block in sorted(state.content_blocks.items())
            if block.get("type") == "tool_use"
        ]
        attach_anthropic_history_blocks(tool_calls, history_blocks)
        return tool_calls

    def _finish_reason(self, raw: Any, has_tool_calls: bool) -> str | None:
        if has_tool_calls or raw == "tool_use":
            return "tool_calls"
        if raw == "end_turn":
            return "stop"
        if raw == "max_tokens":
            return "length"
        return str(raw) if raw else None
