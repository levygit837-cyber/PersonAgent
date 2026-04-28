"""Domain conversation entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class Role(Enum):
    """Role of a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """One individual message in the conversation."""

    role: Role
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the message to an LLM API-compatible format."""
        result: dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create a Message from a dictionary."""
        return cls(
            role=Role(data.get("role", "assistant")),
            content=data.get("content", ""),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Conversation:
    """One complete conversation thread."""

    id: UUID = field(default_factory=uuid4)
    title: str = "New Chat"
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    model_config_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation."""
        self.messages.append(message)
        self.updated_at = datetime.utcnow()

    def get_messages_for_llm(self, system_prompt: str | None = None) -> list[dict[str, Any]]:
        """Return messages in the format expected by LLM APIs."""
        result: list[dict[str, Any]] = []
        if system_prompt:
            result.append({"role": "system", "content": system_prompt})
        result.extend(msg.to_dict() for msg in self.messages)
        return result

    def generate_title(self, max_length: int = 50) -> str:
        """Generate a title from the first user message."""
        for msg in self.messages:
            if msg.role == Role.USER:
                title = msg.content.strip().replace("\n", " ")
                if len(title) > max_length:
                    title = title[:max_length].rsplit(" ", 1)[0] + "..."
                return title or "New Chat"
        return self.title
