# Browser Workspace

## V1 Contract

The Session Panel Browser is a Browser Workspace, not a universal pixel-perfect browser.
It keeps LightPanda as the real runtime, renders the captured page DOM in Electron, preserves
the original page CSS when possible, and overlays PersonAgent controls for inspection,
annotations, actions, and timeline feedback.

V1 stores only lightweight workspace state in `Conversation.metadata["browser_workspace"]`:
annotations, the latest compact element map, active browser id, current URL/title, and a capped
timeline. Full HTML snapshots are runtime data and must not be persisted into conversation
metadata.

## Model-Facing Control Surface

The browser stack keeps `LightPandaBrowserWorker`, `create_browser_tools`, logical
`page_id`/`window_id` aliases, `BROWSER_CDP_URL`, and the existing
search/open/extract/html/chunk/element-map tools. Browser autonomy is exposed through
explicit tools first:

- `BrowserClick`: click by `node_id` from `BrowserGetElementMap`, or by viewport `x/y`.
- `BrowserType`: `type`, `fill`, or `press`, optionally targeting a `node_id`.
- `BrowserScreenshot`: pixel screenshot through Chrome/Chromium CDP when available.
- `BrowserCloseTab`: close one logical page and clear its page, element, and console caches.
- `BrowserReadConsole`: read a bounded per-page console buffer.
- `BrowserScript`: advanced allowlisted page JS/CDP execution.
- `BrowserScroll`, `BrowserReload`, `BrowserHistory`, `BrowserSwitchTab`, `BrowserWait`: direct page-control tools.

`BrowserAct` remains available for advanced compatibility actions such as hover,
drag/drop, upload, select text, submit/select, and mapped fallback actions. Prompts should
prefer the explicit tools for predictable GPT OSS behavior.

All page-targeted tools accept `page_id` or `window_id`. If neither is provided, the
worker resolves the current page, then the last opened page. If both are provided and
different, validation fails. Visual tools default to `1024x720`; tools that mutate page
state are not concurrency-safe.

Common result fields include `type`, `page_id`, `window_id`, `url`, `title`, `runtime`,
`render_mode`, `active_tab_id`, `navigated`, and bounded `elements` when useful.

## Runtime Notes

LightPanda does not expose a graphical compositor, so `BrowserScreenshot` returns
`can_capture=false` with a controlled DOM-mirror fallback when running on LightPanda only.
When the worker is connected to Chrome/Chromium CDP, screenshots return `image_data` plus
`image_mime_type`; Electron renders this as an image preview instead of dumping base64 as
the primary text.

Console capture is attached when pages are opened or resolved. The worker stores a bounded
ring buffer per conversation/page for `console.*` and page errors. `BrowserReadConsole`
supports `levels`, `since_id`, `limit`, and `clear`; closing a tab or session removes its
console entries.

`BrowserScript` is intentionally restricted. `mode=evaluate` runs bounded JavaScript in the
page with script length, timeout, and result-size caps. `mode=cdp` allows only:
`Runtime.evaluate`, `Performance.getMetrics`, `DOM.getDocument`, `DOM.querySelector`,
`DOM.getOuterHTML`, `Page.captureScreenshot`, `Log.enable`, and `Log.clear`.

Production web safety still blocks private hosts by default. Integration tests can opt in
with `web_allow_private_hosts=True` and empty `web_blocked_domains` for local fixture pages.

## V2 Backlog

- Visual automation recorder with editable replay steps.
- Rich timeline with snapshot diffs, screenshots when Chrome CDP is active, and step-by-step replay.
- Reusable browser workflows scoped by workspace.
- Deeper iframe, Shadow DOM, SPA, authenticated-session, and multi-tab synchronization support.
- Stronger Chrome/Chromium CDP path for pixel-perfect rendering when LightPanda cannot provide enough visual fidelity.
