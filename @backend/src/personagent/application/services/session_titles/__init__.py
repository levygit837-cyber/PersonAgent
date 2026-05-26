"""LLM-backed session title verification and deduplication."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable

import structlog

from personagent.application.services.session_titles._common import _chunks
from personagent.application.services.session_titles._models import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_DUPLICATE_CHECK_INTERVAL_SECONDS,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_FALLBACK_PROVIDER,
    DEFAULT_MAX_HISTORY_CHARS,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_PRIMARY_PROVIDER,
    DEFAULT_SCAN_LIMIT,
    DEFAULT_SIMILARITY_THRESHOLD,
    SessionTitleBatchResult,
    SessionTitleResult,
)
from personagent.application.services.session_titles._models import (
    SESSION_TITLE_CACHE_KEY as SESSION_TITLE_CACHE_KEY,
)
from personagent.application.services.session_titles._models import (
    SESSION_TITLE_CACHE_VERSION as SESSION_TITLE_CACHE_VERSION,
)
from personagent.application.services.session_titles._service_helpers import (
    _SessionTitleServiceHelpersMixin,
)
from personagent.application.services.session_titles._uniqueness import _TitleUniqueness
from personagent.application.services.session_titles.llm_titles import TitleGenerator
from personagent.domain.models.conversation import Conversation
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)


class SessionTitleService(_SessionTitleServiceHelpersMixin):
    """Keeps persisted conversation titles short, unique, and cacheable."""

    def __init__(
        self,
        *,
        primary_llm_backend: LLMBackendRepository | None,
        fallback_llm_backend: LLMBackendRepository | None = None,
        primary_provider: str = DEFAULT_PRIMARY_PROVIDER,
        primary_model: str = DEFAULT_PRIMARY_MODEL,
        fallback_provider: str = DEFAULT_FALLBACK_PROVIDER,
        fallback_model: str = DEFAULT_FALLBACK_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        scan_limit: int = DEFAULT_SCAN_LIMIT,
        max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
        duplicate_check_interval_seconds: float = DEFAULT_DUPLICATE_CHECK_INTERVAL_SECONDS,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self._primary_llm_backend = primary_llm_backend
        self._fallback_llm_backend = fallback_llm_backend
        self._primary_provider = primary_provider
        self._primary_model = primary_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model
        self._batch_size = max(1, int(batch_size))
        self._scan_limit = max(1, int(scan_limit))
        self._max_history_chars = max(8_000, int(max_history_chars))
        self._duplicate_check_interval_seconds = max(
            0.0,
            float(duplicate_check_interval_seconds),
        )
        self._similarity_threshold = max(0.0, min(1.0, float(similarity_threshold)))
        self._last_duplicate_check_at = 0.0
        self._duplicate_check_lock = asyncio.Lock()
        self._title_generator = TitleGenerator(
            primary_llm_backend=primary_llm_backend,
            fallback_llm_backend=fallback_llm_backend,
            primary_provider=primary_provider,
            primary_model=primary_model,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            max_history_chars=self._max_history_chars,
        )

    async def refresh_title(
        self,
        repo: ConversationRepository,
        conversation: Conversation,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> SessionTitleResult:
        """Refresh one conversation title against all existing session titles."""
        summaries = await self._list_summaries(repo, limit=self._scan_limit)
        existing_titles = [
            str(summary.get("title") or "")
            for summary in summaries
            if str(summary.get("id") or "") != str(conversation.id)
        ]
        result = await self.refresh_conversations(
            repo,
            [conversation],
            force=force,
            dry_run=dry_run,
            existing_titles=existing_titles,
        )
        return result.results[0]

    async def verify_all(
        self,
        repo: ConversationRepository,
        *,
        limit: int | None = None,
        offset: int = 0,
        batch_size: int | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> SessionTitleBatchResult:
        """Verify every selected persisted session title in LLM batches."""
        summaries = await self._list_summaries(repo, limit=self._scan_limit, offset=0)
        selected = summaries[max(0, offset) :]
        if limit is not None:
            selected = selected[: max(0, limit)]

        target_id_list = [str(summary.get("id") or "") for summary in selected]
        target_ids = set(target_id_list)
        existing_titles = [
            str(summary.get("title") or "")
            for summary in summaries
            if str(summary.get("id") or "") not in target_ids
        ]

        aggregate = self._new_batch_result()
        size = max(1, int(batch_size or self._batch_size))
        for chunk in _chunks(target_id_list, size):
            conversations = await self._load_conversations_by_id(repo, chunk)
            batch_result = await self.refresh_conversations(
                repo,
                conversations,
                force=force,
                dry_run=dry_run,
                existing_titles=existing_titles,
            )
            aggregate.merge(batch_result)
            existing_titles.extend(result.new_title for result in batch_result.results)
        return aggregate

    async def refresh_conversations(
        self,
        repo: ConversationRepository,
        conversations: list[Conversation],
        *,
        force: bool = False,
        dry_run: bool = False,
        existing_titles: Iterable[str] = (),
    ) -> SessionTitleBatchResult:
        """Refresh a list of conversations, using one LLM call for uncached items."""
        result = self._new_batch_result()
        if not conversations:
            return result
        result.batches = 1

        uniqueness = _TitleUniqueness(existing_titles, self._similarity_threshold)
        pending: list[tuple[Conversation, str]] = []

        for conversation in conversations:
            history_hash = self._history_hash(conversation)
            cached_title = self._cached_title(conversation, history_hash)
            if cached_title and not force:
                unique_title = self._unique_title(cached_title, conversation, uniqueness)
                title_result = await self._apply_title(
                    repo,
                    conversation,
                    unique_title,
                    history_hash=history_hash,
                    source="cache",
                    dry_run=dry_run,
                    reason="history_hash_unchanged",
                )
                result.add(title_result)
                continue
            if not conversation.messages:
                unique_title = self._unique_title(
                    self._fallback_title(conversation), conversation, uniqueness
                )
                title_result = await self._apply_title(
                    repo,
                    conversation,
                    unique_title,
                    history_hash=history_hash,
                    source="deterministic",
                    dry_run=dry_run,
                    reason="empty_session",
                )
                result.add(title_result)
                continue
            pending.append((conversation, history_hash))

        if not pending:
            return result

        generated, source, reason = await self._title_generator.generate_titles_for_batch(
            [conversation for conversation, _hash in pending],
            existing_titles=list(uniqueness.titles()),
        )
        if source in {"llm_error", "fallback_error"}:
            logger.warning("session_title_batch_generation_failed", reason=reason)

        for conversation, history_hash in pending:
            candidate = generated.get(str(conversation.id))
            if not candidate:
                candidate = self._fallback_title(conversation)
                source_for_result = "deterministic"
            else:
                source_for_result = "llm_fallback" if source == "fallback" else "llm"
            unique_title = self._unique_title(candidate, conversation, uniqueness)
            title_result = await self._apply_title(
                repo,
                conversation,
                unique_title,
                history_hash=history_hash,
                source=source_for_result,
                dry_run=dry_run,
                reason=reason,
            )
            result.add(title_result)
        return result

    async def maybe_repair_duplicate_titles(
        self,
        repo: ConversationRepository,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> SessionTitleBatchResult:
        """Periodically repair exact or near-duplicate persisted titles."""
        now = time.monotonic()
        if (
            not force
            and self._last_duplicate_check_at
            and now - self._last_duplicate_check_at < self._duplicate_check_interval_seconds
        ):
            result = self._new_batch_result()
            return result

        async with self._duplicate_check_lock:
            now = time.monotonic()
            if (
                not force
                and self._last_duplicate_check_at
                and now - self._last_duplicate_check_at < self._duplicate_check_interval_seconds
            ):
                return self._new_batch_result()

            self._last_duplicate_check_at = now
            summaries = await self._list_summaries(repo, limit=self._scan_limit)
            duplicate_ids, duplicate_groups = self._duplicate_title_ids(summaries)
            result = self._new_batch_result()
            result.duplicate_groups = duplicate_groups
            if not duplicate_ids:
                return result

            conversations = await self._load_conversations_by_id(repo, duplicate_ids)
            existing_titles = [
                str(summary.get("title") or "")
                for summary in summaries
                if str(summary.get("id") or "") not in set(duplicate_ids)
            ]
            repaired = await self.refresh_conversations(
                repo,
                conversations,
                force=force,
                dry_run=dry_run,
                existing_titles=existing_titles,
            )
            repaired.duplicate_groups = duplicate_groups
            return repaired
