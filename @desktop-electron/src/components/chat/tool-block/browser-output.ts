import type { ToolBlockUi } from "../../../types/chat";

export function browserInlineText(block: ToolBlockUi) {
  if (!isBrowserToolName(block.name)) return undefined;

  const action = browserActionLabel(block);
  if (block.status === "permission_required") return `Permission required for ${action.base}`;
  if (block.status === "error") return `Failed ${action.base}`;
  if (isRunning(block)) return action.running;
  return action.completed;
}

function browserActionLabel(block: ToolBlockUi) {
  const target = browserTargetLabel(block);
  if (block.name === "BrowserOpen") {
    return {
      base: target ? `BrowserOpen ${target}` : "BrowserOpen",
      running: target ? `Opening ${target}` : "Opening browser tab",
      completed: target ? `Opened ${target}` : "Opened browser tab",
    };
  }
  if (block.name === "BrowserExtractContent") {
    return {
      base: target ? `BrowserExtractContent ${target}` : "BrowserExtractContent",
      running: target ? `Extracting content from ${target}` : "Extracting browser content",
      completed: target ? `Extracted content from ${target}` : "Extracted browser content",
    };
  }
  if (block.name === "BrowserSearch") {
    const query = stringValue(block.data?.query);
    return {
      base: query ? `BrowserSearch ${query}` : "BrowserSearch",
      running: query ? `Searching ${query}` : "Searching the web",
      completed: query ? `Searched ${query}` : "Searched the web",
    };
  }
  if (block.name === "BrowserListTabs") {
    return { base: "BrowserListTabs", running: "Listing browser tabs", completed: "Listed browser tabs" };
  }
  if (block.name === "BrowserGetElementMap") {
    return { base: "BrowserGetElementMap", running: "Mapping browser elements", completed: "Mapped browser elements" };
  }
  if (block.name === "BrowserClick") {
    return {
      base: target ? `BrowserClick ${target}` : "BrowserClick",
      running: target ? `Clicking ${target}` : "Clicking browser page",
      completed: target ? `Clicked ${target}` : "Clicked browser page",
    };
  }
  if (block.name === "BrowserType") {
    return {
      base: target ? `BrowserType ${target}` : "BrowserType",
      running: target ? `Typing in ${target}` : "Typing in browser",
      completed: target ? `Typed in ${target}` : "Typed in browser",
    };
  }
  if (block.name === "BrowserScreenshot") {
    return {
      base: target ? `BrowserScreenshot ${target}` : "BrowserScreenshot",
      running: target ? `Capturing ${target}` : "Capturing browser screenshot",
      completed: target ? `Captured ${target}` : "Captured browser screenshot",
    };
  }
  if (block.name === "BrowserCloseTab") {
    return { base: "BrowserCloseTab", running: "Closing browser tab", completed: "Closed browser tab" };
  }
  if (block.name === "BrowserReadConsole") {
    return { base: "BrowserReadConsole", running: "Reading browser console", completed: "Read browser console" };
  }
  if (block.name === "BrowserScript") {
    return { base: "BrowserScript", running: "Running browser script", completed: "Ran browser script" };
  }
  if (block.name === "BrowserScroll") {
    return { base: "BrowserScroll", running: "Scrolling browser page", completed: "Scrolled browser page" };
  }
  if (block.name === "BrowserReload") {
    return { base: "BrowserReload", running: "Reloading browser page", completed: "Reloaded browser page" };
  }
  if (block.name === "BrowserHistory") {
    return { base: "BrowserHistory", running: "Navigating browser history", completed: "Navigated browser history" };
  }
  if (block.name === "BrowserSwitchTab") {
    return { base: "BrowserSwitchTab", running: "Switching browser tab", completed: "Switched browser tab" };
  }
  if (block.name === "BrowserWait") {
    return { base: "BrowserWait", running: "Waiting for browser page", completed: "Waited for browser page" };
  }
  if (block.name === "BrowserAct") {
    return { base: "BrowserAct", running: "Running browser action", completed: "Ran browser action" };
  }
  if (block.name === "BrowserReadContentChunk") {
    return { base: "BrowserReadContentChunk", running: "Reading browser content chunks", completed: "Read browser content chunks" };
  }
  if (block.name === "BrowserGetHtml") {
    return {
      base: target ? `BrowserGetHtml ${target}` : "BrowserGetHtml",
      running: target ? `Reading HTML from ${target}` : "Reading browser HTML",
      completed: target ? `Read HTML from ${target}` : "Read browser HTML",
    };
  }
  return { base: block.name, running: `${block.name} running`, completed: block.name };
}

function browserTargetLabel(block: ToolBlockUi) {
  return (
    stringValue(block.data?.title) ??
    stringValue(block.data?.final_url) ??
    stringValue(block.data?.url) ??
    stringValue(block.data?.page_id) ??
    stringValue(block.data?.window_id) ??
    block.path
  );
}


export function normalizedToolOutput(block: ToolBlockUi) {
  if (isBrowserToolName(block.name)) return browserOutputText(block);
  return block.content.trimEnd();
}

export function browserOutputText(block: ToolBlockUi) {
  const data = block.data ?? {};
  const error = stringValue(data.error);
  if (error) return error;

  if (block.name === "BrowserOpen") return browserOpenOutput(data);
  if (block.name === "BrowserExtractContent") return browserExtractOutput(block, data);
  if (block.name === "BrowserSearch") return browserSearchOutput(data);
  if (block.name === "BrowserListTabs") return browserTabsOutput(data);
  if (block.name === "BrowserReadContentChunk") return browserChunksOutput(block, data);
  if (block.name === "BrowserGetHtml") return browserHtmlOutput(block, data);
  if (block.name === "BrowserReadConsole") return browserConsoleOutput(data);
  if (block.name === "BrowserScript") return browserScriptOutput(data);
  if (block.name === "BrowserScreenshot") return browserScreenshotOutput(data);
  if (isBrowserControlToolName(block.name)) return browserControlOutput(data);
  return block.content.trimEnd();
}

function browserOpenOutput(data: Record<string, unknown>) {
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Final URL", stringValue(data.final_url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Window ID", stringValue(data.window_id)),
    keyValueLine("Search ID", stringValue(data.search_id)),
    keyValueLine("Opened pages", numberValue(data.opened_page_count)),
  ]);
}

function browserExtractOutput(block: ToolBlockUi, data: Record<string, unknown>) {
  const content = rawStringValue(data.content) ?? rawStringValue(data.content_preview) ?? block.content;
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Cache key", stringValue(data.cache_key)),
    keyValueLine("Content chars", numberValue(data.content_chars)),
    keyValueLine("Chunks", numberValue(data.chunk_count)),
    keyValueLine("Full output", stringValue(data.storage_ref)),
    data.inline_content_truncated === true ? "Inline content truncated: true" : undefined,
    content.trim() ? `\n${content.trimEnd()}` : stringValue(data.message),
  ]);
}

function browserSearchOutput(data: Record<string, unknown>) {
  const results = arrayValue(data.results) ?? [];
  const lines = compactOutputLines([
    keyValueLine("Query", stringValue(data.query)),
    keyValueLine("Provider", stringValue(data.provider)),
    keyValueLine("Search ID", stringValue(data.search_id)),
    keyValueLine("Results", results.length),
  ]);
  const resultLines = results
    .map((item, index) => browserSearchResultOutput(item, index))
    .filter((line) => line.length > 0);
  return compactOutputLines([lines, resultLines.length ? `\n${resultLines.join("\n\n")}` : undefined]);
}

function browserSearchResultOutput(value: unknown, index: number) {
  if (!isRecord(value)) return "";
  return compactOutputLines([
    `${index + 1}. ${stringValue(value.title) ?? stringValue(value.url) ?? "Untitled result"}`,
    stringValue(value.url) ? `   ${stringValue(value.url)}` : undefined,
    stringValue(value.snippet) ? `   ${stringValue(value.snippet)}` : undefined,
  ]);
}

function browserTabsOutput(data: Record<string, unknown>) {
  const tabs = arrayValue(data.tabs) ?? [];
  const lines = compactOutputLines([
    keyValueLine("Tab count", numberValue(data.tab_count) ?? tabs.length),
    keyValueLine("Current URL", stringValue(data.current_url)),
    keyValueLine("Last page ID", stringValue(data.last_open_page_id)),
  ]);
  const tabLines = tabs
    .map((item, index) => browserTabOutput(item, index))
    .filter((line) => line.length > 0);
  return compactOutputLines([lines, tabLines.length ? `\n${tabLines.join("\n\n")}` : undefined]);
}

function browserTabOutput(value: unknown, index: number) {
  if (!isRecord(value)) return "";
  return compactOutputLines([
    `${index + 1}. ${stringValue(value.title) ?? stringValue(value.url) ?? "Untitled tab"}`,
    stringValue(value.url) ? `   ${stringValue(value.url)}` : undefined,
    stringValue(value.page_id) ? `   page_id: ${stringValue(value.page_id)}` : undefined,
  ]);
}

function browserChunksOutput(block: ToolBlockUi, data: Record<string, unknown>) {
  const chunks = arrayValue(data.chunks) ?? [];
  const lines = compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Cache key", stringValue(data.cache_key)),
    keyValueLine("Chunks returned", numberValue(data.chunk_count) ?? chunks.length),
    keyValueLine("Total chunks", numberValue(data.total_chunks)),
  ]);
  const chunkLines = chunks
    .map((item) => browserChunkOutput(item))
    .filter((line) => line.length > 0);
  return compactOutputLines([
    lines,
    chunkLines.length ? `\n${chunkLines.join("\n\n")}` : undefined,
    !chunkLines.length ? block.content.trimEnd() : undefined,
  ]);
}

function browserChunkOutput(value: unknown) {
  if (!isRecord(value)) return "";
  const index = numberValue(value.index);
  const content = rawStringValue(value.content);
  return compactOutputLines([
    `## Chunk ${index ?? "?"}`,
    content?.trimEnd(),
  ]);
}

function browserHtmlOutput(block: ToolBlockUi, data: Record<string, unknown>) {
  const html = rawStringValue(data.html);
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("HTML chars", typeof html === "string" ? html.length : undefined),
    html ? `\n${html.trimEnd()}` : block.content.trimEnd(),
  ]);
}

function browserControlOutput(data: Record<string, unknown>) {
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Runtime", stringValue(data.runtime)),
    keyValueLine("Render mode", stringValue(data.render_mode)),
    keyValueLine("Active tab", stringValue(data.active_tab_id)),
    data.navigated === true ? "Navigated: true" : undefined,
    keyValueLine("Elements", numberValue(data.element_count)),
  ]);
}

function browserScreenshotOutput(data: Record<string, unknown>) {
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Runtime", stringValue(data.runtime)),
    keyValueLine("Render mode", stringValue(data.render_mode)),
    keyValueLine("Screenshot method", stringValue(data.screenshot_method)),
    keyValueLine("Can capture", data.can_capture === true ? "true" : data.can_capture === false ? "false" : undefined),
    keyValueLine("Viewport", browserViewportLabel(data)),
    keyValueLine("Fallback", stringValue(data.screenshot_error)),
    keyValueLine("Elements", numberValue(data.element_count)),
  ]);
}

function browserConsoleOutput(data: Record<string, unknown>) {
  const entries = arrayValue(data.entries) ?? [];
  const header = compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Entries", entries.length),
  ]);
  const entryLines = entries
    .slice(-30)
    .map((entry) => browserConsoleEntryOutput(entry))
    .filter((line) => line.length > 0);
  return compactOutputLines([header, entryLines.length ? `\n${entryLines.join("\n")}` : undefined]);
}

function browserConsoleEntryOutput(value: unknown) {
  if (!isRecord(value)) return "";
  const id = numberValue(value.id);
  const level = stringValue(value.level) ?? "log";
  const text = rawStringValue(value.text)?.trimEnd() ?? "";
  return `${id ?? "?"} [${level}] ${text}`;
}

function browserScriptOutput(data: Record<string, unknown>) {
  const resultText = rawStringValue(data.result_text);
  return compactOutputLines([
    keyValueLine("Title", stringValue(data.title)),
    keyValueLine("URL", stringValue(data.url)),
    keyValueLine("Page ID", stringValue(data.page_id)),
    keyValueLine("Mode", stringValue(data.mode)),
    keyValueLine("CDP method", stringValue(data.cdp_method)),
    data.truncated === true ? "Result truncated: true" : undefined,
    resultText ? `\n${resultText.trimEnd()}` : undefined,
  ]);
}

function browserViewportLabel(data: Record<string, unknown>) {
  const width = numberValue(data.viewport_width);
  const height = numberValue(data.viewport_height);
  return width && height ? `${width}x${height}` : undefined;
}

export function browserImageDataUrl(block: ToolBlockUi) {
  if (block.name !== "BrowserScreenshot") return undefined;
  const imageData = rawStringValue(block.data?.image_data);
  if (!imageData) return undefined;
  const mimeType = stringValue(block.data?.image_mime_type) ?? "image/png";
  return `data:${mimeType};base64,${imageData}`;
}

function keyValueLine(label: string, value: string | number | undefined) {
  if (value === undefined || value === "") return undefined;
  return `${label}: ${value}`;
}

function compactOutputLines(lines: Array<string | undefined>) {
  return lines.filter((line): line is string => Boolean(line && line.trim().length > 0)).join("\n");
}

export function shellLabel(block: ToolBlockUi) {
  const command = stringValue(block.data?.command);
  if (!command) return "Shell command";
  const base = shellCommandBase(command);
  const args = base ? command.slice(base.length).trim() : "";
  if (base === "find") return `Find ${args}`;
  if (base === "grep") return `Grep ${args}`;
  if (base === "rg") return `Search ${args}`;
  return `Shell ${command}`;
}

export function isBrowserToolName(name: string) {
  return (
    name === "BrowserSearch" ||
    name === "BrowserOpen" ||
    name === "BrowserListTabs" ||
    name === "BrowserExtractContent" ||
    name === "BrowserReadContentChunk" ||
    name === "BrowserGetHtml" ||
    name === "BrowserGetElementMap" ||
    isBrowserControlToolName(name) ||
    name === "BrowserAct"
  );
}

function isBrowserControlToolName(name: string) {
  return (
    name === "BrowserClick" ||
    name === "BrowserType" ||
    name === "BrowserScreenshot" ||
    name === "BrowserCloseTab" ||
    name === "BrowserReadConsole" ||
    name === "BrowserScript" ||
    name === "BrowserScroll" ||
    name === "BrowserReload" ||
    name === "BrowserHistory" ||
    name === "BrowserSwitchTab" ||
    name === "BrowserWait"
  );
}


function isRunning(block: ToolBlockUi) {
  return block.status === "running" || block.status === "queued";
}

function stringValue(value: unknown) {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length ? trimmed : undefined;
}

function rawStringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

function arrayValue(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function shellCommandBase(command: string) {
  return /^\s*([^\s]+)/.exec(command)?.[1];
}
