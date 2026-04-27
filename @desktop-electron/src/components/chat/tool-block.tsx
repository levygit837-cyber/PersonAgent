import { useMemo, useState } from "react";
import type { ToolBlockStatus, ToolBlockUi } from "../../types/chat";

const TOOL_OUTPUT_VISIBILITY_STORAGE_KEY = "personagent.toolOutputVisibility";

type SearchOutputRow = {
  kind: "file" | "match" | "line";
  file?: string;
  line?: string;
  text: string;
};

type WriteOutputRow = {
  kind: "add" | "remove" | "context" | "meta" | "error";
  marker: string;
  text: string;
};

export type TodoItem = {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed";
};

export function ToolBlock({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  if (block.name === "Read" || block.name === "read_file") {
    return <ReadToolEvent block={block} nested={nested} />;
  }

  if (block.name === "Write") {
    return <WriteToolEvent block={block} nested={nested} />;
  }

  if (isTodoTool(block)) {
    return <TodoToolEvent block={block} nested={nested} />;
  }

  if (isSearchTool(block)) {
    return <SearchToolEvent block={block} nested={nested} />;
  }

  return <GenericToolEvent block={block} nested={nested} />;
}

export function CompactToolGroupBlock({ kind, blocks }: { kind: string; blocks: ToolBlockUi[] }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true);
  const hasError = blocks.some(isError);
  const hasRunning = blocks.some(isRunning);
  const status: ToolBlockStatus = hasError ? "error" : hasRunning ? "running" : "completed";
  const hasDetails = blocks.some(toolBlockHasDetails);

  if (kind === "todo") {
    return <TodoToolGroupBlock blocks={blocks} />;
  }

  return (
    <div className="mb-2">
      <button
        type="button"
        className="flex w-fit items-center gap-2 rounded-lg px-1.5 py-[2px] -ml-1.5 font-mono text-[11px] transition-colors hover:bg-glass/70"
        onClick={() => !hasRunning && hasDetails && toggleCollapsed()}
      >
        <StatusDot status={status} />
        <span className={hasError ? "text-destructive" : hasRunning ? "text-muted-foreground" : "text-muted-foreground hover:text-foreground"}>
          {groupLabel(kind, blocks, collapsed)}
        </span>
      </button>
      {!hasRunning && hasDetails && !collapsed ? (
        <div className="ml-4 mt-2">
          {blocks.map((block) => {
            if (kind === "read") return <ReadToolEvent key={block.id} block={block} nested />;
            if (kind === "search") return <SearchToolEvent key={block.id} block={block} nested />;
            if (kind === "shell") return <ShellToolEvent key={block.id} block={block} nested />;
            if (kind === "todo") return <TodoToolEvent key={block.id} block={block} nested />;
            return <GenericToolEvent key={block.id} block={block} nested />;
          })}
        </div>
      ) : null}
    </div>
  );
}

function ReadToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  return (
    <div className={nested ? "mb-1 flex items-center gap-2" : "mb-2 flex items-center gap-2"}>
      <StatusDot status={block.status} size={6} />
      <span className={isError(block) ? "min-w-0 truncate font-mono text-xs text-destructive" : "min-w-0 truncate font-mono text-xs text-muted-foreground"}>
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
          <StatusDot status={status} size={7} />
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

function SearchToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true);
  const rows = useMemo(() => (collapsed ? [] : searchOutputRows(block)), [block, collapsed]);
  const hasOutput = searchHasOutput(block);
  const summary = searchSummary(block);
  const preview = searchOutputPreview(block);

  return (
    <div className={nested ? "mb-2" : "mb-3"}>
      <div className="flex items-start gap-2">
        <div className="pt-1">
          <StatusDot status={block.status} size={6} />
        </div>
        <div className="min-w-0 flex-1">
          <div className={isError(block) ? "truncate font-mono text-xs text-destructive" : "truncate font-mono text-xs text-muted-foreground"}>
            {searchEventText(block)}
          </div>
          {summary ? <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{summary}</div> : null}
          {preview ? <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{preview}</div> : null}
          {hasOutput && !isRunning(block) ? (
            <button type="button" className="mt-1 font-mono text-[11px] text-primary" onClick={toggleCollapsed}>
              Output - {collapsed ? "Show" : "Hide"}
            </button>
          ) : null}
        </div>
      </div>
      {hasOutput && !collapsed ? <SearchOutputPanel block={block} rows={rows} /> : null}
    </div>
  );
}

function WriteToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(block.isCollapsed);
  const rows = useMemo(() => (collapsed ? [] : writeOutputRows(block)), [block, collapsed]);
  const hasOutput = writeHasOutput(block);
  const stats = writeLineStats(block);
  const showStats = !isRunning(block) && !isError(block) && (stats.added > 0 || stats.removed > 0);

  return (
    <div className={nested ? "mb-1" : "mb-2"}>
      <button
        type="button"
        disabled={!hasOutput}
        className="flex w-full min-w-0 flex-wrap items-center gap-2 text-left font-mono text-xs disabled:cursor-default"
        onClick={() => hasOutput && toggleCollapsed()}
      >
        <StatusDot status={block.status} />
        <span className={isError(block) ? "text-destructive" : "text-muted-foreground"}>{writeEventText(block)}</span>
        {showStats ? (
          <span className="flex items-center gap-1">
            {stats.added > 0 ? <span className="font-medium text-success">+{stats.added}</span> : null}
            {stats.removed > 0 ? <span className="font-medium text-destructive">-{stats.removed}</span> : null}
          </span>
        ) : null}
        {hasOutput ? (
          <>
            <span className="text-muted-foreground/70">-</span>
            <span className="text-primary">{collapsed ? "Show" : "Hide"}</span>
          </>
        ) : null}
      </button>
      {hasOutput && !collapsed ? <WriteOutputPanel rows={rows} /> : null}
    </div>
  );
}

function ShellToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(true);
  const output = block.content.trimEnd();
  const hasOutput = output.trim().length > 0;
  return (
    <div className={nested ? "mb-2" : "mb-3"}>
      <div className="flex items-start gap-2">
        <div className="pt-1">
          <StatusDot status={block.status} size={6} />
        </div>
        <div className="min-w-0 flex-1">
          <div className={isError(block) ? "truncate font-mono text-xs text-destructive" : "truncate font-mono text-xs text-muted-foreground"}>
            {shellCommandText(block)}
          </div>
          {shellOutputPreview(output) ? (
            <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground/70">{shellOutputPreview(output)}</div>
          ) : null}
          {hasOutput ? (
            <button type="button" className="mt-1 font-mono text-[11px] text-primary" onClick={toggleCollapsed}>
              Output - {collapsed ? "Show" : "Hide"}
            </button>
          ) : null}
        </div>
      </div>
      {hasOutput && !collapsed ? (
        <pre className="ml-4 mt-2 max-h-72 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 font-mono text-[11px] leading-5 text-muted-foreground shadow-soft">
          {output}
        </pre>
      ) : null}
    </div>
  );
}

function useToolOutputCollapsed(fallbackCollapsed: boolean) {
  const [collapsed, setCollapsed] = useState(() => initialToolOutputCollapsed(fallbackCollapsed));

  const toggleCollapsed = () => {
    setCollapsed((value) => {
      const next = !value;
      persistToolOutputCollapsed(next);
      return next;
    });
  };

  return [collapsed, toggleCollapsed] as const;
}

function initialToolOutputCollapsed(fallbackCollapsed: boolean) {
  const persisted = readPersistedToolOutputCollapsed();
  return persisted ?? fallbackCollapsed;
}

function readPersistedToolOutputCollapsed() {
  if (typeof window === "undefined") return undefined;
  try {
    const value = window.localStorage.getItem(TOOL_OUTPUT_VISIBILITY_STORAGE_KEY);
    if (value === "show") return false;
    if (value === "hide") return true;
  } catch {
    return undefined;
  }
  return undefined;
}

function persistToolOutputCollapsed(collapsed: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOOL_OUTPUT_VISIBILITY_STORAGE_KEY, collapsed ? "hide" : "show");
  } catch {
    // Ignore storage failures; the current click should still update the visible row.
  }
}

function WriteOutputPanel({ rows }: { rows: WriteOutputRow[] }) {
  return (
    <div className="ml-4 mt-2 max-h-80 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 font-mono text-[11px] leading-5 shadow-soft">
      {rows.map((row, index) => (
        <WriteOutputLine key={`${row.kind}-${index}-${row.text}`} row={row} />
      ))}
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

  return (
    <div className={`grid grid-cols-[2.25rem_minmax(0,1fr)] border-b border-glass-border/25 py-0.5 last:border-0 ${className}`}>
      <span className="select-none pr-3 text-right opacity-80">{row.marker}</span>
      <span className="whitespace-pre-wrap break-words pr-3">{row.text.length > 0 ? row.text : " "}</span>
    </div>
  );
}

function GenericToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean }) {
  const [collapsed, toggleCollapsed] = useToolOutputCollapsed(block.isCollapsed);
  const hasDetails = block.content.trim().length > 0;
  const error = isError(block);

  return (
    <div className={nested ? "mb-1" : "mb-2"}>
      <button
        type="button"
        disabled={!hasDetails}
        onClick={toggleCollapsed}
        className="flex w-full items-center gap-2 text-left font-mono text-xs disabled:cursor-default"
      >
        <StatusDot status={block.status} size={nested ? 6 : 8} />
        <span className={error ? "min-w-0 flex-1 truncate text-destructive" : "min-w-0 flex-1 truncate text-muted-foreground"}>
          {inlineToolText(block)}
          {hasDetails ? ` - ${collapsed ? "Show" : "Hide"}` : ""}
        </span>
      </button>
      {hasDetails && !collapsed ? (
        <pre className="ml-4 mt-2 max-h-72 overflow-auto rounded-xl border border-glass-border/35 bg-card/80 p-3 font-mono text-[11px] leading-5 text-muted-foreground shadow-soft">
          {block.content}
        </pre>
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
  if (block.name === "Write") return writeHasOutput(block);
  if (isTodoTool(block)) return todoItems(block).length > 0 || block.content.trim().length > 0;
  if (isSearchTool(block)) return searchHasOutput(block);
  return block.content.trim().length > 0;
}

function StatusDot({ status, size = 8 }: { status: ToolBlockStatus; size?: number }) {
  const running = status === "running" || status === "queued";
  const color = isErrorStatus(status) ? "bg-destructive" : "bg-success";
  return running ? (
    <span className="personagent-spinner shrink-0 text-muted-foreground" style={{ width: size, height: size }} aria-hidden="true" />
  ) : (
    <span className={`shrink-0 rounded-full ${color}`} style={{ width: size, height: size }} />
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

function searchEventText(block: ToolBlockUi) {
  if (block.status === "permission_required") return `Permission required for ${searchStaticLabel(block)}`;
  if (block.status === "error") return `Failed ${searchStaticLabel(block)}`;
  if (isRunning(block)) return searchRunningLabel();
  return searchStaticLabel(block);
}

function writeEventText(block: ToolBlockUi) {
  const file = writeFileLabel(block);
  const label = file ? `Write - ${file}` : "Write";
  if (block.status === "permission_required") return `Permission required for ${label}`;
  if (block.status === "error") return `Failed ${label}`;
  if (isRunning(block)) return `${label} running`;
  return label;
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
    return diff.split(/\r?\n/).map((line) => writeOutputRowFromDiffLine(line));
  }

  const writtenContent = writeWrittenContent(block);
  if (typeof writtenContent === "string") {
    return contentLines(writtenContent).map((line) => ({ kind: "add", marker: "+", text: line }));
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

function writeOutputRowFromDiffLine(line: string): WriteOutputRow {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) {
    return { kind: "meta", marker: "", text: line };
  }
  if (line.startsWith("+")) return { kind: "add", marker: "+", text: line.slice(1) };
  if (line.startsWith("-")) return { kind: "remove", marker: "-", text: line.slice(1) };
  if (line.startsWith(" ")) return { kind: "context", marker: "", text: line.slice(1) };
  return { kind: "context", marker: "", text: line };
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

function searchSummary(block: ToolBlockUi) {
  if (isRunning(block)) return undefined;
  const data = block.data;
  const parts: string[] = [];
  const count = numberValue(data?.matches) ?? numberValue(data?.count);
  const shown = numberValue(data?.shown);

  if (typeof count === "number") {
    const label = block.name === "Glob" ? "file" : "match";
    parts.push(`${count} ${count === 1 ? label : `${label}s`}`);
  }
  if (typeof shown === "number" && typeof count === "number" && shown !== count) {
    parts.push(`showing ${shown}`);
  }
  if (data?.truncated === true) parts.push("truncated");
  if (data?.timed_out === true) parts.push("timed out");

  return parts.join(" - ");
}

function inlineToolText(block: ToolBlockUi) {
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

function groupLabel(kind: string, blocks: ToolBlockUi[], collapsed: boolean) {
  const count = blocks.length;
  if (kind === "read") return blocks.some(isRunning) ? readRunningLabel(count) : collapsed ? readCollapsedLabel(count) : `Read ${count} ${count === 1 ? "File" : "Files"} Hide`;
  if (kind === "shell") return `${blocks.some(isRunning) ? "Running" : "Ran"} ${count} ${count === 1 ? "command" : "commands"}`;
  if (kind === "search") return blocks.some(isRunning) ? searchRunningLabel() : collapsed ? searchCollapsedLabel(count) : `Search ${count} ${count === 1 ? "time" : "times"} Hide`;
  if (kind === "web") return `Fetched ${count} URLs`;
  if (kind === "task") return `Updated ${count} tasks`;
  if (kind === "todo") return `Updated ${count} todo ${count === 1 ? "list" : "lists"}`;
  if (kind === "lsp") return `Ran ${count} LSP queries`;
  return `${count} tool calls`;
}

export function isTodoTool(block: Pick<ToolBlockUi, "name">) {
  return block.name.toLowerCase().startsWith("todo");
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
  if (pattern) return `${prefix} ${pattern}`;
  if (block.path) return `${prefix} ${block.path}`;
  return prefix;
}

function globLabel(block: ToolBlockUi) {
  const pattern = stringValue(block.data?.pattern);
  return pattern ? `Glob ${pattern}` : "Glob";
}

function webFetchLabel(block: ToolBlockUi) {
  const url = stringValue(block.data?.final_url) ?? stringValue(block.data?.url);
  return url ? `Fetch ${url}` : "WebFetch";
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

function shellLabel(block: ToolBlockUi) {
  const command = stringValue(block.data?.command);
  if (!command) return "Shell command";
  const base = shellCommandBase(command);
  const args = base ? command.slice(base.length).trim() : "";
  if (base === "find") return `Find ${args}`;
  if (base === "grep") return `Grep ${args}`;
  if (base === "rg") return `Search ${args}`;
  return `Shell ${command}`;
}

function searchMetadata(block: ToolBlockUi) {
  const data = block.data;
  const items: { label: string; value: string }[] = [];
  const command = stringValue(data?.command);
  const pattern = stringValue(data?.pattern);
  const path = stringValue(data?.display_path) ?? stringValue(data?.path);
  const count = numberValue(data?.matches) ?? numberValue(data?.count);
  const shown = numberValue(data?.shown);
  const returnCode = numberValue(data?.return_code);

  if (command) items.push({ label: "Command", value: command });
  if (pattern) items.push({ label: "Pattern", value: pattern });
  if (path) items.push({ label: "Path", value: path });
  if (typeof count === "number") items.push({ label: block.name === "Glob" ? "Files" : "Matches", value: String(count) });
  if (typeof shown === "number") items.push({ label: "Shown", value: String(shown) });
  if (typeof returnCode === "number") items.push({ label: "Return code", value: String(returnCode) });
  if (data?.truncated === true) items.push({ label: "Truncated", value: "true" });
  if (data?.timed_out === true) items.push({ label: "Timed out", value: "true" });

  return items;
}

function searchOutputRows(block: ToolBlockUi): SearchOutputRow[] {
  const matches = block.data?.matches;
  if (Array.isArray(matches)) {
    return matches.map((item) => ({ kind: "file" as const, text: String(item) })).filter((row) => row.text.trim().length > 0);
  }

  const output = searchOutputText(block);
  if (!output.trim()) return [];
  return output
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
    .map((line) => searchOutputRowFromLine(line, block));
}

function searchOutputRowFromLine(line: string, block: ToolBlockUi): SearchOutputRow {
  const parsed = /^(.+?):(\d+):(.*)$/.exec(line);
  if (parsed) {
    return {
      kind: "match",
      file: parsed[1],
      line: parsed[2],
      text: parsed[3].trim(),
    };
  }

  const command = stringValue(block.data?.command);
  const base = command ? shellCommandBase(command) : undefined;
  if (block.name === "Glob" || base === "find") {
    return { kind: "file", text: line };
  }

  return { kind: "line", text: line };
}

function searchOutputText(block: ToolBlockUi) {
  return rawStringValue(block.data?.content) ?? block.content;
}

function searchHasOutput(block: ToolBlockUi) {
  const matches = block.data?.matches;
  return (Array.isArray(matches) && matches.length > 0) || hasNonWhitespace(searchOutputText(block));
}

function searchOutputPreview(block: ToolBlockUi) {
  const matches = block.data?.matches;
  const firstLine = firstNonEmptyLine(searchOutputText(block));
  const first =
    Array.isArray(matches) && matches.length > 0
      ? { kind: "file" as const, text: String(matches[0]) }
      : firstLine
        ? searchOutputRowFromLine(firstLine, block)
        : undefined;
  if (!first) return undefined;
  const text = first.kind === "match" ? `${first.file}:${first.line} ${first.text}` : first.text;
  return text.length > 140 ? `${text.slice(0, 139)}...` : text;
}

function firstNonEmptyLine(output: string) {
  let start = 0;
  while (start <= output.length) {
    const end = output.indexOf("\n", start);
    const lineEnd = end === -1 ? output.length : end;
    const line = output.slice(start, lineEnd).trimEnd();
    if (line.trim().length > 0) return line;
    if (end === -1) return undefined;
    start = end + 1;
  }
  return undefined;
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

export function todoItems(block: ToolBlockUi): TodoItem[] {
  const rawTodos =
    arrayValue(block.data?.todos) ??
    arrayValue(block.data?.items) ??
    arrayValue(block.data?.todo_list) ??
    singleTodoValue(block.data?.todo) ??
    todoArrayFromContent(block.content);

  return rawTodos
    .map((item, index) => normalizeTodoItem(item, index))
    .filter((item): item is TodoItem => Boolean(item));
}

function normalizeTodoItem(value: unknown, index: number): TodoItem | undefined {
  if (!isRecord(value)) return undefined;
  const content =
    stringValue(value.content) ??
    stringValue(value.title) ??
    stringValue(value.text) ??
    stringValue(value.description);
  if (!content) return undefined;
  const id = stringValue(value.id) ?? `${content}-${index}`;
  return {
    id,
    content,
    status: todoStatusValue(value.status),
  };
}

function todoStatusValue(value: unknown): TodoItem["status"] {
  if (typeof value !== "string") return "pending";
  const normalized = value.trim().toLowerCase().replace(/-/g, "_");
  if (normalized === "completed" || normalized === "complete" || normalized === "done") return "completed";
  if (normalized === "in_progress" || normalized === "running" || normalized === "active") return "in_progress";
  return "pending";
}

function todoStatusLabel(status: TodoItem["status"]) {
  if (status === "completed") return "completed";
  if (status === "in_progress") return "in progress";
  return "pending";
}

function todoArrayFromContent(content: string): unknown[] {
  if (!content.trim()) return [];
  try {
    const parsed: unknown = JSON.parse(content);
    if (!isRecord(parsed)) return [];
    return (
      arrayValue(parsed.todos) ??
      arrayValue(parsed.items) ??
      arrayValue(parsed.todo_list) ??
      singleTodoValue(parsed.todo) ??
      []
    );
  } catch {
    return [];
  }
}

function arrayValue(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function singleTodoValue(value: unknown): unknown[] | undefined {
  return isRecord(value) ? [value] : undefined;
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
  return status === "error" || status === "permission_required";
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
