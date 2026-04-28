"""Data Transfer Objects para o caso de uso de chat."""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from personagent.domain.models.inference_result import GeneratedImage


@dataclass(frozen=True, slots=True)
class ChatRequestDTO:
    """DTO para requisição de chat."""

    conversation_id: UUID | None = None
    message: str = ""
    system_prompt: str | None = None
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = -1
    provider: str = "llama"
    model: str = "local-model"
    prompt_mode: str = "auto"
    reasoning_level: str | None = None
    reasoning_budget_tokens: int | None = None
    tools_enabled: bool = True
    allowed_tools: list[str] | None = None
    tool_context: dict[str, Any] = field(default_factory=dict)
    max_tool_iterations: int | None = None
    context_attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatResponseDTO:
    """DTO para resposta de chat."""

    conversation_id: UUID
    message_id: str
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    model: str | None = None
    provider: str | None = None
    images: list[GeneratedImage] = field(default_factory=list)
    is_streaming: bool = False
