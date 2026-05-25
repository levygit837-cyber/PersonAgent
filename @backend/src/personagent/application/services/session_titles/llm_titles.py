"""LLM-backed title generation for sessions."""

from __future__ import annotations

import json
from typing import Any

import structlog

from personagent.application.services.session_titles._common import _sanitize_title
from personagent.domain.models.conversation import Conversation, Message
from personagent.domain.repositories.llm_backend_repository import LLMBackendRepository

logger = structlog.get_logger(__name__)

_TITLE_SYSTEM_PROMPT = """You rename PersonAgent chat sessions.

Rules:
- Analyze the whole provided session history, not only the first message.
- Produce one short natural-language phrase per session in English, even when the source history is in another language.
- Keep each title under 9 words and under 72 characters.
- Avoid generic titles such as "New Chat", "Test", "Chat", "Session", or titles based only on the first user message.
- Titles must be distinct from each other and from existing_titles. If two sessions discuss similar topics, include a concrete differentiator from the history.
- Prefer concrete nouns from the actual task, repo, tool, provider, or bug discussed.
- Do not invent projects, files, providers, or outcomes that are not present in the history.
- Do not mention that you are generating titles.

Return only compact JSON:
{"titles":[{"id":"<session id>","title":"<short unique title>"}]}"""


class TitleGenerator:
    """Generates session titles using LLM backends."""

    def __init__(
        self,
        *,
        primary_llm_backend: LLMBackendRepository | None,
        fallback_llm_backend: LLMBackendRepository | None = None,
        primary_provider: str,
        primary_model: str,
        fallback_provider: str,
        fallback_model: str,
        max_history_chars: int,
    ) -> None:
        self._primary_llm_backend = primary_llm_backend
        self._fallback_llm_backend = fallback_llm_backend
        self._primary_provider = primary_provider
        self._primary_model = primary_model
        self._fallback_provider = fallback_provider
        self._fallback_model = fallback_model
        self._max_history_chars = max_history_chars

    async def generate_titles_for_batch(
        self,
        conversations: list[Conversation],
        *,
        existing_titles: list[str],
    ) -> tuple[dict[str, str], str, str]:
        """Generate titles for a batch of conversations using LLM."""
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
                single, single_source, _reason = await self.generate_titles_for_batch(
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
