"""Readable-content cleanup helpers for browser extraction."""

from __future__ import annotations

import re
from typing import Any

MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

_MARKDOWN_ANY_LINK_PATTERN = re.compile(r"\[([^\]]*)]\([^)]*\)")
_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*]\([^)]*\)")
_MIN_READABLE_CONTENT_CHARS = 240
_NOISE_LINE_MARKERS = {
    "advertise",
    "advertisement",
    "all rights reserved",
    "cookie policy",
    "copyright",
    "follow us",
    "forbes logo",
    "privacy policy",
    "see all",
    "see more",
    "share a news tip",
    "sign in",
    "sign up",
    "sign up for newsletters",
    "subscribe",
    "terms of service",
}
_NOISE_LINE_SUBSTRINGS = (
    "crown each region",
    "frase by forbes",
    "guess the category",
    "mini crossword",
    "pinpoint by linkedin",
    "quick solve. big win",
    "queens by linkedin",
    "unscramble the anagram",
)


def clean_extracted_content(raw_content: str) -> tuple[str, dict[str, Any]]:
    """Remove navigation/link-list noise while preserving article text."""

    raw = str(raw_content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = _MARKDOWN_IMAGE_PATTERN.sub("", raw)
    raw_link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(raw)) + len(_URL_PATTERN.findall(raw))
    if not raw:
        return "", {
            "raw_chars": 0,
            "cleaned_chars": 0,
            "raw_link_count": 0,
            "removed_link_noise_blocks": 0,
        }

    kept_blocks: list[str] = []
    removed_blocks = 0
    for block in re.split(r"\n\s*\n+", raw):
        cleaned_block = clean_content_block(block)
        if not cleaned_block:
            continue
        if is_link_noise_block(block):
            removed_blocks += 1
            continue
        kept_blocks.append(cleaned_block)

    cleaned = "\n\n".join(kept_blocks)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if should_keep_raw_content(raw, cleaned, raw_link_count):
        cleaned = collapse_text_spacing(raw)
    return cleaned, {
        "raw_chars": len(raw),
        "cleaned_chars": len(cleaned),
        "raw_link_count": raw_link_count,
        "removed_link_noise_blocks": removed_blocks,
    }


def clean_content_block(block: str) -> str:
    lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = _MARKDOWN_ANY_LINK_PATTERN.sub(lambda match: match.group(1).strip(), line)
        line = _URL_PATTERN.sub("", line)
        line = re.sub(r"^[\-*+]\s+", "", line)
        line = collapse_text_spacing(line)
        if not line or is_noise_line(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def is_link_noise_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False
    link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(block)) + len(_URL_PATTERN.findall(block))
    if link_count < 6:
        return False
    link_only_lines = sum(1 for line in lines if is_link_only_line(line))
    if link_only_lines / max(1, len(lines)) >= 0.55:
        return True
    text_without_links = _MARKDOWN_ANY_LINK_PATTERN.sub("", block)
    text_without_links = _URL_PATTERN.sub("", text_without_links)
    non_link_chars = len(collapse_text_spacing(text_without_links))
    return link_count >= 12 and non_link_chars < link_count * 24


def is_link_only_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    link_count = len(_MARKDOWN_ANY_LINK_PATTERN.findall(stripped)) + len(
        _URL_PATTERN.findall(stripped)
    )
    if link_count == 0:
        return False
    without_links = _MARKDOWN_ANY_LINK_PATTERN.sub("", stripped)
    without_links = _URL_PATTERN.sub("", without_links)
    without_links = re.sub(r"^[\-*+]\s*", "", without_links)
    return len(collapse_text_spacing(without_links)) <= 12


def is_noise_line(line: str) -> bool:
    normalized = collapse_text_spacing(line).strip(" :-|").lower()
    if not normalized:
        return True
    if not any(char.isalnum() for char in normalized):
        return True
    if normalized in _NOISE_LINE_MARKERS:
        return True
    if any(marker in normalized for marker in _NOISE_LINE_SUBSTRINGS):
        return True
    return len(normalized) <= 4 and normalized in {"ad", "ads", "new", "more"}


def should_keep_raw_content(raw: str, cleaned: str, raw_link_count: int) -> bool:
    if len(cleaned) >= _MIN_READABLE_CONTENT_CHARS:
        return False
    if raw_link_count >= 12:
        return False
    return len(raw) > len(cleaned)


def should_prefer_readable_dom(cleaned: str, stats: dict[str, Any]) -> bool:
    raw_link_count = int(stats.get("raw_link_count") or 0)
    removed_blocks = int(stats.get("removed_link_noise_blocks") or 0)
    cleaned_chars = len(cleaned)
    if cleaned_chars < _MIN_READABLE_CONTENT_CHARS:
        return True
    return bool(raw_link_count >= 40 and removed_blocks)


def collapse_text_spacing(value: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", str(value or "")).strip()
