import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode, type WheelEvent } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Database,
  ExternalLink,
  FilePenLine,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Globe2,
  ListChecks,
  MessageSquarePlus,
  RefreshCw,
  Loader2,
  PanelRightClose,
  Plus,
  Upload,
  X,
} from "lucide-react";
import {
  fetchBackendText,
  type SessionBrowserAnnotation,
  type SessionBrowserCooperationEvent,
  type SessionBrowserCooperationMode,
  type SessionBrowserElement,
  type SessionBrowserView,
  type SessionBrowserViewport,
} from "../../api/client";
import { cn } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import type { ComposerAnnotation } from "../../stores/chat-store";
import type {
  ChangedFile,
  ProjectItem,
  SessionMemorySummary,
  SessionMemoryTopItem,
  SessionPanelSnapshot,
  SessionSource,
  SessionUsage,
  SessionUsageMetric,
  ToolBlockStatus,
  ToolBlockUi,
} from "../../types/chat";

import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import type { SessionDetailView } from "./session-detail-window";
import {
  BROWSER_FORWARD_KEYS,
  browserAnnotationCounts,
  browserAnnotationEditorStyle,
  browserCssBadgeClass,
  browserCssLabel,
  browserElementAtRenderedPoint,
  browserRenderedElementStyle,
  browserToolEventAppliesToBrowser,
  browserToolEventIsPassive,
  browserTraceBounds,
  browserViewport,
  browserVisualEventFromProposal,
  browserVisualEventsFromRecords,
  formatNumber,
  formatValue,
  isBrowserViewportControlTarget,
  labelize,
  normalizeBrowserElementMetadata,
  normalizeBrowserTextSelection,
  recordArray,
  selectedElementLabel,
} from "./session-panel/browser-helpers";
import { browserMirrorSrcDoc } from "./session-panel/browser-mirror";
import { useBrowserTabs } from "./session-panel/use-browser-tabs";
import { useSessionPanelState } from "./session-panel/use-session-panel-state";
export { SESSION_PANEL_CACHE_STORAGE_KEY } from "./session-panel/cache";
export { browserMirrorSrcDoc, sanitizeBrowserMirrorHtml } from "./session-panel/browser-mirror";
import {
  type BrowserTab,
  type BrowserState,
  type BrowserElementMetadata,
  type BrowserTextSelectionMetadata,
  type BrowserTracingTab,
  type BrowserVisualEffect,
  type BrowserVisualEvent,
  type BrowserToolEvent,
  summaryTab,
  BROWSER_LOADING_MESSAGES,
  browserCooperationFromView,
  createEmptyBrowserState,
  isBrowserCooperationEvent,
  isBrowserTab,
  recordValue,
  resolveBackendUrlPath,
} from "./session-panel/helpers";

export function SessionPanel({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const {
    baseUrl,
    workspaceRoot,
    conversationId,
    isStreaming,
    browserToolBlocks,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
    snapshot,
    usage,
    panelIsLoading,
    panelError,
  } = useSessionPanelState(visible);
  const {
    tabs,
    activeTabId,
    activeTab,
    loadingDetailId,
    browserVisualEvents,
    browserToolEvent,
    setActiveTabId,
    closeTab,
    openBrowserPlaceholder,
    openDetailTab,
    openProjectDetail,
    updateBrowserTab,
    loadBrowserView,
    navigateBrowser,
    moveBrowserHistory,
    refreshBrowser,
    clickBrowser,
    keyBrowser,
    scrollBrowser,
    setBrowserMode,
    selectBrowserElement,
    updateAnnotationDraft,
    addBrowserTextSelection,
    saveBrowserAnnotation,
    activateBrowserElement,
    setBrowserCooperationMode,
    decideBrowserProposal,
    recordBrowserEvents,
    setBrowserError,
  } = useBrowserTabs({
    browserToolBlocks,
    isStreaming,
    conversationId,
    baseUrl,
    workspaceRoot,
    visible,
    addComposerAnnotation,
    approvePendingTool,
    rejectPendingTool,
  });
  return (
    <aside className="flex h-full min-w-0 w-full flex-col bg-popover">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3">
        <PanelRightClose className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">Session Panel</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {snapshot?.title || (conversationId ? "Active session" : "No conversation")}
          </div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Close session panel" onClick={onClose}>
              <PanelRightClose className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Close</TooltipContent>
        </Tooltip>
      </div>

      <BrowserTabStrip
        tabs={tabs}
        activeTabId={activeTabId}
        onSelect={setActiveTabId}
        onClose={closeTab}
        onAdd={openBrowserPlaceholder}
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-3">
        {isBrowserTab(activeTab) ? (
          <DetailTabContent
            tab={activeTab}
            onBrowserDraftChange={(value) => updateBrowserTab(activeTab.id, (browser) => ({ ...browser, draftUrl: value }))}
            onBrowserLoad={(viewport) => void loadBrowserView(activeTab.id, viewport)}
            onBrowserNavigate={(value, viewport) => void navigateBrowser(activeTab.id, value, viewport)}
            onBrowserBack={(viewport) => void moveBrowserHistory(activeTab.id, -1, viewport)}
            onBrowserForward={(viewport) => void moveBrowserHistory(activeTab.id, 1, viewport)}
            onBrowserRefresh={(viewport) => void refreshBrowser(activeTab.id, viewport)}
            onBrowserClick={(input) => void clickBrowser(activeTab.id, input)}
            onBrowserKey={(input) => void keyBrowser(activeTab.id, input)}
            onBrowserScroll={(input) => void scrollBrowser(activeTab.id, input)}
            onBrowserModeChange={(mode) => setBrowserMode(activeTab.id, mode)}
            onBrowserElementSelect={(nodeId, element) => selectBrowserElement(activeTab.id, nodeId, element)}
            onBrowserTextSelect={(selection) => addBrowserTextSelection(activeTab.id, selection)}
            onBrowserAnnotationDraftChange={(value) => updateAnnotationDraft(activeTab.id, value)}
            onBrowserAnnotationSave={() => void saveBrowserAnnotation(activeTab.id)}
            onBrowserElementActivate={(nodeId, viewport) => void activateBrowserElement(activeTab.id, nodeId, viewport)}
            onBrowserCooperationModeChange={(mode) => void setBrowserCooperationMode(activeTab.id, mode)}
            onBrowserEvents={(events) => void recordBrowserEvents(activeTab.id, events)}
            onBrowserProposalDecision={(proposal, decision) => void decideBrowserProposal(activeTab.id, proposal, decision)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
            browserToolEvent={browserToolEvent}
            browserVisualEvents={browserVisualEvents}
          />
        ) : !conversationId ? (
          <EmptyPanel text="Start or open a conversation to view session data." />
        ) : panelIsLoading ? (
          <PanelSkeleton />
        ) : panelError ? (
          <EmptyPanel text={panelError instanceof Error ? panelError.message : String(panelError)} />
        ) : activeTab.id === summaryTab.id ? (
          <SummaryContent
            snapshot={snapshot}
            usage={usage}
            loadingDetailId={loadingDetailId}
            onOpenDetail={openDetailTab}
            onOpenProjectDetail={(item) => void openProjectDetail(item)}
          />
        ) : (
          <DetailTabContent
            tab={activeTab}
            onBrowserDraftChange={(value) => updateBrowserTab(activeTab.id, (browser) => ({ ...browser, draftUrl: value }))}
            onBrowserLoad={(viewport) => void loadBrowserView(activeTab.id, viewport)}
            onBrowserNavigate={(value, viewport) => void navigateBrowser(activeTab.id, value, viewport)}
            onBrowserBack={(viewport) => void moveBrowserHistory(activeTab.id, -1, viewport)}
            onBrowserForward={(viewport) => void moveBrowserHistory(activeTab.id, 1, viewport)}
            onBrowserRefresh={(viewport) => void refreshBrowser(activeTab.id, viewport)}
            onBrowserClick={(input) => void clickBrowser(activeTab.id, input)}
            onBrowserKey={(input) => void keyBrowser(activeTab.id, input)}
            onBrowserScroll={(input) => void scrollBrowser(activeTab.id, input)}
            onBrowserModeChange={(mode) => setBrowserMode(activeTab.id, mode)}
            onBrowserElementSelect={(nodeId, element) => selectBrowserElement(activeTab.id, nodeId, element)}
            onBrowserTextSelect={(selection) => addBrowserTextSelection(activeTab.id, selection)}
            onBrowserAnnotationDraftChange={(value) => updateAnnotationDraft(activeTab.id, value)}
            onBrowserAnnotationSave={() => void saveBrowserAnnotation(activeTab.id)}
            onBrowserElementActivate={(nodeId, viewport) => void activateBrowserElement(activeTab.id, nodeId, viewport)}
            onBrowserCooperationModeChange={(mode) => void setBrowserCooperationMode(activeTab.id, mode)}
            onBrowserEvents={(events) => void recordBrowserEvents(activeTab.id, events)}
            onBrowserProposalDecision={(proposal, decision) => void decideBrowserProposal(activeTab.id, proposal, decision)}
            canPersistBrowserWorkspace={Boolean(conversationId)}
            browserToolEvent={browserToolEvent}
            browserVisualEvents={browserVisualEvents}
          />
        )}
      </div>
    </aside>
  );
}

function BrowserTabStrip({
  tabs,
  activeTabId,
  onSelect,
  onClose,
  onAdd,
}: {
  tabs: BrowserTab[];
  activeTabId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onAdd: () => void;
}) {
  return (
    <div className="flex h-11 shrink-0 items-end border-b border-glass-border/25 bg-background/80 px-2 pt-1.5" role="tablist" aria-label="Session panel tabs">
      <div className="flex min-w-0 flex-1 items-end gap-1 overflow-x-auto">
        {tabs.map((tab) => {
          const active = tab.id === activeTabId;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={tab.title}
              className={cn(
                "group relative flex h-8 max-w-[170px] min-w-0 items-center gap-1.5 rounded-t-xl px-3 text-left text-xs transition-[background,color,box-shadow]",
                active
                  ? "bg-popover text-foreground shadow-[inset_0_1px_0_hsl(var(--glass-border)_/_0.45),inset_1px_0_0_hsl(var(--glass-border)_/_0.35),inset_-1px_0_0_hsl(var(--glass-border)_/_0.35)]"
                  : "bg-transparent text-muted-foreground hover:bg-muted/70 hover:text-foreground",
              )}
              onClick={() => onSelect(tab.id)}
            >
              <span className="min-w-0 flex-1 truncate">{tab.title}</span>
              {tab.closeable ? (
                <span
                  role="button"
                  aria-label={`Close tab ${tab.title}`}
                  tabIndex={0}
                  className="grid h-4 w-4 shrink-0 place-items-center rounded text-muted-foreground opacity-0 hover:bg-accent hover:text-foreground group-hover:opacity-100 group-focus-within:opacity-100"
                  onClick={(event) => {
                    event.stopPropagation();
                    onClose(tab.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      event.stopPropagation();
                      onClose(tab.id);
                    }
                  }}
                >
                  <X className="h-3 w-3" />
                </span>
              ) : null}
            </button>
          );
        })}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="New panel tab"
              className="mb-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" sideOffset={8} className="w-48 rounded-xl">
            <DropdownMenuLabel>New tab</DropdownMenuLabel>
            <DropdownMenuItem onClick={onAdd} className="gap-2 rounded-lg">
              <Globe2 className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="min-w-0 flex-1">Browser</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <div className="h-8 min-w-2 flex-1" />
      </div>
    </div>
  );
}

function SummaryContent({
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

function DetailTabContent({
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

function BrowserTabContent({
  browser,
  browserToolEvent,
  browserVisualEvents = [],
  onDraftChange,
  onLoadView,
  onNavigate,
  onBack,
  onForward,
  onRefresh,
  onBrowserClick,
  onBrowserKey,
  onBrowserScroll,
  onModeChange,
  onElementSelect,
  onTextSelect,
  onAnnotationDraftChange,
  onAnnotationSave,
  onBrowserElementActivate,
  onCooperationModeChange,
  onBrowserEvents,
  onProposalDecision,
  canPersistWorkspace,
}: {
  browser: BrowserState;
  browserToolEvent?: BrowserToolEvent;
  browserVisualEvents?: BrowserVisualEvent[];
  onDraftChange: (value: string) => void;
  onLoadView: (viewport: SessionBrowserViewport) => void;
  onNavigate: (value: string, viewport: SessionBrowserViewport) => void;
  onBack: (viewport: SessionBrowserViewport) => void;
  onForward: (viewport: SessionBrowserViewport) => void;
  onRefresh: (viewport: SessionBrowserViewport) => void;
  onBrowserClick: (input: SessionBrowserViewport & { x: number; y: number; button?: "left" | "middle" | "right" }) => void;
  onBrowserKey: (input: SessionBrowserViewport & { text?: string; key?: string }) => void;
  onBrowserScroll: (input: SessionBrowserViewport & { delta_x: number; delta_y: number }) => void;
  onModeChange: (mode: BrowserState["mode"]) => void;
  onElementSelect: (nodeId: string, element?: BrowserElementMetadata) => void;
  onTextSelect: (selection: BrowserTextSelectionMetadata) => void;
  onAnnotationDraftChange: (value: string) => void;
  onAnnotationSave: () => void;
  onBrowserElementActivate: (nodeId: string, viewport: SessionBrowserViewport, action?: "click" | "submit") => void;
  onCooperationModeChange: (mode: SessionBrowserCooperationMode | "off") => void;
  onBrowserEvents: (events: SessionBrowserCooperationEvent[]) => void;
  onProposalDecision: (
    proposal: Record<string, unknown>,
    decision: "approve" | "deny" | "dismiss",
  ) => void;
  canPersistWorkspace: boolean;
}) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const annotationInputRef = useRef<HTMLTextAreaElement | null>(null);
  const requestedInitialViewRef = useRef(false);
  const lastBrowserIdRef = useRef(browser.browserId);
  const [mirrorUrl, setMirrorUrl] = useState("");
  const [mirrorReady, setMirrorReady] = useState(false);
  const [remoteDocumentHtml, setRemoteDocumentHtml] = useState("");
  const [pixelHoverNodeId, setPixelHoverNodeId] = useState<string | null>(null);
  const [loadingMessageIndex, setLoadingMessageIndex] = useState(0);
  const [tracingOpen, setTracingOpen] = useState(false);
  const [tracingTab, setTracingTab] = useState<BrowserTracingTab>("timeline");
  const canGoBack = browser.historyIndex > 0;
  const canGoForward = browser.historyIndex >= 0 && browser.historyIndex < browser.history.length - 1;
  const canRefresh = Boolean(browser.currentUrl);
  const imageSource =
    browser.view?.image_data && browser.view.image_mime_type
      ? `data:${browser.view.image_mime_type};base64,${browser.view.image_data}`
      : resolveBackendUrlPath(
          baseUrl,
          browser.view?.preview_image_url || browser.view?.browser_snapshot?.preview_image_url,
        );
  const showRenderedPage = Boolean(imageSource && browser.currentUrl);
  const inlineDocumentHtml = browser.view?.document_html || browser.view?.browser_snapshot?.document_html || browser.view?.html || "";
  const documentUrl = resolveBackendUrlPath(
    baseUrl,
    browser.view?.document_url || browser.view?.browser_snapshot?.document_url,
  );
  const documentHtml = inlineDocumentHtml || remoteDocumentHtml;
  const elementMap = browser.view?.element_map || browser.view?.browser_snapshot?.element_map || [];
  const annotations = browser.view?.annotations || browser.view?.browser_snapshot?.annotations || [];
  const timelineEvents = browser.view?.timeline_events || browser.view?.browser_snapshot?.timeline_events || [];
  const backendTabs = browser.view?.tabs || browser.view?.browser_snapshot?.tabs || [];
  const cooperation = browserCooperationFromView(browser.view);
  const cooperationEnabled = Boolean(cooperation?.enabled);
  const cooperationMode = cooperationEnabled ? cooperation?.mode ?? cooperation?.agent_control ?? "observe_only" : "off";
  const rawEvents = useMemo(() => recordArray(cooperation?.raw_events), [cooperation?.raw_events]);
  const usefulTimeline = useMemo(() => recordArray(cooperation?.useful_timeline), [cooperation?.useful_timeline]);
  const recentUserEvents = useMemo(() => recordArray(cooperation?.recent_user_events), [cooperation?.recent_user_events]);
  const recentAgentEvents = useMemo(() => recordArray(cooperation?.recent_agent_events), [cooperation?.recent_agent_events]);
  const pendingProposals = useMemo(
    () =>
      recordArray(cooperation?.pending_action_proposals).filter(
        (proposal) => String(proposal.status ?? "awaiting_approval") === "awaiting_approval",
      ),
    [cooperation?.pending_action_proposals],
  );
  const activeProposal = pendingProposals[0];
  const activeProposalTarget = activeProposal ? recordValue(activeProposal.target) : {};
  const proposalVisual = useMemo(
    () => (activeProposal ? browserVisualEventFromProposal(activeProposal, browser) : undefined),
    [activeProposal, browser.browserId, browser.currentUrl, browser.view?.active_tab_id],
  );
  const viewVisualEvents = useMemo(
    () => browserVisualEventsFromRecords(browser.view?.visual_events ?? browser.view?.browser_snapshot?.visual_events),
    [browser.view?.visual_events, browser.view?.browser_snapshot?.visual_events],
  );
  const visibleBrowserVisualEvents = useMemo(
    () =>
      [proposalVisual, ...browserVisualEvents, ...viewVisualEvents]
        .filter((event): event is BrowserVisualEvent => Boolean(event))
        .filter((event) => browserToolEventAppliesToBrowser(event, browser))
        .slice(0, 8),
    [browser, browserVisualEvents, proposalVisual, viewVisualEvents],
  );
  const activeBrowserToolEvent = browserToolEventAppliesToBrowser(browserToolEvent, browser) ? browserToolEvent : undefined;
  const showHtmlMirror = Boolean(
    browser.currentUrl &&
      (browser.view?.render_mode === "html_mirror" || browser.view?.render_mode === "computed_html") &&
      documentHtml,
  );
  const mirrorElementMap = useMemo(() => elementMap, [browser.browserId, browser.currentUrl, documentHtml]);
  const mirrorDocument = useMemo(
    () =>
      showHtmlMirror
        ? browserMirrorSrcDoc(documentHtml, browser.currentUrl, browser.browserId, mirrorElementMap, false)
        : "",
    [browser.browserId, browser.currentUrl, documentHtml, mirrorElementMap, showHtmlMirror],
  );
  const canInspectBrowser = showHtmlMirror || showRenderedPage;
  const annotationCounts = useMemo(() => browserAnnotationCounts(annotations), [annotations]);
  const selectedElement = browser.selectedNodeId
    ? elementMap.find((item) => item.node_id === browser.selectedNodeId) ?? browser.elementMetadata[browser.selectedNodeId]
    : undefined;
  const pixelHoverElement = pixelHoverNodeId ? elementMap.find((item) => item.node_id === pixelHoverNodeId) : undefined;
  const viewport = () => browserViewport(viewportRef.current, browser.view);
  const showEmptyState = !browser.loading && !showRenderedPage && !(showHtmlMirror && mirrorUrl);
  const showMirrorPreparing = showHtmlMirror && Boolean(mirrorUrl) && !mirrorReady;

  if (lastBrowserIdRef.current !== browser.browserId) {
    lastBrowserIdRef.current = browser.browserId;
    requestedInitialViewRef.current = false;
  }

  useEffect(() => {
    if (requestedInitialViewRef.current || browser.view || browser.loading) return;
    if (activeBrowserToolEvent && browserToolEventIsPassive(activeBrowserToolEvent)) return;
    requestedInitialViewRef.current = true;
    onLoadView(viewport());
  }, [browser.browserId, browser.currentUrl, browser.loading, browser.view, onLoadView, activeBrowserToolEvent]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data =
        event.data as
          | {
              type?: unknown;
              browserId?: unknown;
              url?: unknown;
              nodeId?: unknown;
              action?: unknown;
              element?: unknown;
              selection?: unknown;
              events?: unknown;
            }
          | undefined;
      if (!data || data.browserId !== browser.browserId) return;
      if (data.type === "personagent-session-browser:ready") {
        setMirrorReady(true);
      } else if (data.type === "personagent-session-browser:navigate" && typeof data.url === "string") {
        onNavigate(data.url, viewport());
      } else if (data.type === "personagent-session-browser:element" && typeof data.nodeId === "string") {
        const element = normalizeBrowserElementMetadata(data.element, data.nodeId);
        onElementSelect(data.nodeId, element);
      } else if (data.type === "personagent-session-browser:element-action" && typeof data.nodeId === "string") {
        onBrowserElementActivate(data.nodeId, viewport(), data.action === "submit" ? "submit" : "click");
      } else if (data.type === "personagent-session-browser:text-selection") {
        const selection = normalizeBrowserTextSelection(data.selection);
        if (selection) {
          onTextSelect(selection);
        }
      } else if (data.type === "personagent-session-browser:event-batch" && Array.isArray(data.events)) {
        const events = data.events.filter(isBrowserCooperationEvent);
        if (events.length) onBrowserEvents(events);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [browser.browserId, onBrowserElementActivate, onBrowserEvents, onElementSelect, onNavigate, onTextSelect]);

  useEffect(() => {
    if (browser.mode !== "annotate" || !browser.selectedNodeId) return;
    annotationInputRef.current?.focus();
  }, [browser.mode, browser.selectedNodeId]);

  useEffect(() => {
    if (inlineDocumentHtml || !documentUrl) {
      setRemoteDocumentHtml("");
      return;
    }
    let cancelled = false;
    setRemoteDocumentHtml("");
    fetchBackendText(documentUrl)
      .then((html) => {
        if (!cancelled) setRemoteDocumentHtml(html);
      })
      .catch(() => {
        if (!cancelled) setRemoteDocumentHtml("");
      });
    return () => {
      cancelled = true;
    };
  }, [documentUrl, inlineDocumentHtml]);

  useEffect(() => {
    if (!browser.loading) {
      setLoadingMessageIndex(0);
      return;
    }
    const interval = window.setInterval(() => {
      setLoadingMessageIndex((current) => (current + 1) % BROWSER_LOADING_MESSAGES.length);
    }, 1200);
    return () => window.clearInterval(interval);
  }, [browser.loading]);

  useEffect(() => {
    if (!mirrorDocument || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
      setMirrorReady(false);
      setMirrorUrl("");
      return;
    }
    const nextUrl = URL.createObjectURL(new Blob([mirrorDocument], { type: "text/html" }));
    setMirrorReady(false);
    setMirrorUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [mirrorDocument]);

  const postMirrorState = () => {
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage(
      {
        type: "personagent-session-browser:state",
        browserId: browser.browserId,
        mode: browser.mode,
        annotationCounts,
        selectedNodeId: browser.selectedNodeId || "",
        cooperationEnabled,
      },
      "*",
    );
  };

  const handleMirrorLoad = () => {
    postMirrorState();
  };

  useEffect(() => {
    postMirrorState();
  }, [browser.browserId, browser.mode, browser.selectedNodeId, annotationCounts, cooperationEnabled, mirrorUrl]);

  const handleViewportClick = (event: MouseEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view) return;
    if (browser.mode !== "browse" && pixelHoverElement?.node_id) {
      event.preventDefault();
      event.stopPropagation();
      onElementSelect(pixelHoverElement.node_id, pixelHoverElement as BrowserElementMetadata);
      return;
    }
    if (!imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    viewportRef.current?.focus();
    const targetWidth = browser.view.viewport_width || rect.width;
    const targetHeight = browser.view.viewport_height || rect.height;
    onBrowserClick({
      width: targetWidth,
      height: targetHeight,
      x: ((event.clientX - rect.left) / rect.width) * targetWidth,
      y: ((event.clientY - rect.top) / rect.height) * targetHeight,
      button: event.button === 1 ? "middle" : event.button === 2 ? "right" : "left",
    });
  };

  const handleViewportMouseMove = (event: MouseEvent<HTMLDivElement>) => {
    if (browser.mode === "browse" || !browser.view) return;
    const surface = showRenderedPage ? imageRef.current : showHtmlMirror ? viewportRef.current : null;
    if (!surface) return;
    const element = browserElementAtRenderedPoint(event, surface, browser.view, elementMap);
    setPixelHoverNodeId(element?.node_id ?? null);
  };

  const handleViewportMouseLeave = () => {
    setPixelHoverNodeId(null);
  };

  const handleViewportKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view || event.ctrlKey || event.metaKey || event.altKey) return;
    const currentViewport = viewport();
    if (event.key.length === 1) {
      event.preventDefault();
      onBrowserKey({ ...currentViewport, text: event.key });
      return;
    }
    if (BROWSER_FORWARD_KEYS.has(event.key)) {
      event.preventDefault();
      onBrowserKey({ ...currentViewport, key: event.key });
    }
  };

  const handleViewportWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (isBrowserViewportControlTarget(event.target)) return;
    if (!browser.view) return;
    event.preventDefault();
    onBrowserScroll({ ...viewport(), delta_x: event.deltaX, delta_y: event.deltaY });
  };

  return (
    <div className="flex min-h-[calc(100vh-170px)] flex-col">
      <div className="-mx-3 -mt-3 flex h-11 shrink-0 items-center gap-1.5 border-b border-glass-border/25 bg-background/70 px-3">
        <BrowserNavButton label="Back" disabled={!canGoBack} onClick={() => onBack(viewport())}>
          <ArrowLeft className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <BrowserNavButton label="Forward" disabled={!canGoForward} onClick={() => onForward(viewport())}>
          <ArrowRight className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <BrowserNavButton label="Reload page" disabled={!canRefresh} onClick={() => onRefresh(viewport())}>
          <RefreshCw className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <form
          className="ml-1 min-w-0 flex-1"
          onSubmit={(event) => {
            event.preventDefault();
            onNavigate(browser.draftUrl, viewport());
          }}
        >
          <input
            aria-label="Enter URL"
            className="h-8 w-full rounded-full border border-glass-border/35 bg-card/70 px-3 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/50 focus:bg-background"
            placeholder="Enter URL"
            value={browser.draftUrl}
            onChange={(event) => onDraftChange(event.currentTarget.value)}
          />
        </form>
        <BrowserModeButton
          label="Inspect and annotate"
          active={browser.mode === "annotate"}
          disabled={!canInspectBrowser}
          onClick={() => onModeChange(browser.mode === "annotate" ? "browse" : "annotate")}
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
        </BrowserModeButton>
        <BrowserCooperationModeMenu
          value={cooperationMode}
          disabled={!canPersistWorkspace}
          onChange={onCooperationModeChange}
        />
        <BrowserModeButton
          label="Tracing"
          active={tracingOpen}
          disabled={!canInspectBrowser}
          onClick={() => setTracingOpen((open) => !open)}
        >
          <Activity className="h-3.5 w-3.5" />
        </BrowserModeButton>
      </div>
      <div className="-mx-3 flex h-8 shrink-0 items-center gap-2 border-b border-glass-border/20 bg-background/55 px-3 text-[11px] text-muted-foreground">
        <span className={cn("rounded-full border px-2 py-0.5", browserCssBadgeClass(browser.view?.css_fidelity))}>
          {browserCssLabel(browser.view?.css_fidelity)}
        </span>
        <span className="min-w-0 flex-1 truncate">
          {browser.mode === "annotate"
            ? "Annotation mode · hover and click an element"
            : `${elementMap.length} mapped elements${backendTabs.length > 1 ? ` · ${backendTabs.length} tabs` : ""}`}
        </span>
        {annotations.length ? (
          <span className="inline-flex items-center gap-1">
            <MessageSquarePlus className="h-3 w-3" />
            {annotations.length}
          </span>
        ) : null}
        {timelineEvents.length ? (
          <span className="inline-flex items-center gap-1">
            <ListChecks className="h-3 w-3" />
            {timelineEvents.length}
          </span>
        ) : null}
      </div>
      <div
        ref={viewportRef}
        role="application"
        aria-label="LightPanda browser viewport"
        tabIndex={0}
        className="relative -mx-3 -mb-4 min-h-[calc(100vh-220px)] flex-1 overflow-hidden bg-background outline-none"
        onClick={handleViewportClick}
        onMouseMove={handleViewportMouseMove}
        onMouseLeave={handleViewportMouseLeave}
        onKeyDown={handleViewportKeyDown}
        onWheel={handleViewportWheel}
      >
        {showRenderedPage ? (
          <>
            <img
              ref={imageRef}
              src={imageSource}
              alt={browser.view?.title || browser.currentUrl || "LightPanda browser"}
              title={`Browser ${browser.currentUrl || browser.view?.url || ""}`.trim()}
              className="h-full min-h-[calc(100vh-220px)] w-full select-none object-contain"
              draggable={false}
            />
            {pixelHoverElement?.bounds && browser.view ? (
              <div
              className="pointer-events-none absolute z-20 rounded-[var(--browser-highlight-radius,4px)] border-2 border-primary bg-primary/18 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.18)] transition-all duration-100"
              style={browserRenderedElementStyle(pixelHoverElement.bounds, imageRef.current, browser.view)}
              />
            ) : null}
          </>
        ) : showHtmlMirror && mirrorUrl ? (
	          <iframe
	            ref={iframeRef}
	            title={`Browser ${browser.currentUrl}`}
	            src={mirrorUrl}
	            sandbox="allow-forms allow-scripts"
	            onLoad={handleMirrorLoad}
	            className={cn(
	              "h-full min-h-[calc(100vh-220px)] w-full border-0 bg-white transition-opacity duration-150",
	              !mirrorReady && "opacity-0",
	            )}
	          />
        ) : showEmptyState ? (
          <div className="flex h-full min-h-[260px] items-center justify-center px-8 text-center text-xs leading-5 text-muted-foreground">
            Enter a URL to open a page in this tab.
          </div>
        ) : null}
        {activeProposal && browser.view ? (
          <BrowserProposalOverlay
            proposal={activeProposal}
            target={activeProposalTarget}
            elementMap={elementMap}
            view={browser.view}
            surface={showRenderedPage ? imageRef.current : viewportRef.current}
            onDecision={onProposalDecision}
          />
        ) : null}
        {tracingOpen ? (
          <BrowserTracingPanel
            cooperation={cooperation}
            rawEvents={rawEvents}
            usefulTimeline={usefulTimeline}
            recentUserEvents={recentUserEvents}
            recentAgentEvents={recentAgentEvents}
            pendingProposals={pendingProposals}
            visualEvents={visibleBrowserVisualEvents}
            activeTab={tracingTab}
            onTabChange={setTracingTab}
            onClose={() => setTracingOpen(false)}
            onProposalDecision={onProposalDecision}
          />
        ) : null}
        {browser.loading || showMirrorPreparing ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-background/78 px-8 text-center backdrop-blur-sm">
            <div className="flex max-w-[300px] flex-col items-center gap-3 rounded-2xl border border-glass-border/35 bg-card/86 px-5 py-5 shadow-floating ring-1 ring-white/[0.04]">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <div className="space-y-1">
                <div className="text-sm font-medium text-foreground">
                  {showMirrorPreparing ? "Aguardando CSS da pagina..." : BROWSER_LOADING_MESSAGES[loadingMessageIndex]}
                </div>
                <div className="text-[11px] leading-4 text-muted-foreground">
                  Preparando HTML, CSS e mapa de elementos do Browser.
                </div>
              </div>
            </div>
          </div>
        ) : null}
        {browser.error ? (
          <div className="absolute inset-x-4 bottom-4 rounded-lg border border-destructive/35 bg-background/90 px-3 py-2 text-[11px] leading-4 text-destructive">
            {browser.error}
          </div>
        ) : null}
        {browser.mode === "annotate" && browser.selectedNodeId ? (
          <form
            data-browser-annotation-editor="true"
            className="absolute z-30 max-w-[calc(100%-24px)] rounded-2xl border border-glass-border/40 bg-card/88 p-2 text-xs shadow-floating ring-1 ring-white/[0.04] backdrop-blur-2xl"
            style={browserAnnotationEditorStyle(selectedElement?.bounds, browser.view)}
            onSubmit={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onAnnotationSave();
            }}
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
            onWheel={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            <div className="mb-2 flex items-start gap-2">
              <MessageSquarePlus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-foreground">
                  {selectedElementLabel(selectedElement, browser.selectedNodeId)}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                  {selectedElement?.text || selectedElement?.selector || "Browser element"}
                </div>
              </div>
              <button
                type="button"
                className="text-muted-foreground transition-colors hover:text-foreground"
                onClick={() => onElementSelect("")}
                aria-label="Close annotation editor"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <textarea
              ref={annotationInputRef}
              value={browser.annotationDraft}
              onChange={(event) => onAnnotationDraftChange(event.currentTarget.value)}
              placeholder="Ask the agent about this element or describe a change"
              rows={1}
              className="max-h-24 min-h-10 w-full resize-none rounded-xl border border-glass-border/30 bg-background/45 px-3 py-2 text-sm leading-5 text-foreground outline-none placeholder:text-muted-foreground/75 focus:border-primary/45"
              onKeyDown={(event) => {
                event.stopPropagation();
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  onAnnotationSave();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  onElementSelect("");
                }
              }}
            />
            <div className="mt-2 flex justify-end gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => onElementSelect("")}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={!browser.annotationDraft.trim()}
              >
                Send to Agent
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}

function BrowserNavButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
    >
      {children}
    </button>
  );
}

function BrowserModeButton({
  label,
  active,
  disabled,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs transition-colors disabled:pointer-events-none disabled:opacity-35",
        active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function BrowserCooperationModeMenu({
  value,
  disabled,
  onChange,
}: {
  value: SessionBrowserCooperationMode | "off";
  disabled: boolean;
  onChange: (mode: SessionBrowserCooperationMode | "off") => void;
}) {
  const options: Array<{ value: SessionBrowserCooperationMode | "off"; label: string }> = [
    { value: "off", label: "Off" },
    { value: "observe_only", label: "Observe" },
    { value: "suggest_before_action", label: "Suggest" },
    { value: "agent_control", label: "Control" },
  ];
  const active = options.find((option) => option.value === value) ?? options[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Browser cooperation mode"
          disabled={disabled}
          className={cn(
            "inline-flex h-7 max-w-[132px] shrink-0 items-center gap-1.5 rounded-full border border-glass-border/35 bg-card/70 px-2.5 text-[11px] text-foreground outline-none transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-35",
            value !== "off" && "border-primary/35 bg-primary/10 text-primary",
          )}
        >
          <span className="truncate">{active.label}</span>
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel>Cooperation</DropdownMenuLabel>
        {options.map((option) => (
          <DropdownMenuItem key={option.value} onSelect={() => onChange(option.value)}>
            <Check className={cn("mr-2 h-3.5 w-3.5", option.value === value ? "opacity-100" : "opacity-0")} />
            <span>{option.label}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function BrowserProposalOverlay({
  proposal,
  target,
  elementMap,
  view,
  surface,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  target: Record<string, unknown>;
  elementMap: SessionBrowserElement[];
  view: SessionBrowserView;
  surface: HTMLElement | null;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  const bounds = browserTraceBounds(target, elementMap);
  if (!bounds) {
    return (
      <div className="absolute right-3 top-3 z-40 w-[min(340px,calc(100%-24px))] rounded-lg border border-primary/35 bg-background/94 p-3 text-xs shadow-floating backdrop-blur-xl">
        <ProposalBody proposal={proposal} onDecision={onDecision} />
      </div>
    );
  }
  const highlight = browserRenderedElementStyle(bounds, surface, view);
  const barTop = Math.max(8, highlight.top - 38);
  const barLeft = Math.max(8, Math.min(highlight.left, (view.viewport_width || 420) - 230));
  return (
    <>
      <div
        className="pointer-events-none absolute z-30 rounded-[4px] border-2 border-primary bg-primary/18 shadow-[0_0_0_3px_rgba(34,150,255,0.14)]"
        style={highlight}
      />
      <div
        className="absolute z-40 flex max-w-[min(360px,calc(100%-16px))] items-center gap-2 rounded-full border border-primary/35 bg-background/94 px-2 py-1.5 text-[11px] shadow-floating backdrop-blur-xl"
        style={{ left: barLeft, top: barTop }}
      >
        <span className="min-w-0 max-w-32 truncate text-muted-foreground">
          {String(proposal.tool_name ?? "Browser action")}
        </span>
        <button
          type="button"
          className="rounded-full bg-primary px-2.5 py-1 font-medium text-primary-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "approve");
          }}
        >
          Allow
        </button>
        <button
          type="button"
          className="rounded-full border border-destructive/35 px-2.5 py-1 font-medium text-destructive"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "deny");
          }}
        >
          Deny
        </button>
        <button
          type="button"
          className="rounded-full px-2 py-1 text-muted-foreground hover:text-foreground"
          onClick={(event) => {
            event.stopPropagation();
            onDecision(proposal, "dismiss");
          }}
        >
          Dismiss
        </button>
      </div>
    </>
  );
}

function ProposalBody({
  proposal,
  onDecision,
}: {
  proposal: Record<string, unknown>;
  onDecision: (proposal: Record<string, unknown>, decision: "approve" | "deny" | "dismiss") => void;
}) {
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-foreground">
            {String(proposal.tool_name ?? "Browser action")}
          </div>
          <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
            {String(proposal.reason ?? "The agent needs permission before executing this action.")}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-primary/30 px-2 py-0.5 font-mono text-[10px] text-primary">
          {String(proposal.mode ?? "ask")}
        </span>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" onClick={() => onDecision(proposal, "approve")}>
          Allow
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDecision(proposal, "deny")}>
          Deny
        </Button>
      </div>
    </div>
  );
}

function BrowserTracingPanel({
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
  cooperation?: SessionBrowserView["cooperation"];
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

function BrowserVisualEventList({ events }: { events: BrowserVisualEvent[] }) {
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

function TraceList({ items, empty, raw = false }: { items: Array<Record<string, unknown>>; empty: string; raw?: boolean }) {
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

function TraceRoleBadge({ role }: { role: string }) {
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

function TraceJson({ value, compact = false }: { value: unknown; compact?: boolean }) {
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

function MetadataBlock({ metadata }: { metadata: Record<string, unknown> }) {
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

function FilesBlock({ files }: { files: Array<Record<string, unknown>> }) {
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

function CommitsBlock({ commits }: { commits: Array<Record<string, unknown>> }) {
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

function MetricBand({ items }: { items: Array<[string, number]> }) {
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

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
      {icon}
      <span>{title}</span>
    </div>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return <div className="flex min-h-[220px] items-center justify-center px-6 text-center text-xs text-muted-foreground">{text}</div>;
}

function EmptyList({ text }: { text: string }) {
  return <div className="py-2 text-[11px] text-muted-foreground">{text}</div>;
}

function PanelSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="grid grid-cols-4 gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="border-b border-glass-border/25 pb-2">
            <div className="h-5 w-8 rounded bg-muted" />
            <div className="mt-1 h-3 w-14 rounded bg-muted/60" />
          </div>
        ))}
      </div>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-24 rounded bg-muted/60" />
        </div>
        <div className="mt-2 divide-y divide-glass-border/25">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <div className="h-3 w-full rounded bg-muted/50" />
              <div className="h-3 w-8 rounded bg-muted/30" />
            </div>
          ))}
        </div>
      </section>
      <section className="border-t border-glass-border/25 pt-3">
        <div className="flex items-center gap-2">
          <div className="h-3.5 w-3.5 rounded bg-muted" />
          <div className="h-3 w-28 rounded bg-muted/60" />
        </div>
        <div className="mt-2 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 w-full rounded-lg border border-glass-border/25 bg-muted/20" />
          ))}
        </div>
      </section>
    </div>
  );
}
