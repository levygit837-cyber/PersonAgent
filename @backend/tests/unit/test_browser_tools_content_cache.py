"""Unit tests for browser_tools/content_cache.py — content caching and chunking."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from personagent.infrastructure.tools.browser_tools.content_cache import (
    _DEFAULT_CHUNK_SIZE,
    _EXTRACT_INLINE_CONTENT_CHARS,
    _MAX_CHUNK_COUNT,
    _coerce_page_or_window_id,
    _prepare_extracted_content_response,
    _resolve_cache_key,
    _split_content_chunks,
    _trim_content,
)

# ---------------------------------------------------------------------------
# _coerce_page_or_window_id
# ---------------------------------------------------------------------------


class TestCoercePageOrWindowId:
    def test_prefers_page_id(self) -> None:
        assert _coerce_page_or_window_id("page-1", "window-1") == "page-1"

    def test_falls_back_to_window_id(self) -> None:
        assert _coerce_page_or_window_id(None, "window-1") == "window-1"

    def test_returns_none_when_both_empty(self) -> None:
        assert _coerce_page_or_window_id("", "") is None

    def test_returns_none_when_both_none(self) -> None:
        assert _coerce_page_or_window_id(None, None) is None

    def test_strips_whitespace(self) -> None:
        assert _coerce_page_or_window_id("  page-1  ", None) == "page-1"

    def test_skips_whitespace_only_page_id(self) -> None:
        assert _coerce_page_or_window_id("   ", "window-1") == "window-1"

    def test_non_string_page_id(self) -> None:
        assert _coerce_page_or_window_id(42, "window-1") == "window-1"

    def test_non_string_both(self) -> None:
        assert _coerce_page_or_window_id(42, 99) is None


# ---------------------------------------------------------------------------
# _split_content_chunks
# ---------------------------------------------------------------------------


class TestSplitContentChunks:
    def test_single_chunk_short_content(self) -> None:
        chunks, ranges = _split_content_chunks("Hello world", 100)
        assert chunks == ["Hello world"]
        assert ranges == [(0, 11)]

    def test_multiple_chunks(self) -> None:
        content = "A" * 50 + "\n\n" + "B" * 50
        chunks, ranges = _split_content_chunks(content, 50)
        assert len(chunks) >= 2

    def test_empty_content(self) -> None:
        chunks, ranges = _split_content_chunks("", 100)
        assert chunks == []
        assert ranges == []

    def test_respects_chunk_size(self) -> None:
        content = "word " * 200
        chunks, _ = _split_content_chunks(content, 50)
        for chunk in chunks:
            assert len(chunk) <= 55  # slight overshoot allowed at boundary

    def test_prefers_paragraph_boundary(self) -> None:
        content = "A" * 30 + "\n\n" + "B" * 20
        chunks, _ = _split_content_chunks(content, 40)
        assert chunks[0] == "A" * 30


# ---------------------------------------------------------------------------
# _trim_content
# ---------------------------------------------------------------------------


class TestTrimContent:
    def test_returns_short_content_unchanged(self) -> None:
        assert _trim_content("short", 100) == "short"

    def test_trims_at_sentence_boundary(self) -> None:
        content = "First sentence. Second sentence here."
        trimmed = _trim_content(content, 20)
        assert len(trimmed) <= 20
        assert trimmed.endswith(".")

    def test_trims_at_newline_boundary(self) -> None:
        content = "Line one\nLine two is longer"
        trimmed = _trim_content(content, 15)
        assert len(trimmed) <= 15

    def test_hard_trim_when_no_boundary(self) -> None:
        content = "A" * 100
        trimmed = _trim_content(content, 50)
        assert len(trimmed) == 50


# ---------------------------------------------------------------------------
# _prepare_extracted_content_response
# ---------------------------------------------------------------------------


class TestPrepareExtractedContentResponse:
    def test_empty_content_sets_unavailable(self) -> None:
        data: dict[str, Any] = {"content": "", "url": "https://example.com"}
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=True
        )
        assert result["content_unavailable"] is True
        assert result["chunk_count"] == 0
        assert result["chunks_available"] is False
        assert result["links"] == []
        assert result["cache_key"] is None

    def test_short_content_not_truncated(self) -> None:
        data: dict[str, Any] = {
            "content": "Short content",
            "url": "https://example.com",
            "title": "Test",
        }
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=False
        )
        assert result["inline_content_truncated"] is False
        assert result["content"] == "Short content"

    def test_none_content_treated_as_empty(self) -> None:
        data: dict[str, Any] = {"content": None, "url": "https://example.com"}
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=True
        )
        assert result["content_unavailable"] is True

    def test_links_suppressed_when_include_links_false(self) -> None:
        data: dict[str, Any] = {
            "content": "Some content",
            "url": "https://example.com",
            "title": "Test",
            "links": [{"url": "https://link.com", "text": "Link"}],
        }
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=False
        )
        assert result["links"] == []

    def test_chunk_size_set_to_default(self) -> None:
        data: dict[str, Any] = {"content": "text", "url": "https://example.com"}
        result = _prepare_extracted_content_response(
            conversation_id="conv-1", data=data, include_links=True
        )
        assert result["chunk_size"] == _DEFAULT_CHUNK_SIZE


# ---------------------------------------------------------------------------
# _resolve_cache_key
# ---------------------------------------------------------------------------


class TestResolveCacheKey:
    @patch("personagent.infrastructure.tools.browser_tools.content_cache._PAGE_CACHE")
    def test_delegates_to_page_cache(self, mock_cache: MagicMock) -> None:
        mock_cache.resolve_key.return_value = "resolved-key"
        result = _resolve_cache_key("conv-1", "raw-key")
        mock_cache.resolve_key.assert_called_once_with("conv-1", "raw-key")
        assert result == "resolved-key"

    @patch("personagent.infrastructure.tools.browser_tools.content_cache._PAGE_CACHE")
    def test_returns_none_for_invalid(self, mock_cache: MagicMock) -> None:
        mock_cache.resolve_key.return_value = None
        result = _resolve_cache_key("conv-1", None)
        assert result is None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_default_chunk_size(self) -> None:
        assert _DEFAULT_CHUNK_SIZE == 3_000

    def test_extract_inline_content_chars(self) -> None:
        assert _EXTRACT_INLINE_CONTENT_CHARS == 8_000

    def test_max_chunk_count(self) -> None:
        assert _MAX_CHUNK_COUNT == 6
