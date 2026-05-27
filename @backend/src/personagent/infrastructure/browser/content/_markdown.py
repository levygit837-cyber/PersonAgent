"""Markdown / text extraction helpers for BrowserContent."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.scripts.content import (
    _READABLE_DOM_SCRIPT,
)
from personagent.infrastructure.browser.scripts.content_cleanup import (
    clean_extracted_content as _clean_extracted_content,
)
from personagent.infrastructure.browser.scripts.content_cleanup import (
    should_prefer_readable_dom as _should_prefer_readable_dom,
)
from personagent.infrastructure.browser.search.url_utils import (
    clean_browser_url as _clean_browser_url,
)


class _MarkdownExtractionMixin:
    """Methods for extracting markdown or text content from pages and URLs."""

    async def _markdown_or_text_page(
        self,
        page: Any,
        *,
        fallback_url: str,
    ) -> tuple[str, str, dict[str, Any]]:
        try:
            preparation = await asyncio.wait_for(
                self._prepare_page_for_extraction(page),
                timeout=min(max(self._w.timeout_ms / 1000, 1.0), 22.0),
            )
        except Exception as exc:
            fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
                fallback_url
            )
            return (
                fallback_content,
                fallback_method,
                {
                    **fallback_stats,
                    "prepared_page": False,
                    "prepare_error": str(exc),
                    "fallback": fallback_method,
                },
            )
        value: Any = None
        with suppress(Exception):
            value = await self._w._browser_runtime.evaluate_page(page, _READABLE_DOM_SCRIPT)
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                cleaned, stats = _clean_extracted_content(content)
                if cleaned:
                    return (
                        cleaned,
                        "prepared_readable_dom_text",
                        {
                            **stats,
                            **preparation,
                            "selected_tag": value.get("selected_tag"),
                            "readable_score": value.get("score"),
                        },
                    )
        elif isinstance(value, str):
            cleaned, stats = _clean_extracted_content(value)
            if cleaned:
                return cleaned, "prepared_dom_text", {**stats, **preparation}

        text = ""
        with suppress(Exception):
            value = await self._w._browser_runtime.evaluate_page(
                page,
                "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                "|| document.documentElement.textContent || '')",
            )
            if isinstance(value, str):
                text = value
        cleaned_text, text_stats = _clean_extracted_content(text)
        if cleaned_text:
            return cleaned_text, "prepared_dom_text", {**text_stats, **preparation}

        fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
            fallback_url
        )
        return (
            fallback_content,
            fallback_method,
            {
                **fallback_stats,
                **preparation,
                "fallback": fallback_method,
            },
        )

    async def _markdown_or_text(self, session: _BrowserSession) -> tuple[str, str, dict[str, Any]]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._markdown_or_text_url(url)

    async def _markdown_or_text_url(self, url: str) -> tuple[str, str, dict[str, Any]]:
        markdown = await self._w._markdown.lightpanda_markdown_url(url)
        if markdown:
            cleaned_markdown, stats = _clean_extracted_content(markdown)
            if _should_prefer_readable_dom(cleaned_markdown, stats):
                readable = await self._readable_dom_content_url(url)
                if readable:
                    return (
                        readable,
                        "readable_dom_text",
                        {
                            **stats,
                            "fallback": "readable_dom_text",
                        },
                    )
            if cleaned_markdown:
                method = (
                    "lightpanda_markdown_cleaned"
                    if stats.get("removed_link_noise_blocks")
                    else "lightpanda_markdown"
                )
                return cleaned_markdown, method, stats
        readable = await self._readable_dom_content_url(url)
        if readable:
            return readable, "readable_dom_text", {}
        text = await self._w._cdp_runtime.raw_runtime_evaluate_value(
            url,
            "(document.body && (document.body.innerText || document.body.textContent)) "
            "|| document.documentElement.textContent || ''",
            label="dom_text",
            timeout=min(self._w.timeout_ms / 1000, 5),
        )
        if not isinstance(text, str):
            return "", "dom_text_failed", {}
        cleaned_text, stats = _clean_extracted_content(text)
        return cleaned_text, "dom_text", stats

    async def _readable_dom_content_url(self, url: str) -> str:
        value = await self._w._cdp_runtime.raw_runtime_evaluate_value(
            url,
            _READABLE_DOM_SCRIPT,
            label="readable_dom",
            timeout=min(self._w.timeout_ms / 1000, 8),
        )
        if not isinstance(value, dict):
            return ""
        content = value.get("content")
        if not isinstance(content, str):
            return ""
        cleaned, _stats = _clean_extracted_content(content)
        return cleaned

    def _extract_markdown_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("markdown", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str):
            return payload
        return ""
