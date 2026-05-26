import type { ToolBlockUi } from "../../types/chat";
import { isBrowserToolName, normalizedToolOutput } from "./tool-block/browser-output";
import { searchHasOutput } from "./tool-block/search-output";
import { todoItems, type TodoItem } from "./tool-block/todo";
import { useToolOutputCollapsed } from "./tool-block/visibility";
import { GenericToolEvent, compactGenericToolLabel } from "./tool-block/generic-tool";
import { ReadToolEvent, readCollapsedLabel, readRunningLabel } from "./tool-block/read-tool";
import { SearchToolEvent, searchCollapsedLabel, searchRunningLabel } from "./tool-block/search-tool";
import { ShellToolEvent } from "./tool-block/shell-tool";
import { TodoToolEvent, TodoToolGroupBlock } from "./tool-block/todo-tool";
import { WriteToolEvent, writeHasOutput } from "./tool-block/write-tool";
import { isRunning, isTodoTool, isFileMutationTool, isSearchTool, isSearchShellCommand } from "./tool-block/shared";
import { StatusDot } from "./tool-block/shared";
export { isBrowserToolName } from "./tool-block/browser-output";
export { todoItems, type TodoItem } from "./tool-block/todo";
export { isTodoTool, isSearchShellCommand } from "./tool-block/shared";

export function ToolBlock({ block, nested = false, forceExpanded = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  if (block.name === "Read" || block.name === "read_file") {
    return <ReadToolEvent block={block} nested={nested} />;
  }

  if (isFileMutationTool(block)) {
    return <WriteToolEvent block={block} nested={nested} forceExpanded={forceExpanded} />;
  }

  if (isTodoTool(block)) {
    return <TodoToolEvent block={block} nested={nested} />;
  }

  if (isSearchTool(block)) {
    return <SearchToolEvent block={block} nested={nested} forceExpanded={forceExpanded} />;
  }

  if (block.name === "shell") {
    return <ShellToolEvent block={block} nested={nested} forceExpanded={forceExpanded} />;
  }

  return <GenericToolEvent block={block} nested={nested} forceExpanded={forceExpanded} />;
}

export function CompactToolGroupBlock({ kind, blocks }: { kind: string; blocks: ToolBlockUi[] }) {
  const autoCollapseChildren = shouldAutoCollapseToolGroup(kind);
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse: autoCollapseChildren });
  const hasError = blocks.some((b) => b.status === "error");
  const hasRunning = blocks.some(isRunning);
  const status = hasError ? "error" : hasRunning ? "running" : "completed";
  const hasDetails = blocks.some(toolBlockHasDetails);
  const expanded = hasRunning || !collapsed;
  const showDetails = hasRunning || (hasDetails && expanded);
  const canToggle = !hasRunning && hasDetails;

  if (kind === "todo") {
    return <TodoToolGroupBlock blocks={blocks} />;
  }

  return (
    <div className="mb-1.5">
      <button
        type="button"
        className="flex w-fit items-center gap-2 rounded-lg px-1.5 py-[2px] -ml-1.5 font-mono text-[11px] transition-colors hover:bg-glass/70"
        onClick={() => canToggle && toggleCollapsed()}
      >
        <StatusDot status={status} />
        <span className={hasError ? "text-destructive" : hasRunning ? "text-muted-foreground" : "text-muted-foreground hover:text-foreground"}>
          {groupLabel(kind, blocks, collapsed)}
        </span>
      </button>
      {showDetails ? (
        <div className="ml-4 mt-2">
          {blocks.map((block) => {
            const forceChildExpanded = !autoCollapseChildren && (hasRunning || expanded);
            if (kind === "read") return <ReadToolEvent key={block.id} block={block} nested />;
            if (kind === "shell") return <ShellToolEvent key={block.id} block={block} nested forceExpanded={forceChildExpanded} />;
            if (kind === "todo") return <TodoToolEvent key={block.id} block={block} nested />;
            return <ToolBlock key={block.id} block={block} nested forceExpanded={forceChildExpanded} />;
          })}
        </div>
      ) : null}
    </div>
  );
}

function toolBlockHasDetails(block: ToolBlockUi) {
  if (isFileMutationTool(block)) return writeHasOutput(block);
  if (isTodoTool(block)) return todoItems(block).length > 0 || block.content.trim().length > 0;
  if (isSearchTool(block)) return searchHasOutput(block);
  return normalizedToolOutput(block).trim().length > 0;
}

function shouldAutoCollapseToolOutput() {
  return true;
}

function shouldAutoCollapseToolGroup(kind: string) {
  return kind !== "todo";
}

function groupLabel(kind: string, blocks: ToolBlockUi[], collapsed: boolean) {
  const count = blocks.length;
  const running = blocks.some(isRunning);
  if (kind === "read") return running ? readRunningLabel(count) : collapsed ? readCollapsedLabel(count) : `Read ${count} ${count === 1 ? "File" : "Files"} Hide`;
  if (kind === "shell") return running ? `Running ${count} ${count === 1 ? "command" : "commands"}...` : withGroupToggle(`Ran ${count} ${count === 1 ? "command" : "commands"}`, collapsed);
  if (kind === "search") return running ? searchRunningLabel() : collapsed ? searchCollapsedLabel(count) : `Search ${count} ${count === 1 ? "time" : "times"} Hide`;
  if (kind === "web") return running ? `Fetching ${count} URLs...` : withGroupToggle(`Fetched ${count} URLs`, collapsed);
  if (kind === "browser_open") return running ? `Opening ${count} ${count === 1 ? "Tab" : "Tabs"}...` : withGroupToggle(`Opened ${count} ${count === 1 ? "Tab" : "Tabs"}`, collapsed);
  if (kind === "browser_extract") return running ? `Extracting content from ${count} URLs...` : withGroupToggle(`Extracted content from ${count} URLs`, collapsed);
  if (kind === "browser_search") return running ? `Searching ${count} web ${count === 1 ? "query" : "queries"}...` : withGroupToggle(`Searched ${count} web ${count === 1 ? "query" : "queries"}`, collapsed);
  if (kind === "browser_tabs") return running ? "Listing browser tabs..." : withGroupToggle(`Listed ${count} browser tab ${count === 1 ? "snapshot" : "snapshots"}`, collapsed);
  if (kind === "browser_chunks") return running ? `Reading ${count} content ${count === 1 ? "chunk" : "chunks"}...` : withGroupToggle(`Read ${count} content ${count === 1 ? "chunk" : "chunks"}`, collapsed);
  if (kind === "browser_html") return running ? `Reading HTML from ${count} URLs...` : withGroupToggle(`Read HTML from ${count} URLs`, collapsed);
  if (kind === "write") return running ? `Writing ${count} ${count === 1 ? "File" : "Files"}...` : withGroupToggle(`Wrote ${count} ${count === 1 ? "File" : "Files"}`, collapsed);
  if (kind === "task") return running ? `Updating ${count} tasks...` : withGroupToggle(`Updated ${count} tasks`, collapsed);
  if (kind === "todo") return `Updated ${count} todo ${count === 1 ? "list" : "lists"}`;
  if (kind === "lsp") return running ? `Running ${count} LSP queries...` : withGroupToggle(`Ran ${count} LSP queries`, collapsed);
  if (kind.startsWith("tool:")) {
    const label = compactGenericToolLabel(kind.slice("tool:".length));
    return running ? `Running ${count} ${label} ${count === 1 ? "call" : "calls"}...` : withGroupToggle(`Ran ${count} ${label} ${count === 1 ? "call" : "calls"}`, collapsed);
  }
  return running ? `Running ${count} tool calls...` : withGroupToggle(`${count} tool calls`, collapsed);
}

function withGroupToggle(label: string, collapsed: boolean) {
  return `${label} ${collapsed ? ">" : "Hide"}`;
}
