import { type ReactElement } from "react";
import { AlertCircle, Brain, Check, Database, GitBranchPlus, Loader2, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import type {
  ChatMessageUi,
  MemoryTrace,
  MemoryTraceClassicItem,
  MemoryTraceOperationalItem,
} from "../../../types/chat";
import { useChatStore } from "../../../stores/chat-store";
import { Button } from "../../ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../ui/tooltip";

export type MemoryTraceTab = "used" | "filters" | "prompt";

export function AgentMessageActions({
  message,
  memoryTrace,
  memoryInspectorOpen,
  onToggleMemoryInspector,
}: {
  message: ChatMessageUi;
  memoryTrace?: MemoryTrace;
  memoryInspectorOpen: boolean;
  onToggleMemoryInspector: () => void;
}) {
  const isStreaming = useChatStore((state) => state.isStreaming);
  const setAgentFeedback = useChatStore((state) => state.setAgentFeedback);
  const regenerateAgentMessage = useChatStore((state) => state.regenerateAgentMessage);
  const branchAgentMessage = useChatStore((state) => state.branchAgentMessage);
  const feedback = stringMetadata(message.metadata?.feedback);
  const worktreeStatus = stringMetadata(message.metadata?.worktree_status);
  const worktreeError = stringMetadata(message.metadata?.worktree_error);
  const worktreePath = stringMetadata(message.metadata?.worktree_path);
  const worktreeBranch = stringMetadata(message.metadata?.worktree_branch);
  const branchPending = worktreeStatus === "running";

  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 opacity-70 transition-opacity group-hover/agent-message:opacity-100 focus-within:opacity-100">
      {memoryTrace ? (
        <MemoryTraceBadge
          trace={memoryTrace}
          open={memoryInspectorOpen}
          onClick={onToggleMemoryInspector}
        />
      ) : null}
      <TooltipIconButton
        label={feedback === "positive" ? "Positive feedback selected" : "Positive feedback"}
        active={feedback === "positive"}
        activeClassName="bg-success/15 text-success"
        disabled={isStreaming}
        onClick={() => setAgentFeedback(message.id, "positive")}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label={feedback === "negative" ? "Negative feedback selected" : "Negative feedback"}
        active={feedback === "negative"}
        activeClassName="bg-destructive/15 text-destructive"
        disabled={isStreaming}
        onClick={() => setAgentFeedback(message.id, "negative")}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label="Regenerate"
        disabled={isStreaming}
        onClick={() => {
          void regenerateAgentMessage(message.id);
        }}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </TooltipIconButton>
      <TooltipIconButton
        label={branchPending ? "Creating worktree" : "Branch to worktree"}
        active={worktreeStatus === "ready"}
        activeClassName="bg-primary/15 text-primary"
        disabled={isStreaming || branchPending}
        onClick={() => {
          void branchAgentMessage(message.id);
        }}
      >
        {branchPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitBranchPlus className="h-3.5 w-3.5" />}
      </TooltipIconButton>
      {feedback ? (
        <span className="ml-1 inline-flex items-center gap-1 rounded-full border border-glass-border/30 bg-background/45 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
          <Check className="h-3 w-3" />
          Feedback saved
        </span>
      ) : null}
      {worktreeStatus === "ready" ? (
        <span
          className="ml-1 min-w-0 truncate rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 font-mono text-[10px] text-primary"
          title={worktreePath}
        >
          Worktree: {worktreeBranch || compactMetadataPath(worktreePath)}
        </span>
      ) : null}
      {worktreeStatus === "error" && worktreeError ? (
        <span className="ml-1 inline-flex min-w-0 items-center gap-1 rounded-full border border-destructive/25 bg-destructive/10 px-2 py-0.5 font-mono text-[10px] text-destructive">
          <AlertCircle className="h-3 w-3 shrink-0" />
          <span className="truncate">{worktreeError}</span>
        </span>
      ) : null}
    </div>
  );
}

function MemoryTraceBadge({
  trace,
  open,
  onClick,
}: {
  trace: MemoryTrace;
  open: boolean;
  onClick: () => void;
}) {
  const total = trace.summary.total_used;
  const latency = trace.summary.latency_ms > 0 ? ` · ${Math.round(trace.summary.latency_ms)}ms` : "";
  const tooltip = `${trace.summary.rag_count} RAG, ${trace.summary.classic_count} classic, ${trace.summary.omitted_count} omitted`;
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`Memory trace: ${total} memories used`}
            aria-expanded={open}
            onClick={onClick}
            className={`inline-flex h-7 items-center gap-1 rounded-lg border px-2 py-0.5 font-mono text-[10px] transition-colors ${
              open
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-glass-border/30 bg-background/45 text-muted-foreground hover:border-glass-border/60 hover:text-foreground"
            }`}
          >
            <Database className="h-3 w-3" aria-hidden="true" />
            <span>Memory {total}{latency}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function MemoryTraceInspector({
  trace,
  activeTab,
  onTabChange,
}: {
  trace: MemoryTrace;
  activeTab: MemoryTraceTab;
  onTabChange: (tab: MemoryTraceTab) => void;
}) {
  const tabs: Array<[MemoryTraceTab, string]> = [
    ["used", "Used"],
    ["filters", "Filters"],
    ["prompt", "Prompt"],
  ];
  return (
    <section className="mt-2 overflow-hidden rounded-lg border border-glass-border/35 bg-background/45 shadow-soft" aria-label="Memory trace inspector">
      <div className="flex min-w-0 items-center justify-between gap-3 border-b border-glass-border/25 px-2.5 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-glass-border/35 bg-card/60 text-primary">
            <Brain className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-xs font-medium text-foreground">Memory trace</div>
            <div className="truncate font-mono text-[10px] text-muted-foreground">
              {trace.summary.rag_count} RAG · {trace.summary.classic_count} classic · {trace.summary.omitted_count} omitted
            </div>
          </div>
        </div>
        <div className="flex shrink-0 rounded-lg border border-glass-border/30 bg-card/40 p-0.5">
          {tabs.map(([tab, label]) => (
            <button
              key={tab}
              type="button"
              onClick={() => onTabChange(tab)}
              className={`rounded-md px-2 py-1 font-mono text-[10px] transition-colors ${
                activeTab === tab ? "bg-primary/12 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="px-2.5 py-2.5">
        {activeTab === "used" ? <MemoryTraceUsed trace={trace} /> : null}
        {activeTab === "filters" ? <MemoryTraceFilters trace={trace} /> : null}
        {activeTab === "prompt" ? <MemoryTracePrompt trace={trace} /> : null}
      </div>
    </section>
  );
}

function MemoryTraceUsed({ trace }: { trace: MemoryTrace }) {
  if (trace.operational.length === 0 && trace.classic.length === 0) {
    return <div className="py-1 text-xs text-muted-foreground">No memory items were attached to this response.</div>;
  }
  return (
    <div className="space-y-3">
      {trace.operational.length > 0 ? (
        <MemoryTraceGroup title="RAG" count={trace.operational.length}>
          {trace.operational.map((item, index) => (
            <MemoryTraceOperationalRow key={`${item.source_ids?.[0] ?? item.paths?.[0] ?? item.summary ?? "rag"}-${index}`} item={item} />
          ))}
        </MemoryTraceGroup>
      ) : null}
      {trace.classic.length > 0 ? (
        <MemoryTraceGroup title="Classic" count={trace.classic.length}>
          {trace.classic.map((item, index) => (
            <MemoryTraceClassicRow key={`${item.path ?? item.name ?? "classic"}-${index}`} item={item} />
          ))}
        </MemoryTraceGroup>
      ) : null}
    </div>
  );
}

function MemoryTraceGroup({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactElement | ReactElement[];
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        <Database className="h-3 w-3" aria-hidden="true" />
        <span>{title}</span>
        <span className="rounded-full border border-glass-border/25 px-1.5 py-0.5 text-[9px]">{count}</span>
      </div>
      <div className="divide-y divide-glass-border/20 rounded-lg border border-glass-border/25 bg-card/25">{children}</div>
    </div>
  );
}

function MemoryTraceOperationalRow({ item }: { item: MemoryTraceOperationalItem }) {
  const title = item.summary || item.evidence?.[0] || item.paths?.[0] || "Operational memory";
  const score = typeof item.score === "number" ? item.score : undefined;
  return (
    <div className="min-w-0 px-2.5 py-2">
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="line-clamp-2 text-xs font-medium leading-5 text-foreground">{title}</div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
            {item.type ? <span className="rounded border border-glass-border/25 px-1.5 py-0.5">{item.type}</span> : null}
            {item.status ? <span className="rounded border border-glass-border/25 px-1.5 py-0.5">{item.status}</span> : null}
            {score !== undefined ? <span className="rounded border border-glass-border/25 px-1.5 py-0.5">score {memoryScoreLabel(score)}</span> : null}
          </div>
        </div>
      </div>
      {item.paths?.length ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {item.paths.slice(0, 3).map((path) => (
            <span key={path} className="max-w-full truncate rounded border border-glass-border/25 bg-background/35 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground" title={path}>
              {compactMemoryPath(path)}
            </span>
          ))}
        </div>
      ) : null}
      {item.evidence?.length ? (
        <div className="mt-1.5 space-y-1">
          {item.evidence.slice(0, 2).map((evidence, index) => (
            <p key={`${evidence}-${index}`} className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">
              {evidence}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MemoryTraceClassicRow({ item }: { item: MemoryTraceClassicItem }) {
  const title = item.name || item.header || item.path || "Classic memory";
  return (
    <div className="min-w-0 px-2.5 py-2">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium text-foreground">{title}</div>
          {item.header && item.header !== title ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{item.header}</div> : null}
        </div>
        {typeof item.mtime_ms === "number" && item.mtime_ms > 0 ? (
          <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{formatMemoryDate(item.mtime_ms)}</span>
        ) : null}
      </div>
      {item.path ? (
        <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={item.path}>
          {compactMemoryPath(item.path)}
        </div>
      ) : null}
      {item.snippet ? <p className="mt-1.5 line-clamp-3 text-[11px] leading-4 text-muted-foreground">{item.snippet}</p> : null}
    </div>
  );
}

function MemoryTraceFilters({ trace }: { trace: MemoryTrace }) {
  const metrics: Array<[string, string]> = [
    ["Used", formatMemoryNumber(trace.summary.total_used)],
    ["Budget", `${formatMemoryNumber(trace.summary.budget_used)} / ${formatMemoryNumber(trace.summary.budget_tokens)}`],
    ["Omitted", formatMemoryNumber(trace.summary.omitted_count)],
    ["Latency", trace.summary.latency_ms > 0 ? `${Math.round(trace.summary.latency_ms)}ms` : "0ms"],
  ];
  const filters = trace.filters_applied ?? {};
  const hasFilters = Object.keys(filters).length > 0;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 min-[680px]:grid-cols-4">
        {metrics.map(([label, value]) => (
          <div key={label} className="border-b border-glass-border/25 pb-1.5">
            <div className="font-mono text-xs text-foreground">{value}</div>
            <div className="truncate text-[10px] text-muted-foreground">{label}</div>
          </div>
        ))}
      </div>
      {hasFilters ? (
        <pre className="max-h-40 overflow-auto rounded-lg border border-glass-border/25 bg-card/40 p-2 font-mono text-[10px] leading-4 text-muted-foreground">
          {JSON.stringify(filters, null, 2)}
        </pre>
      ) : (
        <div className="py-1 text-xs text-muted-foreground">No recall filters were reported.</div>
      )}
    </div>
  );
}

function MemoryTracePrompt({ trace }: { trace: MemoryTrace }) {
  const prompt = trace.prompt?.formatted?.trim();
  if (!prompt) {
    return <div className="py-1 text-xs text-muted-foreground">No prompt memory block was captured for this response.</div>;
  }
  return (
    <div className="space-y-2">
      {trace.prompt?.truncated ? <div className="font-mono text-[10px] text-warning">Prompt block truncated for display.</div> : null}
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-glass-border/25 bg-card/40 p-2 font-mono text-[10px] leading-4 text-muted-foreground">
        {prompt}
      </pre>
    </div>
  );
}

function TooltipIconButton({
  label,
  active = false,
  activeClassName = "bg-glass/80 text-foreground",
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  active?: boolean;
  activeClassName?: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactElement;
}) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="iconSm"
            disabled={disabled}
            aria-label={label}
            onClick={onClick}
            className={`h-7 w-7 rounded-lg text-muted-foreground hover:text-foreground ${active ? activeClassName : ""}`}
          >
            {children}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function stringMetadata(value: unknown) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function compactMetadataPath(path?: string) {
  if (!path) return "ready";
  const parts = path.split("/").filter(Boolean);
  return parts.slice(-2).join("/") || path;
}

export function memoryTraceFromMetadata(value: unknown): MemoryTrace | undefined {
  const record = memoryRecord(value);
  if (!record) return undefined;
  const classic = memoryArray(record.classic).map((item) => ({
    path: memoryString(item.path),
    name: memoryString(item.name),
    header: memoryString(item.header),
    mtime_ms: memoryNumber(item.mtime_ms),
    snippet: memoryString(item.snippet),
  }));
  const operational = memoryArray(record.operational).map((item) => ({
    type: memoryString(item.type),
    summary: memoryString(item.summary),
    evidence: memoryStringArray(item.evidence),
    paths: memoryStringArray(item.paths),
    source_ids: memoryStringArray(item.source_ids),
    event_types: memoryStringArray(item.event_types),
    score: memoryNumber(item.score),
    status: memoryString(item.status),
    created_at: memoryString(item.created_at),
    metadata: memoryRecord(item.metadata),
  }));
  const rawSummary = memoryRecord(record.summary) ?? {};
  const summary = {
    total_used: memoryNumber(rawSummary.total_used) ?? classic.length + operational.length,
    classic_count: memoryNumber(rawSummary.classic_count) ?? classic.length,
    rag_count: memoryNumber(rawSummary.rag_count) ?? operational.length,
    omitted_count: memoryNumber(rawSummary.omitted_count) ?? 0,
    budget_used: memoryNumber(rawSummary.budget_used) ?? 0,
    budget_tokens: memoryNumber(rawSummary.budget_tokens) ?? 0,
    latency_ms: memoryNumber(rawSummary.latency_ms) ?? 0,
  };
  if (summary.total_used <= 0) return undefined;
  const promptRecord = memoryRecord(record.prompt);
  return {
    classic,
    operational,
    summary,
    filters_applied: memoryRecord(record.filters_applied),
    prompt: promptRecord
      ? {
          formatted: memoryString(promptRecord.formatted),
          truncated: Boolean(promptRecord.truncated),
        }
      : undefined,
  };
}

function memoryRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function memoryArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(memoryRecord).filter((item): item is Record<string, unknown> => Boolean(item)) : [];
}

function memoryString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function memoryStringArray(value: unknown) {
  return Array.isArray(value)
    ? value
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .map((item) => item.trim())
    : undefined;
}

function memoryNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function compactMemoryPath(path: string) {
  const parts = path.split("/").filter(Boolean);
  return parts.length > 3 ? `.../${parts.slice(-3).join("/")}` : path;
}

function memoryScoreLabel(score: number) {
  if (score > 1) return score.toFixed(1);
  return score.toFixed(2);
}

function formatMemoryDate(mtimeMs: number) {
  try {
    return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(mtimeMs));
  } catch {
    return "";
  }
}

function formatMemoryNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}
