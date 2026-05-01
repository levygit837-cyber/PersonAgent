import { useMemo } from "react";
import type { ToolBlockStatus, ToolBlockUi } from "../../types/chat";
import { browserImageDataUrl, browserInlineText, isBrowserToolName, normalizedToolOutput, shellLabel } from "./tool-block/browser-output";
import { searchHasOutput, searchMetadata, searchOutputPreview, searchOutputRows, searchOutputText, searchSummary, type SearchOutputRow } from "./tool-block/search-output";
import { todoItems, type TodoItem } from "./tool-block/todo";
import { useToolOutputCollapsed } from "./tool-block/visibility";
export { isBrowserToolName } from "./tool-block/browser-output";
export { todoItems, type TodoItem } from "./tool-block/todo";

const TOOL_STATUS_DOT_SIZE = 6;
const AUTO_COLLAPSE_TOOL_OUTPUTS = true;

type WriteOutputRow = {
  kind: "add" | "remove" | "context" | "meta" | "error";
  marker: string;
  text: string;
  oldLine?: number;
  newLine?: number;
};

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
  const status: ToolBlockStatus = hasError ? "error" : hasRunning ? "running" : "completed";
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

function ReadToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  return (
    <div className={nested ? "mb-1 flex items-center gap-2" : "mb-1.5 flex items-center gap-2"}>
      <StatusDot status={block.status} />
      <span className={`min-w-0 truncate font-mono text-xs ${statusTextClass(block.status)}`}>
        {readEventText(block)}
      </span>
    </div>
  );
}

function TodoToolGroupBlock({ blocks }: { blocks: ToolBlockUi[] }) {
  return <TodoPanel blocks={blocks} />;
}

function TodoToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  return <TodoPanel blocks={[block]} nested={nested} />;
}

function TodoPanel({ blocks, nested = false }: { blocks: ToolBlockUi[]; nested?: boolean }) {
  const latest = latestTodoBlock(blocks);
  const todos = todoItems(latest);
  const completed = todos.filter((todo) => todo.status === "completed").length;
  const active = todos.find((todo) => todo.status === "in_progress");
  const status = todoPanelStatus(blocks);
  const updateCount = blocks.length;

  if (todos.length === 0) {
    return <GenericToolEvent block={latest} nested={nested} />;
  }

  return (
    <section
      className={
        nested
          ? "personagent-todo-rise mb-2 overflow-hidden rounded-lg border border-glass-border/35 bg-card/45 shadow-soft"
          : "personagent-todo-rise mb-3 overflow-hidden rounded-lg border border-glass-border/40 bg-card/55 shadow-soft"
      }
      aria-label="Todo tracker"
      data-testid="todo-tracker"
    >
      <div className="flex min-w-0 items-center justify-between gap-3 border-b border-glass-border/25 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <StatusDot status={status} />
          <div className="min-w-0">
            <div className="truncate font-mono text-[11px] font-semibold uppercase text-foreground">Todos</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground">
              {latest.name}
              {updateCount > 1 ? ` - ${updateCount} updates` : ""}
            </div>
          </div>
        </div>
        <div className="shrink-0 rounded-full border border-glass-border/35 bg-background/45 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
          {todoProgressLabel(status, completed, todos.length)}
        </div>
      </div>
      <ul className="max-h-56 overflow-y-auto py-1">
        {todos.map((todo, index) => (
          <TodoRow key={todo.id || `${todo.content}-${index}`} todo={todo} index={index} active={active?.id === todo.id} />
        ))}
      </ul>
    </section>
  );
}

function TodoRow({ todo, index, active }: { todo: TodoItem; index: number; active: boolean }) {
  const completed = todo.status === "completed";
  return (
    <li
      className="personagent-todo-item grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 border-b border-glass-border/20 px-3 py-1.5 last:border-0"
      style={{ animationDelay: `${Math.min(index * 24, 144)}ms` }}
    >
      <span className="pt-[7px]">
        <TodoStatusDot status={todo.status} />
      </span>
      <span
        className={
          completed
            ? "min-w-0 break-words text-[12px] leading-5 text-muted-foreground/70 line-through decoration-success/50"
            : "min-w-0 break-words text-[12px] leading-5 text-foreground/90"
        }
      >
        {todo.content}
      </span>
      {active ? (
        <span className="mt-0.5 rounded-full border border-warning/25 px-1.5 py-[1px] font-mono text-[10px] text-warning">active</span>
      ) : null}
    </li>
  );
}

function TodoStatusDot({ status }: { status: TodoItem["status"] }) {
  const completed = status === "completed";
  return (
    <span
      className={`personagent-todo-dot inline-flex h-2.5 w-2.5 shrink-0 rounded-full ${completed ? "bg-success" : "bg-warning"}`}
      data-status={status}
      aria-label={todoStatusLabel(status)}
    />
  );
}

function SearchToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse: true });
  const outputCollapsed = collapsed;
  const rows = useMemo(() => (outputCollapsed ? [] : searchOutputRows(block)), [block, outputCollapsed]);
  const hasOutput = searchHasOutput(block);
  const summary = searchSummary(block);
  const preview = searchOutputPreview(block);
  const canToggle = hasOutput;
  const eventText = searchEventText(block, summary);

  return (
    <div className={nested ? "mb-1.5" : "mb-2"}>
      <div className="flex min-w-0 items-start gap-2">
        <span className="pt-1">
          <StatusDot status={block.status} />
        </span>
        <button
          type="button"
          disabled={!canToggle}
          className="min-w-0 flex-1 text-left disabled:cursor-default"
          aria-label={canToggle ? `${outputCollapsed ? "Show" : "Hide"} search output` : undefined}
          onClick={() => canToggle && toggleCollapsed()}
        >
          <div className={`truncate font-mono text-xs ${statusTextClass(block.status)}`}>
            {eventText}
          </div>
          {preview ? <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{preview}</div> : null}
        </button>
      </div>
      {hasOutput && !outputCollapsed ? <SearchOutputPanel block={block} rows={rows} /> : null}
    </div>
  );
}

function WriteToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse: true });
  const outputCollapsed = collapsed;
  const rows = useMemo(() => (outputCollapsed ? [] : writeOutputRows(block)), [block, outputCollapsed]);
  const hasOutput = writeHasOutput(block);
  const stats = writeLineStats(block);
  const canToggle = hasOutput;
  const showStats = !isRunning(block) && !isError(block) && (stats.added > 0 || stats.removed > 0);

  return (
    <div className={nested ? "mb-1" : "mb-1.5"}>
      <button
        type="button"
        disabled={!canToggle}
        className="flex w-full min-w-0 flex-wrap items-center gap-2 text-left font-mono text-xs disabled:cursor-default"
        onClick={() => canToggle && toggleCollapsed()}
      >
        <StatusDot status={block.status} />
        <span className={isError(block) ? "text-destructive" : "text-muted-foreground"}>{writeEventText(block)}</span>
        {showStats ? (
          <span className="flex items-center gap-1">
            {stats.added > 0 ? <span className="font-medium text-success">+{stats.added}</span> : null}
            {stats.removed > 0 ? <span className="font-medium text-destructive">-{stats.removed}</span> : null}
          </span>
        ) : null}
        {canToggle ? (
          <>
            <span className="text-muted-foreground/70">-</span>
            <span className="text-primary">{outputCollapsed ? "Show" : "Hide"}</span>
          </>
        ) : null}
      </button>
      {hasOutput && !outputCollapsed ? <WriteOutputPanel block={block} rows={rows} /> : null}
    </div>
  );
}

function ShellToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse: true });
  const outputCollapsed = collapsed;
  const output = block.content.trimEnd();
  const hasOutput = output.trim().length > 0;
  const canToggle = hasOutput;
  return (
    <div className={nested ? "mb-1.5" : "mb-2"}>
      <div className="flex items-start gap-2">
        <span className="pt-1">
          <StatusDot status={block.status} />
        </span>
        <button
          type="button"
          disabled={!canToggle}
          className="min-w-0 flex-1 text-left disabled:cursor-default"
          aria-label={canToggle ? `${outputCollapsed ? "Show" : "Hide"} shell output` : undefined}
          onClick={() => canToggle && toggleCollapsed()}
        >
          <div className={isError(block) ? "truncate font-mono text-xs text-destructive" : "truncate font-mono text-xs text-muted-foreground"}>
            {shellCommandText(block)}
          </div>
          {shellOutputPreview(output) ? (
            <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{shellOutputPreview(output)}</div>
          ) : null}
        </button>
      </div>
      {hasOutput && !outputCollapsed ? (
        <div className="ml-4 mt-2 overflow-hidden rounded-xl border border-glass-border/35 bg-card/80 shadow-soft">
          <ArtifactNotice block={block} />
          <pre className="max-h-72 overflow-auto p-3 font-mono text-[11px] leading-5 text-muted-foreground">
            {output}
          </pre>
        </div>
      ) : null}
    </div>
  );
}


function WriteOutputPanel({ block, rows }: { block: ToolBlockUi; rows: WriteOutputRow[] }) {
  const stats = writeLineStats(block);
  return (
    <div
      className="ml-4 mt-2 max-h-80 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 shadow-soft"
      data-testid="file-mutation-preview"
    >
      <div className="sticky top-0 z-10 flex min-w-0 items-center justify-between gap-3 border-b border-glass-border/35 bg-card/95 px-3 py-2 font-mono text-[11px] backdrop-blur">
        <span className="min-w-0 truncate text-foreground">{writePreviewTitle(block)}</span>
        <span className="shrink-0 text-muted-foreground">
          {stats.added > 0 ? `+${stats.added}` : "+0"} / {stats.removed > 0 ? `-${stats.removed}` : "-0"}
        </span>
      </div>
      <div className="font-mono text-[11px] leading-5">
        {rows.map((row, index) => (
          <WriteOutputLine key={`${row.kind}-${index}-${row.text}`} row={row} />
        ))}
      </div>
    </div>
  );
}

function WriteOutputLine({ row }: { row: WriteOutputRow }) {
  const className =
    row.kind === "add"
      ? "bg-success/10 text-success"
      : row.kind === "remove"
        ? "bg-destructive/10 text-destructive"
        : row.kind === "meta"
          ? "bg-secondary/[0.35] text-muted-foreground/70"
          : row.kind === "error"
            ? "text-destructive"
            : "text-muted-foreground";

  const lineNumber = row.newLine ?? row.oldLine;

  return (
    <div className={`grid grid-cols-[3.75rem_1.25rem_minmax(0,1fr)] border-b border-glass-border/25 py-0.5 last:border-0 ${className}`}>
      <span className="select-none pr-3 text-right text-muted-foreground/65">{lineNumber ?? ""}</span>
      <span className="select-none text-center opacity-80">{row.marker}</span>
      <span className="whitespace-pre-wrap break-words pr-3">{row.text.length > 0 ? row.text : " "}</span>
    </div>
  );
}

function GenericToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
  const autoCollapse = shouldAutoCollapseToolOutput();
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true, { autoCollapse });
  const output = normalizedToolOutput(block);
  const browserImage = browserImageDataUrl(block);
  const outputCollapsed = collapsed;
  const hasDetails = output.trim().length > 0 || Boolean(browserImage);
  const error = isError(block);
  const canToggle = hasDetails;

  return (
    <div className={nested ? "mb-1" : "mb-1.5"}>
      <button
        type="button"
        disabled={!canToggle}
        onClick={() => canToggle && toggleCollapsed()}
        className="flex w-full items-center gap-2 text-left font-mono text-xs disabled:cursor-default"
      >
        <StatusDot status={block.status} />
        <span className={error ? "min-w-0 flex-1 truncate text-destructive" : "min-w-0 flex-1 truncate text-muted-foreground"}>
          {inlineToolText(block)}
          {canToggle ? ` - ${outputCollapsed ? "Show" : "Hide"}` : ""}
        </span>
      </button>
      {hasDetails && !outputCollapsed ? (
        <div className="ml-4 mt-2 overflow-hidden rounded-xl border border-glass-border/35 bg-card/80 shadow-soft">
          {browserImage ? (
            <img
              src={browserImage}
              alt="Browser screenshot"
              className="max-h-80 w-full object-contain bg-background/60"
            />
          ) : null}
          <ArtifactNotice block={block} />
          {output.trim() ? (
            <pre className={browserImage ? "max-h-72 overflow-auto border-t border-glass-border/35 p-3 font-mono text-[11px] leading-5 text-muted-foreground" : "max-h-72 overflow-auto p-3 font-mono text-[11px] leading-5 text-muted-foreground"}>
              {output}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SearchOutputPanel({ block, rows }: { block: ToolBlockUi; rows: SearchOutputRow[] }) {
  const metadata = searchMetadata(block);
  const fallback = searchOutputText(block);

  return (
    <div className="ml-4 mt-2 rounded-xl border border-glass-border/35 bg-card/80 p-3 shadow-soft">
      {metadata.length > 0 ? (
        <dl className="grid gap-x-4 gap-y-1 font-mono text-[11px] sm:grid-cols-2">
          {metadata.map((item) => (
            <div key={item.label} className="min-w-0">
              <dt className="text-muted-foreground/60">{item.label}</dt>
              <dd className="truncate text-muted-foreground">{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <ArtifactNotice block={block} />
      {rows.length > 0 ? (
        <div className={metadata.length > 0 ? "mt-3 max-h-72 overflow-auto font-mono text-[11px] leading-5" : "max-h-72 overflow-auto font-mono text-[11px] leading-5"}>
          {rows.map((row, index) => (
            <SearchOutputLine key={`${row.kind}-${index}-${row.text}`} row={row} />
          ))}
        </div>
      ) : fallback.trim() ? (
        <pre className={metadata.length > 0 ? "mt-3 max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-5 text-muted-foreground" : "max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-5 text-muted-foreground"}>
          {fallback.trimEnd()}
        </pre>
      ) : (
        <div className={metadata.length > 0 ? "mt-3 font-mono text-[11px] text-muted-foreground" : "font-mono text-[11px] text-muted-foreground"}>
          No output returned.
        </div>
      )}
    </div>
  );
}

function ArtifactNotice({ block }: { block: ToolBlockUi }) {
  const storageRef = stringValue(block.data?.storage_ref);
  if (!storageRef) return null;
  const originalChars = numberValue(block.data?.original_chars);
  return (
    <div className="border-b border-glass-border/35 bg-secondary/[0.25] px-3 py-2 font-mono text-[11px] leading-5 text-muted-foreground">
      Full output saved: <span className="break-all text-foreground/80">{storageRef}</span>
      {originalChars ? <span className="text-muted-foreground/70"> ({originalChars} chars)</span> : null}
    </div>
  );
}

function SearchOutputLine({ row }: { row: SearchOutputRow }) {
  if (row.kind === "match") {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,2fr)] gap-2 border-b border-glass-border/25 py-1 last:border-0">
        <span className="truncate text-muted-foreground">{row.file}</span>
        <span className="text-muted-foreground/60">{row.line}</span>
        <span className="truncate text-foreground/80">{row.text}</span>
      </div>
    );
  }

  if (row.kind === "file") {
    return (
      <div className="border-b border-glass-border/25 py-1 last:border-0">
        <span className="truncate text-muted-foreground">{row.text}</span>
      </div>
    );
  }

  return (
    <div className="border-b border-glass-border/25 py-1 last:border-0">
      <span className="whitespace-pre-wrap text-muted-foreground">{row.text}</span>
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
  return AUTO_COLLAPSE_TOOL_OUTPUTS;
}

function shouldAutoCollapseToolGroup(kind: string) {
  return kind !== "todo";
}

function StatusDot({ status, size = TOOL_STATUS_DOT_SIZE }: { status: ToolBlockStatus; size?: number }) {
  const running = status === "running" || status === "queued";
  const color = statusDotClass(status);
  return running ? (
    <span
      className="personagent-spinner personagent-tool-status-dot inline-block shrink-0 text-muted-foreground"
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  ) : (
    <span
      className={`personagent-tool-status-dot inline-flex shrink-0 rounded-full ${color}`}
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

export function readRunningLabel(count: number) {
  return `Reading ${count} ${count === 1 ? "File" : "Files"}...`;
}

export function readCollapsedLabel(count: number) {
  return `Read ${count} ${count === 1 ? "File" : "Files"} >`;
}

export function searchRunningLabel() {
  return "Searching...";
}

export function searchCollapsedLabel(count: number) {
  return `Search ${count} ${count === 1 ? "time" : "times"} >`;
}

function readEventText(block: ToolBlockUi) {
  const file = fileLabel(block);
  if (block.status === "permission_required") return `Permission required for Read ${file}`;
  if (block.status === "error") return `Failed Read ${file}`;
  if (isRunning(block)) return readRunningLabel(1);
  const detail = lineDetail(block);
  return `Read ${file}${detail ? ` - ${detail}` : ""}`;
}

function searchEventText(block: ToolBlockUi, summary?: string) {
  if (block.status === "permission_required") return `Permission required for ${searchStaticLabel(block)}`;
  if (block.status === "error") return `Failed ${searchStaticLabel(block)}`;
  if (isRunning(block)) return searchRunningLabel();
  const label = searchStaticLabel(block);
  return summary ? `${label} ${summary}` : label;
}

function writeEventText(block: ToolBlockUi) {
  const file = writeFileLabel(block);
  const verb = block.name === "Edit" ? "Edit" : "Write";
  const label = file ? `${verb} - ${file}` : verb;
  if (block.status === "permission_required") return `Permission required for ${label}`;
  if (block.status === "error") return `Failed ${label}`;
  if (isRunning(block)) return `${label} running`;
  return label;
}

function writePreviewTitle(block: ToolBlockUi) {
  const file = writeFileLabel(block);
  const action = block.name === "Edit" ? "Edit preview" : "File preview";
  return file ? `${action}: ${file}` : action;
}

function writeFileLabel(block: ToolBlockUi) {
  return (
    stringValue(block.data?.display_path) ??
    stringValue(block.data?.path) ??
    (block.path?.trim() ? block.path.trim() : undefined)
  );
}

function writeLineStats(block: ToolBlockUi) {
  const dataAdded = numberValue(block.data?.added_lines);
  const dataRemoved = numberValue(block.data?.removed_lines);
  if (typeof dataAdded === "number" || typeof dataRemoved === "number") {
    return { added: dataAdded ?? 0, removed: dataRemoved ?? 0 };
  }

  const diff = rawStringValue(block.data?.diff);
  if (diff?.trim()) return diffLineStats(diff);

  const writtenContent = writeWrittenContent(block);
  if (typeof writtenContent === "string") {
    return { added: contentLineCount(writtenContent), removed: 0 };
  }

  return { added: 0, removed: 0 };
}

function writeOutputRows(block: ToolBlockUi): WriteOutputRow[] {
  const diff = rawStringValue(block.data?.diff);
  if (diff?.trim()) {
    return writeOutputRowsFromDiff(diff);
  }

  const writtenContent = writeWrittenContent(block);
  if (typeof writtenContent === "string") {
    return contentLines(writtenContent).map((line, index) => ({
      kind: "add",
      marker: "+",
      text: line,
      newLine: index + 1,
    }));
  }

  if (isError(block) && block.content.trim()) {
    return block.content.split(/\r?\n/).map((line) => ({ kind: "error", marker: "!", text: line }));
  }

  return [];
}

function writeHasOutput(block: ToolBlockUi) {
  const diff = rawStringValue(block.data?.diff);
  if (diff?.trim()) return true;
  const writtenContent = writeWrittenContent(block);
  if (typeof writtenContent === "string") return writtenContent.length > 0;
  return isError(block) && hasNonWhitespace(block.content);
}

function writeOutputRowsFromDiff(diff: string): WriteOutputRow[] {
  let oldLine = 0;
  let newLine = 0;
  return diff.split(/\r?\n/).map((line) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      return { kind: "meta", marker: "", text: line };
    }

    if (line.startsWith("+++") || line.startsWith("---")) {
      return { kind: "meta", marker: "", text: line };
    }

    if (line.startsWith("+")) {
      const row = writeOutputRowFromDiffLine(line, undefined, newLine);
      newLine += 1;
      return row;
    }
    if (line.startsWith("-")) {
      const row = writeOutputRowFromDiffLine(line, oldLine, undefined);
      oldLine += 1;
      return row;
    }
    if (line.startsWith(" ")) {
      const row = writeOutputRowFromDiffLine(line, oldLine, newLine);
      oldLine += 1;
      newLine += 1;
      return row;
    }
    return writeOutputRowFromDiffLine(line, oldLine || undefined, newLine || undefined);
  });
}

function writeOutputRowFromDiffLine(line: string, oldLine?: number, newLine?: number): WriteOutputRow {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
    return { kind: "meta", marker: "", text: line };
  }
  if (line.startsWith("+")) return { kind: "add", marker: "+", text: line.slice(1), newLine };
  if (line.startsWith("-")) return { kind: "remove", marker: "-", text: line.slice(1), oldLine };
  if (line.startsWith(" ")) return { kind: "context", marker: "", text: line.slice(1), oldLine, newLine };
  return { kind: "context", marker: "", text: line, oldLine, newLine };
}

function diffLineStats(diff: string) {
  let added = 0;
  let removed = 0;
  for (const line of diff.split(/\r?\n/)) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added += 1;
    if (line.startsWith("-")) removed += 1;
  }
  return { added, removed };
}

function writeWrittenContent(block: ToolBlockUi) {
  return rawStringValue(block.data?.written_content) ?? rawStringValue(block.data?.new_content);
}

function contentLines(content: string) {
  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (normalized === "") return [];
  const lines = normalized.split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

function contentLineCount(content: string) {
  if (content.length === 0) return 0;
  let count = 1;
  for (let index = 0; index < content.length; index += 1) {
    if (content[index] === "\n") count += 1;
  }
  return content.endsWith("\n") ? count - 1 : count;
}


function inlineToolText(block: ToolBlockUi) {
  const browserText = browserInlineText(block);
  if (browserText) return browserText;

  const label =
    block.name === "Grep" || block.name === "search_files"
      ? searchLabel(block)
      : block.name === "Glob"
        ? globLabel(block)
        : block.name === "WebFetch"
          ? webFetchLabel(block)
          : block.name === "LSP"
            ? lspLabel(block)
            : isTodoTool(block)
              ? todoLabel(block)
              : block.name === "shell"
                ? shellLabel(block)
                : block.name === "Task" || block.name.startsWith("Task")
                  ? taskLabel(block)
                  : block.title.trim() || block.name;

  if (block.status === "permission_required") return `Permission required for ${label}`;
  if (block.status === "error") return `Failed ${label}`;
  if (isRunning(block)) return `${label} running`;
  return label;
}

function lspLabel(block: ToolBlockUi) {
  const operation = stringValue(block.data?.operation);
  return operation ? `LSP ${operation}` : "LSP";
}

function todoLabel(block: ToolBlockUi) {
  const todos = todoItems(block);
  return todos.length > 0 ? `${block.name} ${todos.length} items` : block.name;
}

function taskLabel(block: ToolBlockUi) {
  const task = block.data?.task;
  if (task && typeof task === "object" && "title" in task) {
    const title = stringValue((task as Record<string, unknown>).title);
    if (title) return `${block.name} ${title}`;
  }
  const taskId = stringValue(block.data?.task_id);
  return taskId ? `${block.name} ${taskId}` : block.name;
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

export function isTodoTool(block: Pick<ToolBlockUi, "name">) {
  return block.name.toLowerCase().startsWith("todo");
}

function isFileMutationTool(block: Pick<ToolBlockUi, "name">) {
  return block.name === "Write" || block.name === "Edit";
}

function isSearchTool(block: ToolBlockUi) {
  return block.name === "Glob" || block.name === "Grep" || block.name === "search_files" || isSearchShellCommand(block);
}

export function isSearchShellCommand(block: ToolBlockUi) {
  if (block.name !== "shell") return false;
  const command = stringValue(block.data?.command);
  const base = command ? shellCommandBase(command) : undefined;
  return base === "find" || base === "grep" || base === "rg";
}

function searchStaticLabel(block: ToolBlockUi) {
  if (block.name === "Glob") return globLabel(block);
  if (block.name === "shell") return shellLabel(block);
  return searchLabel(block);
}

function searchLabel(block: ToolBlockUi) {
  const prefix = block.name === "search_files" ? "Search" : "Grep";
  const pattern = stringValue(block.data?.pattern);
  if (pattern) return `${prefix} - ${pattern}`;
  if (block.path) return `${prefix} - ${block.path}`;
  return prefix;
}

function globLabel(block: ToolBlockUi) {
  const pattern = stringValue(block.data?.pattern);
  return pattern ? `Glob - ${pattern}` : "Glob";
}

function webFetchLabel(block: ToolBlockUi) {
  const url = stringValue(block.data?.final_url) ?? stringValue(block.data?.url);
  return url ? `Fetch ${url}` : "WebFetch";
}


function compactGenericToolLabel(kindName: string) {
  return kindName.replace(/[_-]+/g, " ");
}


function latestTodoBlock(blocks: ToolBlockUi[]) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    if (todoItems(blocks[index]).length > 0) return blocks[index];
  }
  return blocks[blocks.length - 1];
}

function todoPanelStatus(blocks: ToolBlockUi[]): ToolBlockStatus {
  if (blocks.some(isError)) return "error";
  if (blocks.some(isRunning)) return "running";
  return "completed";
}

function todoProgressLabel(status: ToolBlockStatus, completed: number, total: number) {
  if (status === "running" || status === "queued") return "updating";
  if (status === "error" || status === "permission_required") return "failed";
  return `${completed}/${total} done`;
}


function todoStatusLabel(status: TodoItem["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}


function lineDetail(block: ToolBlockUi) {
  const start = block.data?.start_line;
  const end = block.data?.end_line;
  const truncated = block.data?.truncated === true;
  const range = typeof start === "number" && typeof end === "number" && end >= start ? (start === end ? `L${start}` : `L${start}-L${end}`) : undefined;
  if (!range && !truncated) return undefined;
  return [range, truncated ? "truncated" : undefined].filter(Boolean).join(" - ");
}

function fileLabel(block: ToolBlockUi) {
  if (block.path?.trim()) return block.path.trim();
  const title = block.title.trim();
  if (title.startsWith("Read ") && title.length > 5) return title.slice(5);
  if (title && title !== "Reading file") return title;
  return "file";
}

function shellCommandText(block: ToolBlockUi) {
  const command = stringValue(block.data?.command);
  const text = command || block.title.trim() || "Shell command";
  if (block.status === "permission_required") return `Permission required: ${text}`;
  if (block.status === "error") return `Failed: ${text}`;
  if (isRunning(block)) return `${text} running`;
  return text;
}

function shellOutputPreview(output: string) {
  const firstLine = output.split("\n").find((line) => line.trim().length > 0)?.trimEnd();
  if (!firstLine) return undefined;
  return firstLine.length > 140 ? `${firstLine.slice(0, 139)}...` : firstLine;
}

function hasNonWhitespace(value: string) {
  return /\S/.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function shellCommandBase(command: string) {
  return /^\s*([^\s]+)/.exec(command)?.[1];
}

function isError(block: ToolBlockUi) {
  return isErrorStatus(block.status);
}

function isErrorStatus(status: ToolBlockStatus) {
  return status === "error";
}

function isWarningStatus(status: ToolBlockStatus) {
  return status === "permission_required";
}

function statusTextClass(status: ToolBlockStatus) {
  if (isErrorStatus(status)) return "text-destructive";
  if (isWarningStatus(status)) return "text-warning";
  return "text-muted-foreground";
}

function statusDotClass(status: ToolBlockStatus) {
  if (isErrorStatus(status)) return "bg-destructive";
  if (isWarningStatus(status)) return "bg-warning";
  return "bg-success";
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
