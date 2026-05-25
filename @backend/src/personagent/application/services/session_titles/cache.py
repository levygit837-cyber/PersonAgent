"""Cache and persistent storage for session titles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from personagent.application.services.session_titles._common import (
    _is_generic_title,
    _normalize_title,
    _sanitize_title,
)
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository

if TYPE_CHECKING:
    from personagent.application.services.session_titles import SessionTitleResult

SESSION_TITLE_CACHE_KEY = "session_title_analysis"
SESSION_TITLE_CACHE_VERSION = 1


class TitleCache:
    """Handles history hashing, cache lookups, and persisted title application."""

    def __init__(
        self,
        *,
        primary_provider: str,
        primary_model: str,
        fallback_provider: str,
        fallback_model: str,
    ) -> None:
        self._primary_provider = primary_provider
        self._primary_model = primary_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model

    def history_hash(self, conversation: Conversation) -> str:
        digest = sha256()
        for message in conversation.messages:
            digest.update(message.role.value.encode("utf-8"))
            digest.update(b"\0")
            digest.update(message.content.encode("utf-8", errors="replace"))
            digest.update(b"\0")
            if message.tool_calls:
                digest.update(json.dumps(message.tool_calls, sort_keys=True).encode("utf-8"))
            digest.update(b"\0")
            if message.tool_call_id:
                digest.update(message.tool_call_id.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def cached_title(self, conversation: Conversation, history_hash: str) -> str | None:
        cache = conversation.metadata.get(SESSION_TITLE_CACHE_KEY)
        if not isinstance(cache, dict):
            return None
        if cache.get("version") != SESSION_TITLE_CACHE_VERSION:
            return None
        if cache.get("history_hash") != history_hash:
            return None
        title = _sanitize_title(str(cache.get("title") or ""))
        if _is_generic_title(title):
            return None
        return title

    async def apply_title(
        self,
        repo: ConversationRepository,
        conversation: Conversation,
        title: str,
        *,
        history_hash: str,
        source: str,
        dry_run: bool,
        reason: str = "",
    ) -> SessionTitleResult:
        from personagent.application.services.session_titles import SessionTitleResult

        old_title = conversation.title
        status = "cached" if source == "cache" else "updated"
        if _normalize_title(old_title) == _normalize_title(title) and source == "cache":
            status = "cached"
        elif _normalize_title(old_title) == _normalize_title(title):
            status = "skipped"

        if not dry_run:
            conversation.title = title
            conversation.metadata[SESSION_TITLE_CACHE_KEY] = {
                "version": SESSION_TITLE_CACHE_VERSION,
                "history_hash": history_hash,
                "title": title,
                "source": source,
                "provider": (
                    self._primary_provider
                    if source == "llm"
                    else self._fallback_provider
                    if source == "llm_fallback"
                    else None
                ),
                "model": (
                    self._primary_model
                    if source == "llm"
                    else self._fallback_model
                    if source == "llm_fallback"
                    else None
                ),
                "message_count": len(conversation.messages),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            await repo.update(conversation)

        return SessionTitleResult(
            conversation_id=str(conversation.id),
            old_title=old_title,
            new_title=title,
            status=status,
            source=source,
            history_hash=history_hash,
            reason=reason,
        )
