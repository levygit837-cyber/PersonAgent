_MAX_CONSOLE_ENTRIES_PER_PAGE = 200
_MAX_BROWSER_SCRIPT_CHARS = 10_000
_MAX_BROWSER_SCRIPT_RESULT_CHARS = 12_000
_BROWSER_SCRIPT_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}
