"""Unit tests for browser_tools/link_helpers.py — link processing helpers."""

from __future__ import annotations

from personagent.infrastructure.tools.browser_tools.link_helpers import (
    _LINK_SUPPRESSION_THRESHOLD,
    _LOW_QUALITY_LINK_TEXT,
    _LOW_QUALITY_PATH_MARKERS,
    _MARKDOWN_LINK_PATTERN,
    _MAX_RETURNED_LINKS,
    _coerce_links,
    _curate_links,
    _extract_markdown_links,
    _is_low_quality_link,
)

# ---------------------------------------------------------------------------
# _extract_markdown_links
# ---------------------------------------------------------------------------


class TestExtractMarkdownLinks:
    def test_extracts_links_from_markdown(self) -> None:
        content = "See [Example](https://example.com) and [Docs](http://docs.test/path)"
        links = _extract_markdown_links(content)
        assert len(links) == 2
        assert links[0] == {"text": "Example", "url": "https://example.com"}
        assert links[1] == {"text": "Docs", "url": "http://docs.test/path"}

    def test_returns_empty_for_no_links(self) -> None:
        assert _extract_markdown_links("no links here") == []

    def test_returns_empty_for_empty_string(self) -> None:
        assert _extract_markdown_links("") == []

    def test_normalizes_whitespace_in_text(self) -> None:
        content = "[multi  word   text](https://example.com)"
        links = _extract_markdown_links(content)
        assert links[0]["text"] == "multi word text"

    def test_ignores_urls_with_trailing_whitespace(self) -> None:
        content = "[test](https://example.com  )"
        links = _extract_markdown_links(content)
        assert links == []

    def test_only_matches_http_urls(self) -> None:
        content = "[local](file:///tmp/test) [remote](https://example.com)"
        links = _extract_markdown_links(content)
        assert len(links) == 1
        assert links[0]["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# _coerce_links
# ---------------------------------------------------------------------------


class TestCoerceLinks:
    def test_coerces_valid_links(self) -> None:
        raw = [
            {"url": "https://a.com", "text": "A"},
            {"url": "https://b.com", "text": "B"},
        ]
        result = _coerce_links(raw)
        assert len(result) == 2
        assert result[0] == {"url": "https://a.com", "text": "A"}

    def test_deduplicates_urls(self) -> None:
        raw = [
            {"url": "https://a.com", "text": "first"},
            {"url": "https://a.com", "text": "second"},
        ]
        result = _coerce_links(raw)
        assert len(result) == 1
        assert result[0]["text"] == "first"

    def test_skips_non_http_urls(self) -> None:
        raw = [{"url": "ftp://a.com", "text": "A"}]
        assert _coerce_links(raw) == []

    def test_skips_non_dict_items(self) -> None:
        raw = [{"url": "https://a.com", "text": "A"}, "not a dict", 42]
        result = _coerce_links(raw)
        assert len(result) == 1

    def test_returns_empty_for_non_list(self) -> None:
        assert _coerce_links("not a list") == []
        assert _coerce_links(None) == []
        assert _coerce_links(42) == []

    def test_normalizes_text_whitespace(self) -> None:
        raw = [{"url": "https://a.com", "text": "  multi   space  "}]
        result = _coerce_links(raw)
        assert result[0]["text"] == "multi space"

    def test_handles_empty_url(self) -> None:
        raw = [{"url": "", "text": "A"}, {"url": "   ", "text": "B"}]
        assert _coerce_links(raw) == []

    def test_handles_missing_url_key(self) -> None:
        raw = [{"text": "A"}]
        assert _coerce_links(raw) == []


# ---------------------------------------------------------------------------
# _is_low_quality_link
# ---------------------------------------------------------------------------


class TestIsLowQualityLink:
    def test_low_quality_text(self) -> None:
        for text in ("login", "sign in", "privacy", "terms"):
            assert _is_low_quality_link(
                {"url": "https://example.com/page", "text": text},
                "https://other.com",
            ) is True

    def test_empty_text_is_low_quality(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://example.com", "text": ""},
            "https://other.com",
        ) is True

    def test_low_quality_path(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://example.com/login", "text": "Log In Page"},
            "https://other.com",
        ) is True

    def test_homepage_same_domain_is_low_quality(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://example.com/", "text": "Home Page"},
            "https://example.com/article",
        ) is True
        assert _is_low_quality_link(
            {"url": "https://example.com", "text": "Home Page"},
            "https://example.com/article",
        ) is True

    def test_short_text_no_digits_is_low_quality(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://other.com/page", "text": "xy"},
            "https://example.com",
        ) is True

    def test_short_text_with_digits_is_not_low_quality(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://other.com/page", "text": "p2"},
            "https://example.com",
        ) is False

    def test_high_quality_link(self) -> None:
        assert _is_low_quality_link(
            {"url": "https://other.com/article", "text": "Great Article"},
            "https://example.com",
        ) is False

    def test_all_low_quality_texts_covered(self) -> None:
        for text in _LOW_QUALITY_LINK_TEXT:
            assert _is_low_quality_link(
                {"url": "https://other.com/page", "text": text},
                "https://example.com",
            ) is True

    def test_all_low_quality_paths_covered(self) -> None:
        for marker in _LOW_QUALITY_PATH_MARKERS:
            url = f"https://other.com{marker}page"
            assert _is_low_quality_link(
                {"url": url, "text": "Some Good Text"},
                "https://example.com",
            ) is True


# ---------------------------------------------------------------------------
# _curate_links
# ---------------------------------------------------------------------------


class TestCurateLinks:
    def test_returns_curated_links_below_threshold(self) -> None:
        raw = [{"url": f"https://site{i}.com/article", "text": f"Article {i}"} for i in range(5)]
        links, summary = _curate_links(raw, content="text", source_url="https://other.com")
        assert len(links) == 5
        assert summary["total"] == 5
        assert summary["returned"] == 5
        assert summary["suppressed"] is False

    def test_suppresses_when_low_quality_ratio_high(self) -> None:
        low_quality = [
            {"url": f"https://site.com/login{i}", "text": "login"}
            for i in range(_LINK_SUPPRESSION_THRESHOLD)
        ]
        links, summary = _curate_links(low_quality, content="text", source_url="https://other.com")
        assert links == []
        assert summary["suppressed"] is True
        assert summary["reason"] == "link_dense_navigation_or_low_quality_links"

    def test_suppresses_when_many_markdown_links_in_content(self) -> None:
        raw = [{"url": f"https://site{i}.com/article", "text": f"Article {i}"} for i in range(_LINK_SUPPRESSION_THRESHOLD)]
        content = " ".join(f"[link{i}](https://x{i}.com)" for i in range(_LINK_SUPPRESSION_THRESHOLD))
        links, summary = _curate_links(raw, content=content, source_url="https://other.com")
        assert links == []
        assert summary["suppressed"] is True

    def test_limits_returned_links(self) -> None:
        raw = [{"url": f"https://site{i}.com/article", "text": f"Good Article {i}"} for i in range(30)]
        links, summary = _curate_links(raw, content="text", source_url="https://other.com")
        assert len(links) == _MAX_RETURNED_LINKS
        assert summary["total"] == 30
        assert summary["returned"] == _MAX_RETURNED_LINKS

    def test_summary_includes_max_returned(self) -> None:
        raw = [{"url": "https://a.com/article", "text": "Good Article"}]
        _, summary = _curate_links(raw, content="text", source_url="https://other.com")
        assert summary["max_returned"] == _MAX_RETURNED_LINKS

    def test_empty_input(self) -> None:
        links, summary = _curate_links([], content="text", source_url="https://other.com")
        assert links == []
        assert summary["total"] == 0
        assert summary["suppressed"] is False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_markdown_link_pattern_matches(self) -> None:
        match = _MARKDOWN_LINK_PATTERN.search("[test](https://example.com)")
        assert match is not None
        assert match.group(1) == "test"
        assert match.group(2) == "https://example.com"

    def test_markdown_link_pattern_no_match_non_http(self) -> None:
        match = _MARKDOWN_LINK_PATTERN.search("[test](ftp://example.com)")
        assert match is None
