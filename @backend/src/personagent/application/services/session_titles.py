"""LLM-backed session title verification and deduplication."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any
from uuid import UUID

import structlog

from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.domain.repositories.conversation_repository import ConversationRepository
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

SESSION_TITLE_CACHE_KEY = "session_title_analysis"
SESSION_TITLE_CACHE_VERSION = 1
DEFAULT_PRIMARY_PROVIDER = "nvidia"
DEFAULT_PRIMARY_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_PROVIDER = "llama"
DEFAULT_FALLBACK_MODEL = "local-model"
DEFAULT_BATCH_SIZE = 6
DEFAULT_SCAN_LIMIT = 10_000
DEFAULT_MAX_HISTORY_CHARS = 180_000
DEFAULT_DUPLICATE_CHECK_INTERVAL_SECONDS = 300.0
DEFAULT_SIMILARITY_THRESHOLD = 0.9
MAX_TITLE_CHARS = 72
MAX_TITLE_WORDS = 9

_GENERIC_TITLES = {
    "",
    "chat",
    "conversa",
    "nova conversa",
    "nova sessao",
    "nova sessão",
    "sessao",
    "sessão",
    "sem titulo",
    "sem título",
    "teste",
    "untitled",
}

_STOPWORDS = {
    "a",
    "agora",
    "ai",
    "as",
    "com",
    "como",
    "da",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "essa",
    "esse",
    "esta",
    "este",
    "eu",
    "for",
    "me",
    "na",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "que",
    "quero",
    "the",
    "uma",
    "um",
    "voce",
    "você",
}


@dataclass(slots=True)
class SessionTitleResult:
    """Result for one conversation title verification."""

    conversation_id: str
    old_title: str
    new_title: str
    status: str
    source: str
    history_hash: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "conversation_id": self.conversation_id,
            "old_title": self.old_title,
            "new_title": self.new_title,
            "status": self.status,
            "source": self.source,
            "history_hash": self.history_hash,
            "reason": self.reason,
        }


@dataclass(slots=True)
class SessionTitleBatchResult:
    """Aggregate result for a batch/all-session title verification."""

    checked: int = 0
    analyzed: int = 0
    updated: int = 0
    cached: int = 0
    skipped: int = 0
    failed: int = 0
    batches: int = 0
    duplicate_groups: int = 0
    primary_model: str = DEFAULT_PRIMARY_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    results: list[SessionTitleResult] = field(default_factory=list)

    def add(self, result: SessionTitleResult) -> None:
        self.checked += 1
        if result.status == "updated":
            self.updated += 1
        elif result.status == "cached":
            self.cached += 1
        elif result.status == "skipped":
            self.skipped += 1
        elif result.status == "failed":
            self.failed += 1
        if result.source in {"llm", "llm_fallback"}:
            self.analyzed += 1
        self.results.append(result)

    def merge(self, other: SessionTitleBatchResult) -> None:
        self.checked += other.checked
        self.analyzed += other.analyzed
        self.updated += other.updated
        self.cached += other.cached
        self.skipped += other.skipped
        self.failed += other.failed
        self.batches += other.batches
        self.duplicate_groups += other.duplicate_groups
        self.results.extend(other.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "analyzed": self.analyzed,
            "updated": self.updated,
            "cached": self.cached,
            "skipped": self.skipped,
            "failed": self.failed,
            "batches": self.batches,
            "duplicate_groups": self.duplicate_groups,
            "primary_model": self.primary_model,
            "fallback_model": self.fallback_model,
            "results": [result.to_dict() for result in self.results],
        }


class SessionTitleService:
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
                unique_title = self._unique_title(self._fallback_title(conversation), conversation, uniqueness)
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

        generated, source, reason = await self._generate_titles_for_batch(
            [conversation for conversation, _hash in pending],
            existing_titles=uniqueness.titles(),
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

    async def _generate_titles_for_batch(
        self,
        conversations: list[Conversation],
        *,
        existing_titles: Iterable[str],
    ) -> tuple[dict[str, str], str, str]:
        if not conversations:
            return {}, "none", ""
        payload = {
            "existing_titles": list(existing_titles)[:500],
            "sessions": [
                {
                    "id": str(conversation.id),
                    "current_title": conversation.title,
                    "created_at": conversation.created_at.isoformat(),
                    "updated_at": conversation.updated_at.isoformat(),
                    "message_count": len(conversation.messages),
                    "history": self._render_history(conversation.messages),
                }
                for conversation in conversations
            ],
        }

        primary = await self._call_title_llm(
            self._primary_llm_backend,
            provider=self._primary_provider,
            model=self._primary_model,
            payload=payload,
            batch_size=len(conversations),
        )
        if primary is not None:
            return primary, "primary", ""

        fallback = await self._call_title_llm(
            self._fallback_llm_backend,
            provider=self._fallback_provider,
            model=self._fallback_model,
            payload=payload,
            batch_size=len(conversations),
        )
        if fallback is not None:
            return fallback, "fallback", "primary_failed"

        if len(conversations) > 1:
            merged: dict[str, str] = {}
            split_existing = list(existing_titles)
            used_fallback = False
            for conversation in conversations:
                single, single_source, _reason = await self._generate_titles_for_batch(
                    [conversation],
                    existing_titles=split_existing,
                )
                if single:
                    merged.update(single)
                    split_existing.extend(single.values())
                    used_fallback = used_fallback or single_source == "fallback"
            if merged:
                return (
                    merged,
                    "fallback" if used_fallback else "primary",
                    "split_after_batch_failure",
                )

        return {}, "fallback_error", "all_llm_generation_failed"

    async def _call_title_llm(
        self,
        llm_backend: LLMBackendRepository | None,
        *,
        provider: str,
        model: str,
        payload: dict[str, Any],
        batch_size: int,
    ) -> dict[str, str] | None:
        if llm_backend is None:
            return None
        try:
            response = await llm_backend.chat_completion(
                messages=[
                    {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=max(4_096, min(8_192, 768 * max(1, batch_size) + 512)),
                stream=False,
                tools=None,
                tool_choice=None,
                model=model,
                provider=provider,
                reasoning_level="low",
                reasoning_budget_tokens=0,
            )
            return _parse_title_response(response.content or response.reasoning_content)
        except Exception as exc:
            logger.warning(
                "session_title_llm_failed",
                provider=provider,
                model=model,
                error_type=type(exc).__name__,
                error=str(exc)[:240],
            )
            return None

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
        return _fit_title(f"Sessao {str(conversation.id).split('-', 1)[0]}")

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

    def _render_history(self, messages: list[Message]) -> str:
        if not messages:
            return "(empty session)"
        per_message_limit = max(1_000, min(8_000, self._max_history_chars // len(messages)))
        rendered: list[str] = []
        total = 0
        for index, message in enumerate(messages, start=1):
            content = message.content.strip()
            if len(content) > per_message_limit:
                content = f"{content[:per_message_limit].rstrip()}\n[message truncated]"
            block = f"## {index}. {message.role.value}\n{content}"
            if message.tool_calls:
                block += f"\nTool calls: {message.tool_calls}"
            if message.metadata:
                tool_name = message.metadata.get("tool_name")
                finish_reason = message.metadata.get("finish_reason")
                metadata_bits = {
                    key: value
                    for key, value in {
                        "tool_name": tool_name,
                        "finish_reason": finish_reason,
                    }.items()
                    if value
                }
                if metadata_bits:
                    block += f"\nMetadata: {metadata_bits}"
            total += len(block)
            if total > self._max_history_chars:
                rendered.append("[session history truncated to title-analysis budget]")
                break
            rendered.append(block)
        return "\n\n".join(rendered)

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


class _TitleUniqueness:
    def __init__(self, existing_titles: Iterable[str], similarity_threshold: float) -> None:
        self._similarity_threshold = similarity_threshold
        self._titles: list[str] = []
        self._normalized: set[str] = set()
        for title in existing_titles:
            self.add(title)

    def accepts(self, title: str) -> bool:
        normalized = _normalize_title(title)
        if not normalized or normalized in self._normalized:
            return False
        return all(
            _title_similarity(normalized, existing) < self._similarity_threshold
            for existing in self._normalized
        )

    def add(self, title: str) -> None:
        normalized = _normalize_title(title)
        if normalized:
            self._normalized.add(normalized)
            self._titles.append(title)

    def titles(self) -> list[str]:
        return list(self._titles)


def _parse_title_response(content: str) -> dict[str, str]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])

    items = payload.get("titles") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("title response must contain a titles list")
    parsed: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or item.get("conversation_id") or "").strip()
        title = _sanitize_title(str(item.get("title") or ""))
        if raw_id and title:
            parsed[raw_id] = title
    if not parsed:
        raise ValueError("title response did not contain usable titles")
    return parsed


def _sanitize_title(title: str) -> str:
    cleaned = " ".join(title.replace("\n", " ").replace("\r", " ").split())
    cleaned = cleaned.strip(" \"'`*_#:-.")
    if cleaned.lower().startswith("title:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    words = cleaned.split()
    if len(words) > MAX_TITLE_WORDS:
        cleaned = " ".join(words[:MAX_TITLE_WORDS])
    return _fit_title(cleaned)


def _fit_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if len(cleaned) <= MAX_TITLE_CHARS:
        return cleaned
    clipped = cleaned[:MAX_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    return clipped or cleaned[:MAX_TITLE_CHARS].strip()


def _is_generic_title(title: str) -> bool:
    return _normalize_title(title) in _GENERIC_TITLES


def _normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"[^\wÀ-ÿ]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _keyword_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[\wÀ-ÿ]{3,}", text.lower(), flags=re.UNICODE)
    return [token for token in tokens if token not in _STOPWORDS][:12]


def _date_suffix(conversation: Conversation) -> str:
    try:
        return conversation.updated_at.strftime("%d%m %H%M")
    except Exception:
        return ""


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


_TITLE_SYSTEM_PROMPT = """You rename PersonAgent chat sessions.

Rules:
- Analyze the whole provided session history, not only the first message.
- Produce one short natural-language phrase per session, preferably Portuguese when the session is Portuguese.
- Keep each title under 9 words and under 72 characters.
- Avoid generic titles such as "Nova Conversa", "Teste", "Chat", "Sessao", or titles based only on the first user message.
- Titles must be distinct from each other and from existing_titles. If two sessions discuss similar topics, include a concrete differentiator from the history.
- Do not mention that you are generating titles.

Return only compact JSON:
{"titles":[{"id":"<session id>","title":"<short unique title>"}]}"""
