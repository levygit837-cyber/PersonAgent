import { useMemo } from "react";
import type { ToolBlockUi } from "../../../types/chat";
import { hasNonWhitespace, isError, isRunning, numberValue, rawStringValue, statusTextClass, stringValue } from "./shared";
import { StatusDot } from "./shared";
import { useToolOutputCollapsed } from "./visibility";

export type WriteOutputRow = {
  kind: "add" | "remove" | "context" | "meta" | "error";
  marker: string;
  text: string;
  oldLine?: number;
  newLine?: number;
};

export function WriteToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
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

export function writeOutputRows(block: ToolBlockUi): WriteOutputRow[] {
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

export function writeHasOutput(block: ToolBlockUi) {
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
