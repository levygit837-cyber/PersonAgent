"""Private helpers for browser tool factories.

Extracted from ``browser_tools.py`` as part of browser_tools Slice 1.
Pure functions and constants — no tool definitions.
"""

from __future__ import annotations

from personagent.infrastructure.tools.browser.building._arguments import (  # noqa: F401
    _normalize_browser_open_arguments,
    _validate_page_or_window_id,
)
from personagent.infrastructure.tools.browser.building._building import (  # noqa: F401
    _browser_height,
    _browser_width,
    _page_target_schema,
    _simple_browser_control_tool,
    _validate_browser_dimensions,
    _viewport_schema,
)
from personagent.infrastructure.tools.browser.building._errors import (  # noqa: F401
    _browser_action_permission,
    _deny,
    _error,
    _error_type,
    _target_error_result,
)
from personagent.infrastructure.tools.browser.building._response import (  # noqa: F401
    _json_result,
    _prepare_browser_control_response,
    _progress,
    _summarize_element_map,
)
from personagent.infrastructure.tools.browser.building._utils import (  # noqa: F401
    _browser_result_max_chars,
    _is_int,
)
from personagent.infrastructure.tools.browser.content_cache import (  # noqa: F401
    _DEFAULT_CHUNK_SIZE,
    _EXTRACT_INLINE_CONTENT_CHARS,
    _MAX_CHUNK_COUNT,
    _PAGE_CACHE,
    _cache_page_content,
    _cached_extracted_content_response,
    _coerce_page_or_window_id,
    _prepare_extracted_content_response,
    _resolve_cache_key,
    _run_deduped_browser_extract,
    _split_content_chunks,
    _trim_content,
)
from personagent.infrastructure.tools.browser.link_helpers import (  # noqa: F401
    _MARKDOWN_LINK_PATTERN,
    _coerce_links,
    _curate_links,
    _extract_markdown_links,
    _is_low_quality_link,
)
from personagent.infrastructure.tools.browser.workspace_target import (  # noqa: F401
    _browser_session_id,
    _browser_target,
    _browser_target_page_id,
    _browser_targeted_arguments,
    _browser_view_is_about_blank,
    _browser_workspace,
    _browser_workspace_active_tab_id,
    _browser_workspace_current_url,
    _merge_shared_browser_workspace_tabs,
    _normalize_browser_tab_for_tool,
    _resolve_browser_page_target,
    _workspace_browser_tabs,
)

_BROWSER_ACTIONS = {
    "click",
    "fill",
    "submit",
    "select",
    "press",
    "hover",
    "wait",
    "drag",
    "drop",
    "upload",
    "select_text",
    "scroll_to",
    "screenshot",
}
_BROWSER_CONTROL_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}
_BROWSER_CONSOLE_LEVELS = {"debug", "error", "info", "log", "warning", "warn"}
