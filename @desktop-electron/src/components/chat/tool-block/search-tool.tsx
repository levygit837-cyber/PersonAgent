import { useMemo } from "react";
import type { ToolBlockUi } from "../../../types/chat";
import { searchHasOutput, searchMetadata, searchOutputPreview, searchOutputRows, searchOutputText, searchSummary, type SearchOutputRow } from "./search-output";
import { isRunning, statusTextClass, stringValue } from "./shared";
import { StatusDot, ArtifactNotice } from "./shared";
import { useToolOutputCollapsed } from "./visibility";

export function searchRunningLabel() {
  return "Searching...";
}

export function searchCollapsedLabel(count: number) {
  return `Search ${count} ${count === 1 ? "time" : "times"} >`;
}

export function SearchToolEvent({ block, nested = false }: { block: ToolBlockUi; nested?: boolean; forceExpanded?: boolean }) {
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

function searchEventText(block: ToolBlockUi, summary?: string) {
  if (block.status === "permission_required") return `Permission required for ${searchStaticLabel(block)}`;
  if (block.status === "error") return `Failed ${searchStaticLabel(block)}`;
  if (isRunning(block)) return searchRunningLabel();
  const label = searchStaticLabel(block);
  return summary ? `${label} ${summary}` : label;
}

function searchStaticLabel(block: ToolBlockUi) {
  if (block.name === "Glob") return globLabel(block);
  if (block.name === "shell") return shellLabelFromBlock(block);
  return searchLabel(block);
}

export function searchLabel(block: ToolBlockUi) {
  const prefix = block.name === "search_files" ? "Search" : "Grep";
  const pattern = stringValue(block.data?.pattern);
  if (pattern) return `${prefix} - ${pattern}`;
  if (block.path) return `${prefix} - ${block.path}`;
  return prefix;
}

export function globLabel(block: ToolBlockUi) {
  const pattern = stringValue(block.data?.pattern);
  return pattern ? `Glob - ${pattern}` : "Glob";
}

export function webFetchLabel(block: ToolBlockUi) {
  const url = stringValue(block.data?.final_url) ?? stringValue(block.data?.url);
  return url ? `Fetch ${url}` : "WebFetch";
}

function shellLabelFromBlock(block: ToolBlockUi) {
  const command = stringValue(block.data?.command);
  return command || block.title.trim() || "Shell command";
}
