"""Private helper methods extracted from SessionTitleService."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from personagent.application.services.session_titles._common import (
    _date_suffix,
    _fit_title,
    _is_generic_title,
    _keyword_tokens,
    _normalize_title,
    _sanitize_title,
    _title_similarity,
)
from personagent.application.services.session_titles._models import (
    SESSION_TITLE_CACHE_KEY,
    SESSION_TITLE_CACHE_VERSION,
    SessionTitleBatchResult,
    SessionTitleResult,
)
from personagent.application.services.session_titles._uniqueness import _TitleUniqueness
from personagent.domain.conversation.models import Conversation, Role
from personagent.domain.conversation.repositories import ConversationRepository


class _SessionTitleServiceHelpersMixin:
    async def _apply_title(
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

    async def _list_summaries(
        self,
        repo: ConversationRepository,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        list_summaries = getattr(repo, "list_summaries", None)
        if callable(list_summaries):
            return list(await list_summaries(limit=limit, offset=offset))

        conversations = await repo.list_all(limit=limit, offset=offset)
        return [
            {
                "id": str(conversation.id),
                "title": conversation.title,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
                "message_count": len(conversation.messages),
            }
            for conversation in conversations
        ]

    async def _load_conversations_by_id(
        self,
        repo: ConversationRepository,
        ids: Iterable[str],
    ) -> list[Conversation]:
        conversations: list[Conversation] = []
        for raw_id in ids:
            try:
                parsed_id = UUID(str(raw_id))
            except ValueError:
                continue
            conversation = await repo.get_by_id(parsed_id)
            if conversation is not None:
                conversations.append(conversation)
        return conversations

    def _duplicate_title_ids(
        self,
        summaries: list[dict[str, Any]],
    ) -> tuple[list[str], int]:
        normalized_seen: dict[str, str] = {}
        duplicate_ids: list[str] = []
        groups = 0
        for summary in summaries:
            raw_id = str(summary.get("id") or "")
            title = str(summary.get("title") or "")
            normalized = _normalize_title(title)
            if not raw_id or not normalized:
                continue
            if normalized in normalized_seen:
                duplicate_ids.append(raw_id)
                groups += 1
                continue
            similar_to_existing = any(
                _title_similarity(normalized, existing) >= self._similarity_threshold
                for existing in normalized_seen
            )
            if similar_to_existing:
                duplicate_ids.append(raw_id)
                groups += 1
                continue
            normalized_seen[normalized] = raw_id
        return duplicate_ids, groups

    def _cached_title(self, conversation: Conversation, history_hash: str) -> str | None:
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

    def _unique_title(
        self,
        candidate: str,
        conversation: Conversation,
        uniqueness: _TitleUniqueness,
    ) -> str:
        title = _sanitize_title(candidate)
        if _is_generic_title(title):
            title = self._fallback_title(conversation)
        if uniqueness.accepts(title):
            uniqueness.add(title)
            return title

        suffixes = [
            self._distinctive_suffix(conversation, title),
            _date_suffix(conversation),
            str(conversation.id).split("-", 1)[0],
        ]
        for suffix in suffixes:
            if not suffix:
                continue
            adjusted = _fit_title(f"{title} {suffix}")
            if uniqueness.accepts(adjusted):
                uniqueness.add(adjusted)
                return adjusted

        fallback = _fit_title(f"{title} {str(conversation.id).replace('-', '')[:8]}")
        uniqueness.add(fallback)
        return fallback

    def _fallback_title(self, conversation: Conversation) -> str:
        for message in reversed(conversation.messages):
            if message.role == Role.USER and message.content.strip():
                title = _sanitize_title(message.content)
                if not _is_generic_title(title):
                    return title
        for message in conversation.messages:
            if message.content.strip():
                title = _sanitize_title(message.content)
                if not _is_generic_title(title):
                    return title
        return _fit_title(f"Session {str(conversation.id).split('-', 1)[0]}")

    def _distinctive_suffix(self, conversation: Conversation, base_title: str) -> str:
        base_tokens = set(_keyword_tokens(base_title))
        for message in reversed(conversation.messages):
            if not message.content.strip():
                continue
            tokens = [
                token for token in _keyword_tokens(message.content)
                if token not in base_tokens
            ]
            if tokens:
                return " ".join(tokens[:2])
        return ""

    def _history_hash(self, conversation: Conversation) -> str:
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

    def _new_batch_result(self) -> SessionTitleBatchResult:
        return SessionTitleBatchResult(
            primary_model=self._primary_model,
            fallback_model=self._fallback_model,
        )
