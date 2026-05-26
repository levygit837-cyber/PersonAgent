"""Session memory service for main chat conversations."""

from __future__ import annotations

from pathlib import Path

import structlog

from personagent.domain.conversation.models import Conversation, Message
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.domain.prompts.compact import (
    SESSION_MEMORY_TEMPLATE,
    SESSION_MEMORY_UPDATE_PROMPT,
)

logger = structlog.get_logger(__name__)


class SessionMemoryService:
    """Maintains controlled per-conversation Markdown memory files."""

    def __init__(
        self,
        llm_backend: LLMBackendRepository | None = None,
        root: str | Path | None = None,
    ) -> None:
        self._llm_backend = llm_backend
        self._root = Path(root).expanduser() if root else Path.home() / ".personagent" / "session-memory"

    def memory_path(self, conversation_id: str) -> Path:
        safe_id = "".join(ch for ch in conversation_id if ch.isalnum() or ch in "-_")[:96]
        return self._root / f"{safe_id or 'conversation'}.md"

    def load(self, conversation_id: str) -> str | None:
        path = self.memory_path(conversation_id)
        try:
            if not path.is_file():
                return None
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        return content or None

    async def update(
        self,
        conversation: Conversation,
        *,
        model: str,
        provider: str,
    ) -> str | None:
        if self._llm_backend is None:
            return None
        current = self.load(str(conversation.id)) or SESSION_MEMORY_TEMPLATE
        transcript = _render_recent_messages(conversation.messages)
        try:
            result = await self._llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": SESSION_MEMORY_UPDATE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "# Current Session Memory\n\n"
                            f"{current}\n\n"
                            "# Recent Conversation\n\n"
                            f"{transcript}"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=2_048,
                stream=False,
                tools=None,
                tool_choice=None,
                model=model,
                provider=provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
        except Exception:
            logger.warning("session_memory_update_failed", exc_info=True)
            return None
        content = result.content.strip()
        if not content:
            return None
        path = self.memory_path(str(conversation.id))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError:
            logger.warning("session_memory_write_failed", exc_info=True)
            return None
        return content


def _render_recent_messages(messages: list[Message], limit: int = 12) -> str:
    rendered: list[str] = []
    for index, message in enumerate(messages[-limit:], start=1):
        content = message.content
        if len(content) > 3_000:
            content = content[:3_000].rstrip() + "\n[truncated]"
        rendered.append(f"## {index}. {message.role.value}\n\n{content}")
        if message.tool_calls:
            rendered.append(f"Tool calls: {message.tool_calls}")
    return "\n\n".join(rendered)
