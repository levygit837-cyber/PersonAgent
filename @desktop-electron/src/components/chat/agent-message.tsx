import { memo, useState, type CSSProperties, type ReactElement } from "react";
import { AlertCircle, Brain, Check, ChevronRight, Database, GitBranchPlus, Hammer, Loader2, MessageSquareText, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import type {
  ChatMessageUi,
  MemoryTrace,
  MemoryTraceClassicItem,
  MemoryTraceOperationalItem,
  TeamAgentLogUi,
  TeamAgentTraceUi,
  TeamBlackboardTraceUi,
  TeamClaimTraceUi,
  TeamCompactStatus,
  TeamRunUi,
  TeamToolTraceUi,
  TeamTraceEventUi,
} from "../../types/chat";
import { useChatStore } from "../../stores/chat-store";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
import { ReasoningBlock } from "./reasoning-block";
import {
  AgentMessageContent,
  ChatExecutionStatus,
  MarkdownContent,
  compactToolKindFor,
} from "./agent-message/content-blocks";

const TEAM_CARD_ARRIVAL_STAGGER_MS = 120;
type MemoryTraceTab = "used" | "filters" | "prompt";

export const AgentMessage = memo(function AgentMessage({ message }: { message: ChatMessageUi }) {
  const memoryTrace = memoryTraceFromMetadata(message.metadata?.memory_trace);
  const [memoryInspectorOpen, setMemoryInspectorOpen] = useState(false);
  const [memoryTraceTab, setMemoryTraceTab] = useState<MemoryTraceTab>("used");
  const setReasoningBlockExpanded = useChatStore((state) => state.setReasoningBlockExpanded);

  if (!message.isStreaming && !hasRenderableProgress(message)) {
    return null;
  }

  const hasVisibleAnswerContent = hasVisibleContent(message);
  const hasLegacyThinking = message.parts.length === 0 && (message.reasoning || message.isReasoningStreaming);
  const orphanReasoningBlocks =
    message.parts.length > 0
      ? message.reasoningBlocks.filter(
          (block) => !message.parts.some((part) => part.reasoningBlockId === block.id),
        )
      : [];
  const hasOrphanReasoningFallback =
    orphanReasoningBlocks.length === 0 &&
    message.parts.length > 0 &&
    message.reasoning.trim().length > 0 &&
    !message.parts.some((part) => part.kind === "reasoning");
  const showExecutionStatus = message.isStreaming && !hasRenderableProgress(message);
  const showActions = !message.isStreaming && hasVisibleAnswerContent;

  return (
    <article className="group/agent-message mb-7 min-w-0 max-w-full">
      {showExecutionStatus ? <ChatExecutionStatus /> : null}
      {hasLegacyThinking ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
      {orphanReasoningBlocks.map((block) => (
        <ReasoningBlock
          key={block.id}
          reasoning={block.content}
          isStreaming={block.isStreaming}
          autoCollapse={hasVisibleAnswerContent}
          userExpanded={block.userExpanded}
          onToggleExpanded={() => setReasoningBlockExpanded(message.id, block.id, !block.userExpanded)}
        />
      ))}
      {hasOrphanReasoningFallback ? (
        <ReasoningBlock
          reasoning={message.reasoning}
          isStreaming={message.isReasoningStreaming}
          autoCollapse={hasVisibleAnswerContent}
        />
      ) : null}
      {message.teamRun ? <TeamModeCompactTrace run={message.teamRun} /> : message.teamEvents.length > 0 ? <TeamTrace events={message.teamEvents} /> : null}
      <AgentMessageContent message={message} hasVisibleAnswerContent={hasVisibleAnswerContent} />
      {memoryTrace && memoryInspectorOpen ? (
        <MemoryTraceInspector trace={memoryTrace} activeTab={memoryTraceTab} onTabChange={setMemoryTraceTab} />
      ) : null}
      {showActions ? (
        <AgentMessageActions
          message={message}
          memoryTrace={memoryTrace}
          memoryInspectorOpen={memoryInspectorOpen}
          onToggleMemoryInspector={() => setMemoryInspectorOpen((value) => !value)}
        />
      ) : null}
    </article>
  );
});

function AgentMessageActions({
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

function MemoryTraceInspector({
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

function hasRenderableProgress(message: ChatMessageUi) {
  if (message.content.trim().length > 0) return true;
  if (message.reasoning.trim().length > 0 || message.isReasoningStreaming) return true;
  if (message.reasoningBlocks.some((block) => block.content.trim().length > 0 || block.isStreaming)) return true;
  if (message.toolBlocks.length > 0) return true;
  if (message.teamRun) return true;
  if (message.teamEvents.length > 0) return true;
  return message.parts.some(
    (part) => (part.kind === "content" && Boolean(part.content?.trim())) || part.kind === "image",
  );
}

function hasVisibleContent(message: ChatMessageUi) {
  if (message.content.trim().length > 0) return true;
  return message.parts.some(
    (part) => (part.kind === "content" && Boolean(part.content?.trim())) || part.kind === "image",
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

function memoryTraceFromMetadata(value: unknown): MemoryTrace | undefined {
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

const TeamModeCompactTrace = memo(function TeamModeCompactTrace({ run }: { run: TeamRunUi }) {
  return (
    <section className="mb-4 space-y-2" aria-label="Team Mode execution trace">
      {run.agents.length > 0 ? (
        <div className="space-y-2" aria-label="Agent lanes">
          {run.agents.map((agent, index) => (
            <TeamAgentCard key={agent.agentId} agent={agent} sequenceIndex={index} />
          ))}
        </div>
      ) : null}
      <TeamBlackboardCard blackboard={run.blackboard} runStatus={run.status} sequenceIndex={run.agents.length} />
    </section>
  );
});

const TeamAgentCard = memo(function TeamAgentCard({
  agent,
  sequenceIndex,
}: {
  agent: TeamAgentTraceUi;
  sequenceIndex: number;
}) {
  const [open, setOpen] = useState(false);
  const status = effectiveAgentStatus(agent);
  const summary = compactAgentSummary(agent);
  const previewLogs = visibleAgentLogs(agent).slice(-2);
  return (
    <section
      className="personagent-team-card-arrival overflow-hidden rounded-lg border border-glass-border/45 bg-card/45 shadow-soft"
      style={teamCardArrivalStyle(sequenceIndex)}
    >
      <button
        type="button"
        className="flex w-full min-w-0 cursor-pointer items-center justify-between gap-2 px-2.5 py-2 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-glass-border/50 bg-background/70 text-[11px] font-bold text-foreground">
            {agentInitial(agent)}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold text-foreground">{agent.agentName}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{agent.agentRole || agent.focus || agent.phase || "Agent"}</span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <StatusDot status={status} />
          <ChevronRight className={open ? "h-3.5 w-3.5 rotate-90 text-muted-foreground transition-transform" : "h-3.5 w-3.5 text-muted-foreground transition-transform"} aria-hidden="true" />
        </span>
      </button>
      <div className="border-t border-glass-border/25 px-2.5 py-1.5">
        {previewLogs.length > 0 ? (
          <div className="space-y-1">
            {previewLogs.map((log) => (
              <AgentLogPreview key={log.id} log={log} revealThinkingContent={!isPrivateThinkingLog(agent, log)} />
            ))}
          </div>
        ) : (
          <div className="truncate font-mono text-[11px] text-muted-foreground">{summary ?? agent.phase ?? "waiting"}</div>
        )}
      </div>
      {open ? (
        <div className="border-t border-glass-border/35 px-2.5 py-2.5">
          <AgentLogTimeline agent={agent} running={status === "running"} />
          {agent.error ? <div className="rounded-md border border-destructive/25 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">{agent.error}</div> : null}
        </div>
      ) : null}
    </section>
  );
});

const TeamBlackboardCard = memo(function TeamBlackboardCard({
  blackboard,
  runStatus,
  sequenceIndex,
}: {
  blackboard: TeamBlackboardTraceUi;
  runStatus: TeamCompactStatus;
  sequenceIndex: number;
}) {
  const [open, setOpen] = useState(false);
  const status = runStatus === "running" ? "running" : blackboard.status;
  const claims = blackboard.claims.slice(-6).reverse();
  const coverage = blackboard.coverage.slice(0, 4);
  return (
    <section
      className="personagent-team-card-arrival overflow-hidden rounded-lg border border-glass-border/50 bg-card/40 shadow-soft"
      style={teamCardArrivalStyle(sequenceIndex)}
      aria-label="Blackboard compact snapshot"
    >
      <button
        type="button"
        className="flex w-full min-w-0 cursor-pointer items-center justify-between gap-3 px-2.5 py-2.5 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <StatusDot status={status} />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-semibold text-foreground">Blackboard compact snapshot</span>
            <span className="block truncate font-mono text-[11px] text-muted-foreground">claims, evidence, risks, tools, coverage</span>
          </span>
        </span>
        <span className="flex shrink-0 flex-wrap justify-end gap-1.5 font-mono text-[10px] text-muted-foreground">
          <TracePill label="actual phase" value={blackboard.actualPhase ?? "starting"} />
          <TracePill label="claims" value={String(blackboard.claims.length)} />
          {blackboard.coherencyScore != null ? <TracePill label="coherency" value={blackboard.coherencyScore.toFixed(2)} /> : null}
          <span className="rounded-full border border-glass-border/35 px-2 py-0.5 text-primary">show</span>
        </span>
      </button>
      {open ? (
        <div className="max-h-80 overflow-y-auto border-t border-glass-border/35 px-2.5 py-2.5">
          <div className="grid gap-2 min-[720px]:grid-cols-[minmax(0,1.2fr)_minmax(220px,0.8fr)]">
            <div className="space-y-2">
              {claims.length > 0 ? (
                claims.map((claim) => <BlackboardClaim key={claim.id} claim={claim} />)
              ) : (
                <div className="rounded-md border border-glass-border/35 bg-background/35 px-2 py-1.5 text-xs text-muted-foreground">No claims yet.</div>
              )}
            </div>
            <div className="space-y-2">
              <BlackboardFact title="Actual phase" value={blackboard.actualPhase ?? "starting"} detail={phaseDetail(blackboard.actualPhase)} />
              {blackboard.coverageTotal != null || blackboard.coverageComplete != null ? (
                <BlackboardFact
                  title="Coverage"
                  value={`${blackboard.coverageComplete ?? 0}/${blackboard.coverageTotal ?? blackboard.coverage.length}`}
                  detail={coverageDetail(coverage)}
                />
              ) : null}
              <BlackboardFact title="Next action" value={blackboard.nextAction ?? "Collect deltas"} detail={nextActionDetail(blackboard)} />
              {blackboard.tools.length > 0 ? <BlackboardTools tools={blackboard.tools} /> : null}
              {blackboard.blockers.length > 0 ? <BlackboardTextList title="Blockers" items={blackboard.blockers.slice(-3)} /> : null}
              {blackboard.decisions.length > 0 ? <BlackboardTextList title="Decisions" items={blackboard.decisions.slice(-3)} /> : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
});

function teamCardArrivalStyle(sequenceIndex: number) {
  return {
    "--personagent-team-card-delay": `${sequenceIndex * TEAM_CARD_ARRIVAL_STAGGER_MS}ms`,
  } as CSSProperties & Record<"--personagent-team-card-delay", string>;
}

function AgentLogTimeline({ agent, running }: { agent: TeamAgentTraceUi; running: boolean }) {
  const logs = visibleAgentLogs(agent);
  return (
    <div className="max-h-64 overflow-y-auto pr-1" aria-label={`${agent.agentName} events`}>
      <div className="space-y-1.5">
        {logs.length > 0 ? (
          logs.map((log) => <AgentLogRow key={log.id} log={log} running={running && log.kind === "thinking"} />)
        ) : (
          <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
            Waiting for events.
          </div>
        )}
        {agent.tools.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
              <Hammer className="h-3 w-3" aria-hidden="true" />
              Tools
            </div>
            {agent.tools.slice(-4).map((tool) => <AgentToolRow key={tool.id} tool={tool} />)}
          </div>
        ) : null}
        {agent.claims.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
              <Brain className="h-3 w-3" aria-hidden="true" />
              Claims
            </div>
            {agent.claims.slice(-4).map((claim) => (
              <div key={claim.id} className="truncate rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5 text-[11px] text-muted-foreground">
                <span className="font-mono uppercase text-primary">{claim.type}</span> {claim.text}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AgentLogPreview({
  log,
  revealThinkingContent,
}: {
  log: TeamAgentLogUi;
  revealThinkingContent: boolean;
}) {
  const preview = agentLogPreview(log, revealThinkingContent);
  return (
    <div className="flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
      <span className="shrink-0 uppercase text-primary">{agentLogKindLabel(log.kind)}</span>
      <span className="truncate">{preview}</span>
    </div>
  );
}

function AgentLogRow({ log, running }: { log: TeamAgentLogUi; running: boolean }) {
  const isThinking = log.kind === "thinking";
  return (
    <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5">
      <div className="mb-1 flex min-w-0 items-center justify-between gap-2 font-mono text-[10px] uppercase text-primary">
        <span className="flex min-w-0 items-center gap-1.5">
          {agentLogIcon(log.kind)}
          <span className="truncate">{agentLogKindLabel(log.kind)}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
          {log.phase ? <span className="max-w-24 truncate">{formatPhaseLabel(log.phase)}</span> : null}
          {running ? <StatusDot status="running" /> : log.status ? <StatusDot status={log.status} /> : null}
        </span>
      </div>
      {log.content ? (
        <div
          className={
            isThinking
              ? "max-h-32 overflow-y-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-muted-foreground"
              : "max-h-36 overflow-y-auto text-[12px] leading-5 text-muted-foreground"
          }
        >
          {isThinking ? (
            log.content
          ) : (
            <MarkdownContent content={log.content} />
          )}
        </div>
      ) : (
        <div className="truncate text-[12px] text-muted-foreground">{agentLogPreview(log)}</div>
      )}
    </div>
  );
}

function agentLogIcon(kind: TeamAgentLogUi["kind"]) {
  if (kind === "response") return <MessageSquareText className="h-3 w-3" aria-hidden="true" />;
  if (kind === "tool") return <Hammer className="h-3 w-3" aria-hidden="true" />;
  if (kind === "claim") return <Brain className="h-3 w-3" aria-hidden="true" />;
  return null;
}

function agentLogKindLabel(kind: TeamAgentLogUi["kind"]) {
  if (kind === "thinking") return "thinking";
  if (kind === "response") return "response";
  if (kind === "tool") return "tool";
  if (kind === "claim") return "claim";
  if (kind === "error") return "error";
  return "status";
}

function visibleAgentLogs(agent: TeamAgentTraceUi): TeamAgentLogUi[] {
  const logs = agent.logs.filter(isVisibleAgentLog);
  const hasTextLog = logs.some((log) => log.kind === "thinking" || log.kind === "response");
  const fallbackLogs = hasTextLog ? [] : fallbackAgentLogs(agent);
  return logs.length > 0 || fallbackLogs.length > 0 ? [...logs, ...fallbackLogs] : [];
}

function isVisibleAgentLog(log: TeamAgentLogUi) {
  if (log.kind === "thinking" || log.kind === "response") return Boolean(log.content?.trim());
  return Boolean(log.content?.trim() || log.title.trim());
}

function agentLogPreview(log: TeamAgentLogUi, revealThinkingContent = true) {
  if (log.kind === "thinking" && !revealThinkingContent) {
    return log.phase ? formatPhaseLabel(log.phase) : "working";
  }
  return (log.content?.trim() || log.title).replace(/\s+/g, " ");
}

function isPrivateThinkingLog(agent: TeamAgentTraceUi, log: TeamAgentLogUi) {
  if (log.kind !== "thinking") return false;
  const privateThinking = agent.thinking.trim();
  return Boolean(privateThinking && log.content?.trim() === privateThinking);
}

function formatPhaseLabel(phase: string) {
  return phase.replace(/_/g, " ");
}

function fallbackAgentLogs(agent: TeamAgentTraceUi): TeamAgentLogUi[] {
  const logs: TeamAgentLogUi[] = [];
  if (agent.thinking.trim()) {
    logs.push({
      id: `${agent.agentId}-fallback-thinking`,
      kind: "thinking",
      title: "Thinking",
      content: agent.thinking,
      status: agent.status,
      phase: agent.phase,
      round: agent.round,
    });
  }
  if (agent.output.trim() || agent.digest) {
    logs.push({
      id: `${agent.agentId}-fallback-response`,
      kind: "response",
      title: "Output",
      content: agent.output || agent.digest,
      status: agent.status,
      phase: agent.phase,
      round: agent.round,
    });
  }
  return logs;
}

function AgentToolRow({ tool }: { tool: TeamToolTraceUi }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-glass-border/30 bg-background/30 px-2 py-1.5">
      <button type="button" className="flex w-full cursor-pointer items-center justify-between gap-2 text-left" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">{tool.summary ?? tool.title}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          <StatusDot status={tool.status} />
          <span className="font-mono text-[10px] text-primary">output</span>
        </span>
      </button>
      {open ? (
        <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-md border border-glass-border/25 bg-card/70 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
          {formatToolPayload(tool)}
        </pre>
      ) : null}
    </div>
  );
}

function BlackboardClaim({ claim }: { claim: TeamClaimTraceUi }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[10px] uppercase">
        <span className="text-primary">{claim.type}</span>
        <span className="truncate text-muted-foreground">{claim.agentName ?? claim.agentId ?? "Blackboard"}</span>
      </div>
      <p className="line-clamp-3 text-[12px] leading-5 text-muted-foreground">{claim.text}</p>
    </div>
  );
}

function BlackboardFact({ title, value, detail }: { title: string; value: string; detail?: string }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[10px] uppercase">
        <span className="text-primary">{title}</span>
        <span className="truncate text-muted-foreground">{value}</span>
      </div>
      {detail ? <p className="text-[12px] leading-5 text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

function BlackboardTools({ tools }: { tools: TeamToolTraceUi[] }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase text-primary">
        <Database className="h-3 w-3" aria-hidden="true" />
        Tool audit
      </div>
      <div className="space-y-1">
        {tools.slice(-3).map((tool) => (
          <div key={tool.id} className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="truncate">{tool.summary ?? tool.title}</span>
            <StatusDot status={tool.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

function BlackboardTextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-md border border-glass-border/35 bg-background/35 px-2.5 py-2">
      <div className="mb-1 font-mono text-[10px] uppercase text-primary">{title}</div>
      <ul className="space-y-1 text-[12px] leading-5 text-muted-foreground">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className="line-clamp-2">{item}</li>
        ))}
      </ul>
    </div>
  );
}

function TracePill({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded-full border border-glass-border/35 px-2 py-0.5">
      {label} <strong className="font-semibold text-foreground">{value}</strong>
    </span>
  );
}

function StatusDot({ status }: { status: TeamCompactStatus }) {
  if (status === "running" || status === "blocked") {
    return (
      <span className="relative inline-flex h-2 w-2 shrink-0" aria-label={status}>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/45" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
    );
  }
  const color =
    status === "completed" ? "bg-success" : status === "failed" ? "bg-destructive" : status === "cancelled" ? "bg-muted-foreground" : "bg-muted-foreground/70";
  return <span className={`inline-flex h-2 w-2 shrink-0 rounded-full ${color}`} aria-label={status} />;
}

function effectiveAgentStatus(agent: TeamAgentTraceUi): TeamCompactStatus {
  if (agent.status === "failed" || agent.status === "cancelled") return agent.status;
  if (agent.tools.some((tool) => tool.status === "running" || tool.status === "blocked")) return "running";
  return agent.status;
}

function compactAgentSummary(agent: TeamAgentTraceUi) {
  if (agent.error) return agent.error;
  if (agent.digest) return agent.digest;
  if (agent.output.trim()) return agent.output.trim().split(/\s+/).slice(0, 18).join(" ");
  if (agent.thinking.trim()) return "Thinking";
  if (agent.tools.length > 0) return agent.tools[agent.tools.length - 1]?.summary;
  return agent.phase;
}

function agentInitial(agent: TeamAgentTraceUi) {
  if (agent.isCoordinator) return "C";
  return (agent.agentName || agent.agentId || "A").trim().charAt(0).toUpperCase();
}

function phaseDetail(phase?: string) {
  if (!phase) return undefined;
  if (phase.includes("independent")) return "Agents are producing isolated first-pass findings.";
  if (phase.includes("debate")) return "Agents are reviewing the compact Blackboard snapshot.";
  if (phase.includes("vote")) return "Agents are casting compact ballots on blockers and consensus.";
  if (phase.includes("coordinator")) return "Coordinator is preparing the final synthesis.";
  return "Current Team Mode execution phase.";
}

function coverageDetail(coverage: Array<{ title: string; status?: string }>) {
  if (coverage.length === 0) return undefined;
  return coverage.map((item) => `${item.title}: ${item.status ?? "open"}`).join(" | ");
}

function nextActionDetail(blackboard: TeamBlackboardTraceUi) {
  if (blackboard.blockers.length > 0) return blackboard.blockers[blackboard.blockers.length - 1];
  if (blackboard.lowCoherencyCount && blackboard.lowCoherencyCount > 0) return `${blackboard.lowCoherencyCount} low coherency claim${blackboard.lowCoherencyCount === 1 ? "" : "s"} need review.`;
  return "Continue from the latest Blackboard delta.";
}

function formatToolPayload(tool: TeamToolTraceUi) {
  const payload = {
    phase: tool.phase,
    calls: tool.calls,
    results: tool.results,
    proposals: tool.proposals,
  };
  return JSON.stringify(payload, null, 2);
}

const TeamTrace = memo(function TeamTrace({ events }: { events: TeamTraceEventUi[] }) {
  return (
    <div className="mb-4 space-y-2 border-l border-glass-border/25 pl-3">
      {events.map((event) => (
        <TeamTraceEvent key={event.id} event={event} />
      ))}
    </div>
  );
});

const TeamTraceEvent = memo(function TeamTraceEvent({ event }: { event: TeamTraceEventUi }) {
  const content = event.content?.trimEnd();
  const isRunning = event.status === "running";
  return (
    <div className="text-sm">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className={teamStatusClass(event.status)}>{teamStatusLabel(event)}</span>
        <span className="font-medium text-foreground">{event.title}</span>
        {event.detail ? <span className="font-mono text-[11px] text-muted-foreground">{event.detail}</span> : null}
      </div>
      {content ? (
        <div className="mt-1 max-w-none text-[13px] leading-6 text-muted-foreground">
          {isRunning ? (
            <div className="whitespace-pre-wrap break-words">{content}</div>
          ) : (
            <MarkdownContent content={content} />
          )}
        </div>
      ) : null}
    </div>
  );
});

function teamStatusLabel(event: TeamTraceEventUi) {
  if (event.kind === "round") return "Round";
  if (event.kind === "vote") return event.status === "approved" ? "Approve" : event.status === "rejected" ? "Block" : "Vote";
  if (event.kind === "consensus") return "Consensus";
  if (event.kind === "blackboard") return "Board";
  if (event.kind === "tool") return "Tool";
  if (event.kind === "debate") return "Debate";
  if (event.kind === "coordinator") {
    return event.title.toLowerCase().includes("planning") || event.status !== "completed" ? "Coord" : "Final";
  }
  if (event.kind === "failed") return "Failed";
  if (event.kind === "cancelled") return "Stopped";
  if (event.kind === "turn") return event.status === "completed" ? "Done" : "Turn";
  return "Team";
}

function teamStatusClass(status?: TeamTraceEventUi["status"]) {
  const base = "font-mono text-[10px] uppercase tracking-[0.12em]";
  if (status === "approved" || status === "completed") return `${base} text-success`;
  if (status === "rejected" || status === "failed") return `${base} text-destructive`;
  if (status === "cancelled") return `${base} text-muted-foreground`;
  return `${base} text-warning`;
}


export { MarkdownContent, compactToolKindFor } from "./agent-message/content-blocks";
