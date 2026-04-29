"""Rich tool prompt sections inspired by PersonAgent tool guidance."""

from __future__ import annotations

from personagent.domain.prompts.models import SystemPromptSection
from personagent.domain.tools import ToolDefinition


def get_rich_tool_prompt_sections(
    tool_definitions: list[ToolDefinition] | None = None,
    tool_names: list[str] | None = None,
) -> tuple[SystemPromptSection, ...]:
    """Return a single cacheable section with per-tool usage prompts."""

    names = list(tool_names or [])
    definitions_by_name: dict[str, ToolDefinition] = {}
    for definition in tool_definitions or []:
        definitions_by_name[definition.name] = definition
        if definition.name not in names:
            names.append(definition.name)
    selected = [name for name in names if name in TOOL_PROMPTS or name in definitions_by_name]
    if not selected:
        return ()

    def render() -> str:
        blocks = ["# Tool Prompts", "", "Use these tool-specific contracts when deciding what to call and how to interpret results."]
        for name in selected:
            definition = definitions_by_name.get(name)
            blocks.append(_render_tool_prompt(name, definition))
        return "\n\n".join(blocks)

    cache_break = any(
        not definition.cacheable_prompt for definition in definitions_by_name.values()
    )
    return (SystemPromptSection("tool_prompts", render, cache_break=cache_break),)


def _render_tool_prompt(name: str, definition: ToolDefinition | None) -> str:
    custom = definition.usage_prompt if definition else None
    when_to_use = definition.when_to_use if definition else ()
    when_not_to_use = definition.when_not_to_use if definition else ()
    examples = definition.examples if definition else ()
    base = custom or TOOL_PROMPTS.get(name) or f"Use {name} according to its schema and returned data."
    lines = [f"## {name}", base.strip()]
    if definition and definition.should_defer and not definition.always_load:
        lines.append(
            "This tool may be deferred from the initial callable schema. Use ToolSearch with "
            f"`select:{definition.name}` or an allowed-tool expansion before assuming it can be called directly."
        )
    if when_to_use:
        lines.append("Use when:")
        lines.extend(f"- {item}" for item in when_to_use)
    if when_not_to_use:
        lines.append("Do not use when:")
        lines.extend(f"- {item}" for item in when_not_to_use)
    if examples:
        lines.append("Examples:")
        lines.extend(f"- {item}" for item in examples)
    return "\n".join(lines)


TOOL_PROMPTS: dict[str, str] = {
    "Read": (
        "Read file contents before editing or making claims about implementation. "
        "Use absolute paths or paths resolved against the workspace. For large files, "
        "read focused ranges and continue reading adjacent ranges until the relevant logic is complete."
    ),
    "Write": (
        "Create new files or replace an entire file only when that is the intended operation. "
        "Before overwriting an existing file, read it first and preserve unrelated content. "
        "Prefer Edit for targeted modifications."
    ),
    "Edit": (
        "Modify existing files with exact old_string matches. Read the target file first, keep "
        "edits narrow, and avoid broad formatting churn unless formatting is the task."
    ),
    "Glob": (
        "Discover files by pattern before deep analysis. Use it to map directories, locate source "
        "families, and verify whether expected files exist."
    ),
    "Grep": (
        "Search symbols, strings, routes, DTOs, and tests with focused patterns. Prefer Grep or rg "
        "before reading many files manually."
    ),
    "shell": (
        "Use shell for repository inspection, focused test commands, and operations not covered by "
        "dedicated tools. Prefer rg/find/git commands for exploration. Avoid destructive commands "
        "unless the user explicitly requested them and permissions allow it."
    ),
    "AskUserQuestion": (
        "Use AskUserQuestion only when a concrete user decision blocks progress. Ask short "
        "questions with clear options where possible, then wait for the answer event before continuing."
    ),
    "SendUserMessage": (
        "Use SendUserMessage only as a visible checkpoint during long-running work. Do not use it "
        "as a replacement for the normal assistant response."
    ),
    "Config": (
        "Use Config to read or update allowlisted runtime settings. Reads are automatic; set "
        "operations require approval and should be limited to user-requested policy changes."
    ),
    "EnterWorktree": (
        "Use EnterWorktree when isolated edits are useful. Subsequent workspace-relative tool "
        "paths resolve inside the active worktree until ExitWorktree is called."
    ),
    "ExitWorktree": (
        "Use ExitWorktree when done with an active worktree. Keep preserves it; remove requires "
        "approval and refuses dirty worktrees unless discard_changes=true is explicit."
    ),
    "Agent": (
        "Use Agent for bounded background or delegated work that needs a durable id/name. "
        "AgentTool is an alias, but Agent is the preferred PersonAgent-style name."
    ),
    "SendMessage": (
        "Use SendMessage to communicate with an existing Agent/Task id. It is not the user-facing "
        "response channel."
    ),
    "ListMcpResourcesTool": "List resources from configured MCP servers before reading one.",
    "ReadMcpResourceTool": "Read a known MCP resource by server and URI.",
    "McpAuth": "Use McpAuth or mcp__server__authenticate when an MCP server needs authentication.",
    "WebFetch": (
        "Fetch a specific URL when the user provided it or when a source URL is already known. "
        "Use browser tools for broader navigation and page affordances."
    ),
    "WebSearch": (
        "Use web search for simple search-result discovery when BrowserSearch is unavailable. "
        "Open and inspect sources before making factual claims."
    ),
    "BrowserSearch": (
        "Run multiple targeted queries for research. Search results are leads, not evidence; open "
        "relevant sources before synthesizing. For multi-source research, issue independent "
        "BrowserSearch calls in the same tool turn when possible, then continue with BrowserOpen "
        "instead of merely saying you will open sources."
    ),
    "BrowserOpen": (
        "Open a known URL or a result from BrowserSearch. Keep the returned page_id/window_id when "
        "comparing multiple sources, and verify the final URL before extracting content. If you "
        "have only a search_id, BrowserOpen can use it by itself to open that search's first result."
    ),
    "BrowserListTabs": (
        "List opened browser pages/tabs in the current conversation. The user's Browser panel and "
        "these browser tools share the same browser workspace, so use this to recover panel tab "
        "page_id/window_id values and avoid extracting or acting on the wrong source."
    ),
    "BrowserExtractContent": (
        "Extract structured readable content from a URL, page_id/window_id, or the last BrowserOpen "
        "page. It prepares the rendered page before reading, so prefer page_id/window_id after "
        "BrowserOpen. If content_chars is larger than the returned preview, continue with "
        "BrowserReadContentChunk before synthesizing. Use include_links when links may reveal "
        "deeper documentation, changelogs, pricing, downloads, or examples."
    ),
    "BrowserReadContentChunk": (
        "Read cached page chunks after BrowserExtractContent. Use chunk_count to read multiple "
        "consecutive chunks when needed. Chunks are bounded by chunk_size/content_chars metadata; "
        "links are intentionally omitted unless include_links is needed and the backend did not "
        "suppress them as navigation noise."
    ),
    "BrowserGetHtml": (
        "Use raw HTML only when rendered text is insufficient, such as hidden metadata, script data, "
        "or page controls not present in extracted content."
    ),
    "BrowserGetElementMap": (
        "Inspect the current browser page's mapped UI elements before interacting visually. Use "
        "returned node_id values with BrowserClick or BrowserType. Use BrowserAct only for advanced "
        "compatibility actions not covered by explicit browser tools."
    ),
    "BrowserClick": (
        "Click by node_id from BrowserGetElementMap when possible; use x/y only when no mapped element "
        "exists. After a click that may navigate or change UI state, inspect the returned elements or "
        "call BrowserWait/BrowserGetElementMap before continuing."
    ),
    "BrowserType": (
        "Use mode=fill for inputs with a node_id, mode=type for focused incremental text, and mode=press "
        "for keys such as Enter or Escape. Prefer BrowserType over BrowserAct for text entry."
    ),
    "BrowserScreenshot": (
        "Capture visual state. Chrome/Chromium CDP can return image_data; LightPanda may return a "
        "DOM-mirror fallback with can_capture=false. Do not rely on screenshots for text extraction "
        "when BrowserExtractContent or BrowserGetElementMap is available."
    ),
    "BrowserCloseTab": (
        "Close browser pages that are no longer needed. Keep page_id/window_id from BrowserOpen or "
        "BrowserListTabs and expect the updated tab list in the result."
    ),
    "BrowserReadConsole": (
        "Read captured console logs and page errors after actions or scripts. Use since_id for polling "
        "and clear=true only when those entries are no longer needed."
    ),
    "BrowserScript": (
        "Use only for advanced inspection that explicit browser tools cannot handle. evaluate runs "
        "bounded JavaScript in the page; cdp mode is limited to the allowlisted Runtime, Performance, "
        "DOM, Page.captureScreenshot, and Log methods. Never use it as a first choice for clicking, "
        "typing, scrolling, waiting, reloading, tab switching, or screenshots."
    ),
    "BrowserScroll": (
        "Scroll the selected page when content or controls are below the viewport, then inspect the "
        "returned elements or use BrowserGetElementMap."
    ),
    "BrowserReload": "Reload the selected page when current state may be stale.",
    "BrowserHistory": "Move the selected page back or forward in browser history.",
    "BrowserSwitchTab": (
        "Activate a page_id/window_id returned by BrowserOpen or BrowserListTabs before acting on that tab."
    ),
    "BrowserWait": (
        "Wait for a short time or a load state after click/type/reload/history actions before inspecting "
        "the page again."
    ),
    "BrowserAct": (
        "Advanced compatibility tool for mapped browser actions. Prefer BrowserClick, BrowserType, "
        "BrowserScroll, BrowserWait, BrowserScreenshot, and tab tools first. Use BrowserAct for hover, "
        "drag/drop, upload, select_text, scroll_to, submit/select, or other mapped actions not exposed "
        "as explicit tools, then inspect the updated page before continuing."
    ),
    "TodoWrite": (
        "Use TodoWrite for non-trivial writing, exploration, debugging, research, and validation. "
        "Create concrete todos, keep exactly one item in progress, mark items complete as soon "
        "as they are done, and revise the list when facts or scope change."
    ),
    "Task": (
        "Use Task for autonomous subtasks when available and appropriate. Give bounded instructions, "
        "clear ownership, and expected output."
    ),
    "TaskCreate": (
        "Create background tasks only for work that can run independently. Include a concise title, "
        "clear prompt, and expected result."
    ),
    "TaskGet": "Inspect a known task's status or result before deciding whether to continue waiting.",
    "TaskUpdate": "Update task metadata or status when the task store is the source of truth.",
    "TaskList": "List tasks to recover context or coordinate existing background work.",
    "TaskOutput": "Read task output when the result is needed for the current turn.",
    "TaskStop": "Stop a task when it is no longer needed, unsafe, or superseded.",
    "ToolSearch": (
        "Discover deferred or unfamiliar tools by capability, group, or select:<tool_name>. Use it "
        "before assuming a capability is unavailable."
    ),
    "Skill": (
        "Load a SKILL.md only when the task matches that skill. Treat the returned body as procedural "
        "guidance and follow referenced resources progressively."
    ),
    "StructuredOutput": (
        "Use when a strict JSON schema must be satisfied. Validate the final value against the schema "
        "instead of relying on prose promises."
    ),
    "LSP": (
        "Use language-server information for definitions, references, diagnostics, or symbol-aware "
        "navigation when text search alone is insufficient."
    ),
    "EnterPlanMode": (
        "Use EnterPlanMode only when the user explicitly asks for a plan, a planning-only response, "
        "or an approval-gated plan. Do not use it for ordinary implementation, web research, short "
        "tasks, or because a task has multiple steps; proceed with tools directly."
    ),
    "ExitPlanMode": (
        "Use ExitPlanMode only after EnterPlanMode is already active and the requested plan is ready "
        "for approval. Do not use it as a generic approval request for normal tool use."
    ),
}
