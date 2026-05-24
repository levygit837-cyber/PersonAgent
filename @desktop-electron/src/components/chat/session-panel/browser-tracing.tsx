import { Activity, FilePenLine, GitCommit, X } from "lucide-react";
import { cn } from "../../../lib/utils";
import { formatNumber, formatValue, labelize } from "./browser-helpers";
import { ProposalBody } from "./browser-cooperation";
import type { BrowserTracingTab, BrowserVisualEvent } from "./helpers";
import { EmptyList, SectionTitle } from "./shared-ui";

export function BrowserTracingPanel({
  cooperation,
  rawEvents,
  usefulTimeline,
  recentUserEvents,
  recentAgentEvents,
  pendingProposals,
  visualEvents,
  activeTab,
  onTabChange,
  onClose,
  onProposalDecision,
}: {
  cooperation?: { page_state?: Record<string, unknown> };
  rawEvents: Array<Record<string, unknown>>;
  usefulTimeline: Array<Record<string, unknown>>;
  recentUserEvents: Array<Record<string, unknown>>;
  recentAgentEvents: Array<Record<string, unknown>>;
  pendingProposals: Array<Record<string, unknown>>;
  visualEvents: BrowserVisualEvent[];
  activeTab: BrowserTracingTab;
  onTabChange: (tab: BrowserTracingTab) => void;
  onClose: () => void;
  onProposalDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  const tabs: Array<[BrowserTracingTab, string, number]> = [
    ["timeline", "Useful Timeline", usefulTimeline.length],
    ["raw", "Raw Events", rawEvents.length],
    ["state", "Page State", 0],
    ["agent", "Agent Actions", recentAgentEvents.length + visualEvents.length],
    ["proposals", "Proposals", pendingProposals.length],
  ];
  return (
    <aside
      data-browser-tracing-panel="true"
      className="absolute inset-y-3 right-3 z-50 flex w-[min(390px,calc(100%-24px))] flex-col overflow-hidden rounded-lg border border-glass-border/35 bg-background/96 shadow-floating backdrop-blur-xl"
      onClick={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
    >
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-glass-border/25 px-3">
        <Activity className="h-3.5 w-3.5 text-primary" />
        <div className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">Tracing</div>
        <button type="button" className="text-muted-foreground hover:text-foreground" onClick={onClose} aria-label="Close tracing">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-glass-border/20 px-2 py-2">
        {tabs.map(([tab, label, count]) => (
          <button
            key={tab}
            type="button"
            className={cn(
              "shrink-0 rounded-full px-2.5 py-1 text-[11px] transition-colors",
              activeTab === tab ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
            onClick={() => onTabChange(tab)}
          >
            {label}
            {count ? <span className="ml-1 font-mono">{count}</span> : null}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {activeTab === "timeline" ? <TraceList items={usefulTimeline} empty="No useful timeline events yet." /> : null}
        {activeTab === "raw" ? <TraceList items={rawEvents} empty="No raw events persisted yet." raw /> : null}
        {activeTab === "state" ? (
          <TraceJson value={cooperation?.page_state ?? {}} />
        ) : null}
        {activeTab === "agent" ? (
          <div className="space-y-3">
            {visualEvents.length ? <BrowserVisualEventList events={visualEvents} /> : null}
            <TraceList items={recentAgentEvents} empty="No agent browser actions yet." />
          </div>
        ) : null}
        {activeTab === "proposals" ? (
          <div className="space-y-2">
            {pendingProposals.length ? (
              pendingProposals.map((proposal) => (
                <div key={String(proposal.proposal_id ?? proposal.approval_id)} className="rounded-lg border border-glass-border/30 p-2">
                  <ProposalBody proposal={proposal} onDecision={onProposalDecision} />
                  <TraceJson value={proposal} compact />
                </div>
              ))
            ) : (
              <EmptyList text="No pending proposals." />
            )}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export function BrowserVisualEventList({ events }: { events: BrowserVisualEvent[] }) {
  return (
    <div className="space-y-2">
      {events.slice(0, 8).map((event) => (
        <div key={event.id} className="rounded-lg border border-primary/20 bg-primary/[0.04] p-2 text-xs">
          <div className="flex items-center gap-2">
            <TraceRoleBadge role={event.status === "permission_required" ? "system" : "agent"} />
            <span className="min-w-0 flex-1 truncate text-foreground">{event.toolName}</span>
            <span className="rounded-full border border-glass-border/30 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              {event.effect}
            </span>
          </div>
          <div className="mt-1 truncate text-[10px] text-muted-foreground">
            {event.nodeId || event.url || event.pageId || "viewport"}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TraceList({ items, empty, raw = false }: { items: Array<Record<string, unknown>>; empty: string; raw?: boolean }) {
  if (!items.length) return <EmptyList text={empty} />;
  return (
    <div className="space-y-2">
      {items.slice(-80).reverse().map((item, index) => (
        <div key={String(item.event_id ?? item.id ?? index)} className="rounded-lg border border-glass-border/25 p-2 text-xs">
          <div className="flex items-center gap-2">
            <TraceRoleBadge role={String(item.trace_role ?? item.role ?? item.source ?? "browser")} />
            <span className="min-w-0 flex-1 truncate text-foreground">
              {String(item.semantic_label ?? item.label ?? item.kind ?? item.event_type ?? "event")}
            </span>
            {item.sequence !== undefined ? <span className="font-mono text-[10px] text-muted-foreground">#{String(item.sequence)}</span> : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
            {item.kind ? <span>{String(item.kind)}</span> : null}
            {item.importance ? <span>{String(item.importance)}</span> : null}
            {item.trace_effect ? <span>{String(item.trace_effect)}</span> : null}
          </div>
          {raw ? <TraceJson value={item} compact /> : null}
        </div>
      ))}
    </div>
  );
}

export function TraceRoleBadge({ role }: { role: string }) {
  const className =
    role === "agent"
      ? "border-primary/30 bg-primary/12 text-primary"
      : role === "user"
        ? "border-success/30 bg-success/10 text-success"
        : role === "system"
          ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
          : "border-glass-border/35 bg-muted/30 text-muted-foreground";
  return <span className={cn("rounded-full border px-2 py-0.5 font-mono text-[10px]", className)}>{role}</span>;
}

export function TraceJson({ value, compact = false }: { value: unknown; compact?: boolean }) {
  return (
    <pre
      className={cn(
        "mt-2 overflow-auto rounded-md border border-glass-border/25 bg-card/50 p-2 font-mono text-[10px] leading-4 text-muted-foreground",
        compact ? "max-h-28" : "max-h-[55vh]",
      )}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function MetadataBlock({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (entries.length === 0) return null;
  return (
    <dl className="grid gap-x-4 gap-y-2 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 border-b border-glass-border/25 pb-2">
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground/70">{labelize(key)}</dt>
          <dd className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-muted-foreground">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function FilesBlock({ files }: { files: Array<Record<string, unknown>> }) {
  return (
    <div className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<FilePenLine className="h-3.5 w-3.5" />} title="Files" />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {files.map((file, index) => (
          <div key={`${String(file.filename ?? file.path ?? index)}-${index}`} className="py-2">
            <div className="flex min-w-0 items-center gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-foreground">{String(file.filename ?? file.path ?? "file")}</span>
              {file.additions !== undefined ? <span className="font-mono text-success">+{String(file.additions)}</span> : null}
              {file.deletions !== undefined ? <span className="font-mono text-destructive">-{String(file.deletions)}</span> : null}
            </div>
            {typeof file.patch === "string" && file.patch.trim() ? (
              <pre className="mt-2 max-h-44 overflow-auto rounded-lg border border-glass-border/35 bg-background/70 p-2 font-mono text-[11px] leading-5 text-muted-foreground">
                {file.patch}
              </pre>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CommitsBlock({ commits }: { commits: Array<Record<string, unknown>> }) {
  return (
    <div className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<GitCommit className="h-3.5 w-3.5" />} title="Commits" />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {commits.map((commit, index) => (
          <div key={`${String(commit.sha ?? index)}-${index}`} className="py-2 text-xs">
            <div className="truncate font-medium text-foreground">{String(commit.message ?? commit.sha ?? "commit")}</div>
            <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
              {String(commit.sha ?? "")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MetricBand({ items }: { items: Array<[string, number]> }) {
  return (
    <div className="grid grid-cols-4 gap-2">
      {items.map(([label, value]) => (
        <div key={label} className="border-b border-glass-border/25 pb-2">
          <div className="font-mono text-sm text-foreground">{formatNumber(value)}</div>
          <div className="truncate text-[10px] text-muted-foreground">{label}</div>
        </div>
      ))}
    </div>
  );
}
