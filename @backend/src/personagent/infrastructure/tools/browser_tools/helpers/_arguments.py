"""Argument normalization and validation helpers for browser tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from personagent.domain.tools import (
    ToolArguments,
    ToolPermissionResult,
)
from personagent.infrastructure.tools.browser_tools.helpers._errors import _deny
from personagent.infrastructure.tools.browser_tools.helpers._utils import _is_int

_BROWSER_OPEN_URL_KEYS = ("url", "result_url", "final_url", "href", "link")
_BROWSER_OPEN_INDEX_KEYS = (
    "result_index",
    "index",
    "resultIndex",
    "position",
    "result_number",
    "result",
)
_BROWSER_OPEN_DIRECT_INDEX_KEYS = tuple(
    key for key in _BROWSER_OPEN_INDEX_KEYS if key != "result"
)
_BROWSER_OPEN_SEARCH_ID_KEYS = ("search_id", "searchId")


def _normalize_browser_open_arguments(arguments: ToolArguments) -> dict[str, Any]:
    """Recover common model argument variants while preserving canonical behavior."""

    url, url_key = _first_non_empty_string_with_key(arguments, _BROWSER_OPEN_URL_KEYS)
    search_id, search_id_key, invalid_search_id = _first_string_with_key(
        arguments,
        _BROWSER_OPEN_SEARCH_ID_KEYS,
    )
    raw_result_index, index_key = _first_present_with_key(
        arguments,
        _BROWSER_OPEN_DIRECT_INDEX_KEYS,
    )
    recovered_from: list[str] = []
    raw_result = arguments.get("result")

    if isinstance(raw_result, Mapping):
        if not url:
            url, url_key = _first_non_empty_string_with_key(raw_result, _BROWSER_OPEN_URL_KEYS)
        if not search_id and not invalid_search_id:
            search_id, search_id_key, invalid_search_id = _first_string_with_key(
                raw_result,
                _BROWSER_OPEN_SEARCH_ID_KEYS,
            )
        if raw_result_index is None:
            raw_result_index, index_key = _first_present_with_key(
                raw_result,
                _BROWSER_OPEN_INDEX_KEYS,
            )
    elif raw_result is not None and raw_result_index is None:
        raw_result_index = raw_result
        index_key = "result"

    if isinstance(raw_result, str) and raw_result.strip().startswith(("http://", "https://")):
        if not url:
            url = raw_result.strip()
            url_key = "result"
        if index_key == "result":
            raw_result_index = None
            index_key = ""

    result_index = int(raw_result_index) if _is_int(raw_result_index) else None
    invalid_result_index = raw_result_index is not None and result_index is None
    if url_key and url_key != "url":
        recovered_from.append(url_key)
    if index_key and index_key != "result_index":
        recovered_from.append(index_key)
    if search_id_key and search_id_key != "search_id":
        recovered_from.append(search_id_key)
    if search_id and result_index is None and not url:
        recovered_from.append("search_id_only_default_result_1")

    return {
        "url": url,
        "result_index": result_index,
        "search_id": search_id,
        "invalid_result_index": invalid_result_index,
        "invalid_search_id": invalid_search_id,
        "recovered_from": sorted(set(recovered_from)),
    }


def _first_present_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[Any | None, str]:
    for key in keys:
        if key in values:
            return values[key], key
    return None, ""


def _first_non_empty_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str]:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), key
    return None, ""


def _first_string_with_key(
    values: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, str, bool]:
    for key in keys:
        if key not in values:
            continue
        value = values[key]
        if value is None:
            continue
        if not isinstance(value, str):
            return None, key, True
        if value.strip():
            return value.strip(), key, False
    return None, "", False


def _validate_page_or_window_id(
    page_id: Any,
    window_id: Any,
    *,
    tool_name: str,
    browser_id: Any = None,
) -> ToolPermissionResult | None:
    if browser_id is not None and (not isinstance(browser_id, str) or not browser_id.strip()):
        return _deny(f"{tool_name} browser_id must be a non-empty string.")
    if page_id is not None and (not isinstance(page_id, str) or not page_id.strip()):
        return _deny(f"{tool_name} page_id must be a non-empty string.")
    if window_id is not None and (not isinstance(window_id, str) or not window_id.strip()):
        return _deny(f"{tool_name} window_id must be a non-empty string.")
    if (
        isinstance(page_id, str)
        and page_id.strip()
        and isinstance(window_id, str)
        and window_id.strip()
        and page_id.strip() != window_id.strip()
    ):
        return _deny(f"{tool_name} requires either page_id or window_id, not both.")
    return None
