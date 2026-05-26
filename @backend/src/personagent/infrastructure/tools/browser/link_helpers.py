"""Link processing helpers for browser tools.

Extracted from ``helpers.py`` as part of browser_tools helpers Slice A.
Pure functions and constants for link curation, filtering, and extraction.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETURNED_LINKS = 20
_LINK_SUPPRESSION_THRESHOLD = 24
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_LOW_QUALITY_LINK_TEXT = {
    "about",
    "advertise",
    "all",
    "author",
    "careers",
    "category",
    "contact",
    "deals",
    "follow",
    "games",
    "home",
    "login",
    "more",
    "privacy",
    "read more",
    "search",
    "see all",
    "see more",
    "share",
    "shop",
    "sign in",
    "sign up",
    "subscribe",
    "tag",
    "terms",
    "topics",
}
_LOW_QUALITY_PATH_MARKERS = (
    "/about",
    "/advert",
    "/author/",
    "/authors/",
    "/category/",
    "/contact",
    "/deals",
    "/gift",
    "/login",
    "/newsletter",
    "/privacy",
    "/search",
    "/shop",
    "/sitemap",
    "/tag/",
    "/tags/",
    "/terms",
    "/topics/",
    "/vetted/",
)

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def _extract_markdown_links(content: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for match in _MARKDOWN_LINK_PATTERN.finditer(content):
        links.append({"text": " ".join(match.group(1).split()), "url": match.group(2).strip()})
    return links


def _coerce_links(raw_links: Any) -> list[dict[str, str]]:
    if not isinstance(raw_links, list):
        return []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_links:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "text": " ".join(str(item.get("text") or "").split())})
    return links


def _curate_links(
    raw_links: list[dict[str, str]],
    *,
    content: str,
    source_url: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    unique_links = _coerce_links(raw_links)
    low_quality = [link for link in unique_links if _is_low_quality_link(link, source_url)]
    suppress = False
    reason = ""
    if len(unique_links) >= _LINK_SUPPRESSION_THRESHOLD:
        low_quality_ratio = len(low_quality) / max(1, len(unique_links))
        markdown_link_count = len(_MARKDOWN_LINK_PATTERN.findall(content))
        if low_quality_ratio >= 0.55 or markdown_link_count >= _LINK_SUPPRESSION_THRESHOLD:
            suppress = True
            reason = "link_dense_navigation_or_low_quality_links"
    returned = [] if suppress else unique_links[:_MAX_RETURNED_LINKS]
    return returned, {
        "total": len(unique_links),
        "returned": len(returned),
        "suppressed": suppress,
        "reason": reason,
        "max_returned": _MAX_RETURNED_LINKS,
    }


def _is_low_quality_link(link: dict[str, str], source_url: str) -> bool:
    url = str(link.get("url") or "")
    text = " ".join(str(link.get("text") or "").lower().split())
    parsed = urlparse(url)
    source = urlparse(source_url)
    path = parsed.path.lower()
    if not text or text in _LOW_QUALITY_LINK_TEXT:
        return True
    if any(marker in path for marker in _LOW_QUALITY_PATH_MARKERS):
        return True
    if parsed.netloc == source.netloc and path in {"", "/"}:
        return True
    return len(text) <= 3 and not any(char.isdigit() for char in text)
