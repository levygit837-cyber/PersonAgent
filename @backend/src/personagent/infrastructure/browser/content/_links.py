"""Link extraction and opened-page bookkeeping helpers for BrowserContent."""

from __future__ import annotations

import time

from personagent.infrastructure.browser.models import BrowserOpenedPage
from personagent.infrastructure.browser.scripts.content_cleanup import (
    MARKDOWN_LINK_PATTERN as _MARKDOWN_LINK_PATTERN,
)


class _LinkExtractionMixin:
    """Methods for extracting links and tracking opened-page state."""

    def _extract_links_from_content(self, content: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in _MARKDOWN_LINK_PATTERN.finditer(content):
            text = " ".join(match.group(1).split())
            url = match.group(2).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"url": url, "text": text})
            if len(links) >= 50:
                break
        return links

    def _mark_opened_page_extracted(self, opened_page: BrowserOpenedPage) -> None:
        opened_page.extraction_count += 1
        opened_page.last_extracted_at = time.monotonic()
