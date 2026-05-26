"""Shared constants and helpers for session title services."""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from personagent.domain.conversation.models import Conversation

MAX_TITLE_CHARS = 72
MAX_TITLE_WORDS = 9

_GENERIC_TITLES = {
    "",
    "chat",
    "new chat",
    "new conversation",
    "session",
    "test",
    "untitled",
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
}


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
