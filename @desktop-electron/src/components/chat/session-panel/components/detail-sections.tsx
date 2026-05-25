import type { ReactNode } from "react";
import {
  Activity,
  Database,
  ExternalLink,
  FilePenLine,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Loader2,
  Upload,
} from "lucide-react";
import {
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserViewport,
} from "../../../../api/client";
import { cn } from "../../../../lib/utils";
import type {
  ChangedFile,
  ProjectItem,
  SessionMemorySummary,
  SessionMemoryTopItem,
  SessionPanelSnapshot,
  SessionSource,
  SessionUsage,
  SessionUsageMetric,
} from "../../../../types/chat";
import type { SessionDetailView } from "../../session-detail-window";
import { formatNumber } from "../helpers/browser-helpers";
import { BrowserTabContent } from "./browser-tab-content";
import {
  CommitsBlock,
  FilesBlock,
  MetadataBlock,
  MetricBand,
} from "./browser-tracing";
import type {
  BrowserTab,
  BrowserState,
  BrowserElementMetadata,
  BrowserTextSelectionMetadata,
  BrowserVisualEvent,
  BrowserToolEvent,
} from "../helpers";
import {
  createEmptyBrowserState,
  isBrowserTab,
} from "../helpers";
import { EmptyList, EmptyPanel, SectionTitle } from "./shared-ui";

export function SummaryContent({
  snapshot,
  usage,
  loadingDetailId,
  onOpenDetail,
  onOpenProjectDetail,
}: {
  snapshot?: SessionPanelSnapshot;
  usage: SessionUsage;
  loadingDetailId: string | null;
  onOpenDetail: (detail: SessionDetailView) => void;
  onOpenProjectDetail: (item: ProjectItem) => void;
}) {
  const project = snapshot?.project;
  return (
    <div className="space-y-5">
      <MetricBand
        items={[
          ["Files", snapshot?.changed_files.length ?? 0],
          ["Sources", snapshot?.sources.length ?? 0],
          ["Tools", usage.tool_calls.value],
          ["Plans", usage.plans_created.value],
        ]}
      />
      <UsageSection usage={usage} />
      <MemorySection memory={snapshot?.memory} onOpenDetail={onOpenDetail} />
      <FilesSection files={snapshot?.changed_files ?? []} onOpenDetail={onOpenDetail} />
      <SourcesSection sources={snapshot?.sources ?? []} onOpenDetail={onOpenDetail} />
      <ProjectSection
        project={project}
        loadingDetailId={loadingDetailId}
        onOpenProjectDetail={onOpenProjectDetail}
      />
    </div>
  );
}

function UsageSection({ usage }: { usage: SessionUsage }) {
  const rows: Array<[string, SessionUsageMetric]> = [
    ["Context Tokens", usage.context_tokens],
    ["Agent Output Tokens", usage.agent_output_tokens],
    ["Thinking Output Tokens", usage.thinking_output_tokens],
    ["Tool Calls", usage.tool_calls],
    ["Skills used count", usage.skills_used_count],
    ["MCP calls count", usage.mcp_calls_count],
    ["Plans Created", usage.plans_created],
    ["Todo's Created", usage.todos_created],
    ["SubAgents Used", usage.subagents_used],
  ];
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<Activity className="h-3.5 w-3.5" />} title="Agent Usage" />
      <div className="mt-2 divide-y divide-glass-border/25">
        {rows.map(([label, metric]) => (
          <div key={label} className="flex items-center gap-3 py-2 text-xs">
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{label}</span>
            <span className="font-mono text-foreground">{formatNumber(metric.value)}</span>
            {metric.estimated ? <span className="font-mono text-[10px] text-warning">estimated</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function MemorySection({
  memory,
  onOpenDetail,
}: {
  memory?: SessionMemorySummary;
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  const hasMemory = Boolean(memory && (memory.total_recalls > 0 || memory.rag_used > 0 || memory.classic_used > 0));
  const metrics: Array<[string, string]> = [
    ["Recalls", formatNumber(memory?.total_recalls ?? 0)],
    ["RAG", formatNumber(memory?.rag_used ?? 0)],
    ["Classic", formatNumber(memory?.classic_used ?? 0)],
    ["Omitted", formatNumber(memory?.omitted ?? 0)],
    ["Avg latency", memory?.avg_latency_ms ? `${Math.round(memory.avg_latency_ms)}ms` : "0ms"],
    ["Budget", `${formatNumber(memory?.budget_used ?? 0)} / ${formatNumber(memory?.budget_tokens ?? 0)}`],
  ];

  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<Database className="h-3.5 w-3.5" />} title="Memory" />
      {!hasMemory ? <EmptyList text="No memory recall in this session." /> : null}
      {hasMemory ? (
        <div className="mt-2 space-y-3">
          <div className="grid grid-cols-2 gap-2 min-[780px]:grid-cols-3">
            {metrics.map(([label, value]) => (
              <div key={label} className="border-b border-glass-border/25 pb-1.5">
                <div className="truncate font-mono text-xs text-foreground">{value}</div>
                <div className="truncate text-[10px] text-muted-foreground">{label}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Most used memories</div>
            {memory?.most_used.length ? (
              <div className="mt-1 divide-y divide-glass-border/25">
                {memory.most_used.map((item) => (
                  <MemoryTopItemRow key={item.id} item={item} onOpenDetail={onOpenDetail} />
                ))}
              </div>
            ) : (
              <EmptyList text="No repeated memories yet." />
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function MemoryTopItemRow({
  item,
  onOpenDetail,
}: {
  item: SessionMemoryTopItem;
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  const evidence = item.evidence.filter(Boolean).join("\n\n");
  return (
    <button
      type="button"
      className="flex w-full min-w-0 items-start gap-2 py-2 text-left transition-colors hover:bg-accent/60"
      onClick={() =>
        onOpenDetail({
          type: "memory",
          id: item.id,
          title: item.label,
          subtitle: `${item.source} memory · ${formatNumber(item.count)} use${item.count === 1 ? "" : "s"}`,
          metadata: {
            source: item.source,
            count: item.count,
            paths: item.paths,
            messages: item.messages,
          },
          patch: evidence || undefined,
        })
      }
    >
      <Database className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs text-foreground">{item.label}</span>
        <span className="block truncate text-[11px] text-muted-foreground">{item.paths[0] || item.source}</span>
      </span>
      <span className="shrink-0 rounded-full border border-glass-border/30 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
        {formatNumber(item.count)}
      </span>
    </button>
  );
}

function FilesSection({
  files,
  onOpenDetail,
}: {
  files: ChangedFile[];
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<FilePenLine className="h-3.5 w-3.5" />} title="Changed Files" />
      {files.length === 0 ? <EmptyList text="No changed files in this session." /> : null}
      <div className="mt-2 divide-y divide-glass-border/25">
        {files.map((file) => (
          <button
            key={file.id}
            type="button"
            className="flex w-full min-w-0 items-center gap-2 py-2 text-left transition-colors hover:bg-accent/60"
            onClick={() =>
              onOpenDetail({
                type: "file",
                id: file.id,
                title: file.display_path,
                subtitle: file.source,
                metadata: {
                  path: file.path,
                  status: file.status,
                  source: file.source,
                  additions: file.added_lines,
                  deletions: file.removed_lines,
                },
                patch: file.diff || file.content,
              })
            }
          >
            <span className="min-w-0 flex-1 truncate text-xs text-foreground">{file.display_path}</span>
            <span className="font-mono text-[11px] text-success">+{file.added_lines}</span>
            <span className="font-mono text-[11px] text-destructive">-{file.removed_lines}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function SourcesSection({
  sources,
  onOpenDetail,
}: {
  sources: SessionSource[];
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<ExternalLink className="h-3.5 w-3.5" />} title="Sources" />
      {sources.length === 0 ? <EmptyList text="No sources registered." /> : null}
      <div className="mt-2 divide-y divide-glass-border/25">
        {sources.map((source) => (
          <button
            key={source.id}
            type="button"
            className="flex w-full min-w-0 items-start gap-2 py-2 text-left transition-colors hover:bg-accent/60"
            onClick={() =>
              onOpenDetail({
                type: "source",
                id: source.id,
                title: source.title,
                subtitle: source.domain,
                url: source.url,
                metadata: {
                  url: source.url,
                  domain: source.domain,
                  tool: source.tool_name,
                  description: source.description,
                },
              })
            }
          >
            <img src={source.favicon_url} alt="" className="mt-0.5 h-4 w-4 shrink-0 rounded-sm" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs text-foreground">{source.title}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{source.description || source.url}</span>
            </span>
            <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </div>
    </section>
  );
}

function ProjectSection({
  project,
  loadingDetailId,
  onOpenProjectDetail,
}: {
  project?: SessionPanelSnapshot["project"];
  loadingDetailId: string | null;
  onOpenProjectDetail: (item: ProjectItem) => void;
}) {
  if (!project) {
    return (
      <section className="border-t border-glass-border/25 pt-3">
        <SectionTitle icon={<GitBranch className="h-3.5 w-3.5" />} title="Project Details" />
        <EmptyList text="Project unavailable." />
      </section>
    );
  }
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<GitBranch className="h-3.5 w-3.5" />} title="Project Details" />
      <div className="mt-2 space-y-4">
        <div className="space-y-1 text-xs text-muted-foreground">
          <div className="truncate">{project.repo?.name_with_owner || "Repository not detected"}</div>
          <div className="truncate">Default branch: {project.repo?.default_branch || "N/A"}</div>
        </div>
        <ProjectGroup icon={<GitPullRequest className="h-3.5 w-3.5" />} title="Last PR's" items={project.prs} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<GitBranch className="h-3.5 w-3.5" />} title="Branches" items={project.branches} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<Upload className="h-3.5 w-3.5" />} title="Last Pushs" items={project.pushes} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        <ProjectGroup icon={<GitCommit className="h-3.5 w-3.5" />} title="Last Commits" items={project.commits} loadingDetailId={loadingDetailId} onOpen={onOpenProjectDetail} />
        {project.errors.length ? (
          <div className="border-t border-warning/30 pt-2 text-[11px] leading-4 text-warning">
            {project.errors[0]}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ProjectGroup({
  icon,
  title,
  items,
  loadingDetailId,
  onOpen,
}: {
  icon: ReactNode;
  title: string;
  items: ProjectItem[];
  loadingDetailId: string | null;
  onOpen: (item: ProjectItem) => void;
}) {
  return (
    <div>
      <SectionTitle icon={icon} title={title} />
      <div className="mt-2 divide-y divide-glass-border/25 rounded-xl border border-glass-border/35">
        {items.length === 0 ? <div className="py-2 text-[11px] text-muted-foreground">No data.</div> : null}
        {items.map((item) => {
          const loading = loadingDetailId === `${item.type}:${item.id}`;
          return (
            <button
              key={`${item.type}:${item.id}`}
              type="button"
              className={cn(
                "group flex w-full min-w-0 items-center gap-2 py-2 text-left transition-colors hover:bg-accent/70",
                item.active && "text-primary",
              )}
              onClick={() => onOpen(item)}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-foreground group-hover:text-primary">{item.title}</span>
                {item.subtitle ? <span className="block truncate text-[11px] text-muted-foreground">{item.subtitle}</span> : null}
              </span>
              {loading ? <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DetailTabContent({
  tab,
  browserToolEvent,
  browserVisualEvents,
  onBrowserDraftChange,
  onBrowserLoad,
  onBrowserNavigate,
  onBrowserBack,
  onBrowserForward,
  onBrowserRefresh,
  onBrowserClick,
  onBrowserKey,
  onBrowserScroll,
  onBrowserModeChange,
  onBrowserElementSelect,
  onBrowserTextSelect,
  onBrowserAnnotationDraftChange,
  onBrowserAnnotationSave,
  onBrowserElementActivate,
  onBrowserCooperationModeChange,
  onBrowserEvents,
  onBrowserProposalDecision,
  canPersistBrowserWorkspace,
}: {
  tab: BrowserTab;
  browserToolEvent?: BrowserToolEvent;
  browserVisualEvents?: BrowserVisualEvent[];
  onBrowserDraftChange: (value: string) => void;
  onBrowserLoad: (viewport: SessionBrowserViewport) => void;
  onBrowserNavigate: (value: string, viewport: SessionBrowserViewport) => void;
  onBrowserBack: (viewport: SessionBrowserViewport) => void;
  onBrowserForward: (viewport: SessionBrowserViewport) => void;
  onBrowserRefresh: (viewport: SessionBrowserViewport) => void;
  onBrowserClick: (input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" }) => void;
  onBrowserKey: (input: SessionBrowserViewport & { text?: string; key?: string }) => void;
  onBrowserScroll: (input: SessionBrowserViewport & { delta_x: number; delta_y: number }) => void;
  onBrowserModeChange: (mode: BrowserState["mode"]) => void;
  onBrowserElementSelect: (nodeId: string, element?: BrowserElementMetadata) => void;
  onBrowserTextSelect: (selection: BrowserTextSelectionMetadata) => void;
  onBrowserAnnotationDraftChange: (value: string) => void;
  onBrowserAnnotationSave: () => void;
  onBrowserElementActivate: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  onBrowserCooperationModeChange: (mode: SessionBrowserCooperationMode | "off") => void;
  onBrowserEvents: (events: SessionBrowserCooperationEvent[]) => void;
  onBrowserProposalDecision: (
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => void;
  canPersistBrowserWorkspace: boolean;
}) {
  if (isBrowserTab(tab)) {
    return (
      <BrowserTabContent
        browser={tab.browser ?? createEmptyBrowserState(tab.id)}
        browserToolEvent={browserToolEvent}
        browserVisualEvents={browserVisualEvents}
        onDraftChange={onBrowserDraftChange}
        onLoadView={onBrowserLoad}
        onNavigate={onBrowserNavigate}
        onBack={onBrowserBack}
        onForward={onBrowserForward}
        onRefresh={onBrowserRefresh}
        onBrowserClick={onBrowserClick}
        onBrowserKey={onBrowserKey}
        onBrowserScroll={onBrowserScroll}
        onModeChange={onBrowserModeChange}
        onElementSelect={onBrowserElementSelect}
        onTextSelect={onBrowserTextSelect}
        onAnnotationDraftChange={onBrowserAnnotationDraftChange}
        onAnnotationSave={onBrowserAnnotationSave}
        onBrowserElementActivate={onBrowserElementActivate}
        onCooperationModeChange={onBrowserCooperationModeChange}
        onBrowserEvents={onBrowserEvents}
        onProposalDecision={onBrowserProposalDecision}
        canPersistWorkspace={canPersistBrowserWorkspace}
      />
    );
  }
  if (!tab.detail) return <EmptyPanel text="Empty tab." />;
  const detail = tab.detail;
  return (
    <div className="space-y-3">
      <div className="border-b border-glass-border/25 pb-3">
        <div className="truncate text-sm font-medium text-foreground">{detail.title}</div>
        {detail.subtitle ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{detail.subtitle}</div> : null}
        {detail.url ? (
          <a href={detail.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
            Open URL
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </div>
      {detail.error ? (
        <div className="border-y border-destructive/30 py-2 text-xs text-destructive">
          {detail.error}
        </div>
      ) : null}
      {detail.metadata ? <MetadataBlock metadata={detail.metadata} /> : null}
      {detail.files?.length ? <FilesBlock files={detail.files} /> : null}
      {detail.commits?.length ? <CommitsBlock commits={detail.commits} /> : null}
      {detail.patch ? (
        <pre className="max-h-[48vh] overflow-auto rounded-xl border border-glass-border/35 bg-background/70 p-3 font-mono text-[11px] leading-5 text-muted-foreground">
          {detail.patch}
        </pre>
      ) : null}
    </div>
  );
}
