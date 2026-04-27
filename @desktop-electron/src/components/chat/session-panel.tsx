import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ExternalLink,
  FilePenLine,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Globe2,
  RefreshCw,
  Loader2,
  PanelRightClose,
  Plus,
  Upload,
  X,
} from "lucide-react";
import { getSessionPanel, getSessionProjectDetail } from "../../api/client";
import { cn } from "../../lib/utils";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import type {
  ChangedFile,
  ProjectItem,
  SessionPanelSnapshot,
  SessionSource,
  SessionUsage,
  SessionUsageMetric,
} from "../../types/chat";
import { emptySessionUsage } from "../../types/chat";
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

type BrowserTab = {
  id: string;
  title: string;
  subtitle?: string;
  closeable: boolean;
  detail?: SessionDetailView;
  browser?: BrowserState;
};

type BrowserState = {
  currentUrl: string;
  draftUrl: string;
  history: string[];
  historyIndex: number;
  refreshKey: number;
};

const summaryTab: BrowserTab = {
  id: "summary",
  title: "Resumo",
  closeable: false,
};

function createEmptyBrowserState(): BrowserState {
  return {
    currentUrl: "",
    draftUrl: "",
    history: [],
    historyIndex: -1,
    refreshKey: 0,
  };
}

function isBrowserTab(tab: BrowserTab) {
  return Boolean(tab.browser) || tab.id.startsWith("browser:") || tab.title === "Browser";
}

export function SessionPanel({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);
  const conversationId = useChatStore((state) => state.conversationId);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const liveUsage = useChatStore((state) => state.liveSessionUsage);
  const queryClient = useQueryClient();
  const [loadingDetailId, setLoadingDetailId] = useState<string | null>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([summaryTab]);
  const [activeTabId, setActiveTabId] = useState(summaryTab.id);

  const panel = useQuery({
    queryKey: ["session-panel", baseUrl, conversationId, workspaceRoot],
    queryFn: () => getSessionPanel(baseUrl, conversationId!, workspaceRoot),
    enabled: visible && Boolean(baseUrl && conversationId),
    refetchInterval: visible && isStreaming ? 1500 : false,
  });

  useEffect(() => {
    const handler = () => {
      void queryClient.invalidateQueries({ queryKey: ["session-panel"] });
    };
    window.addEventListener("personagent:session-panel-changed", handler);
    window.addEventListener("personagent:conversations-changed", handler);
    return () => {
      window.removeEventListener("personagent:session-panel-changed", handler);
      window.removeEventListener("personagent:conversations-changed", handler);
    };
  }, [queryClient]);

  const snapshot = panel.data;
  const usage = useMemo(() => mergeUsage(snapshot?.usage, liveUsage), [snapshot?.usage, liveUsage]);
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? summaryTab;

  const openDetailTab = (detail: SessionDetailView) => {
    const tab: BrowserTab = {
      id: `${detail.type}:${detail.id}`,
      title: detail.title,
      subtitle: detail.subtitle,
      closeable: true,
      detail,
    };
    setTabs((current) => {
      if (current.some((item) => item.id === tab.id)) {
        return current.map((item) => (item.id === tab.id ? tab : item));
      }
      return [...current, tab];
    });
    setActiveTabId(tab.id);
  };

  const openProjectDetail = async (item: ProjectItem) => {
    if (!conversationId) return;
    const loadingKey = `${item.type}:${item.id}`;
    setLoadingDetailId(loadingKey);
    try {
      const detail = await getSessionProjectDetail(baseUrl, conversationId, {
        type: item.type,
        id: item.id,
        workspaceRoot,
      });
      openDetailTab({
        ...detail,
        title: detail.title || item.title,
        subtitle: item.subtitle,
      });
    } catch (error) {
      openDetailTab({
        type: item.type,
        id: item.id,
        title: item.title,
        subtitle: item.subtitle,
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLoadingDetailId(null);
    }
  };

  const closeTab = (tabId: string) => {
    setTabs((current) => current.filter((tab) => tab.id === summaryTab.id || tab.id !== tabId));
    if (activeTabId === tabId) setActiveTabId(summaryTab.id);
  };

  const openBrowserPlaceholder = () => {
    const id = `browser:${Date.now()}`;
    setTabs((current) => [
      ...current,
      {
        id,
        title: "Browser",
        closeable: true,
        browser: createEmptyBrowserState(),
      },
    ]);
    setActiveTabId(id);
  };

  const updateBrowserTab = (tabId: string, updater: (browser: BrowserState) => BrowserState) => {
    setTabs((current) =>
      current.map((tab) => {
        if (tab.id !== tabId || !isBrowserTab(tab)) return tab;
        return { ...tab, browser: updater(tab.browser ?? createEmptyBrowserState()) };
      }),
    );
  };

  const navigateBrowser = (tabId: string, rawUrl: string) => {
    const normalized = normalizeBrowserUrl(rawUrl);
    if (!normalized) return;
    updateBrowserTab(tabId, (browser) => {
      const baseHistory = browser.history.slice(0, browser.historyIndex + 1);
      const history = baseHistory.at(-1) === normalized ? baseHistory : [...baseHistory, normalized];
      return {
        currentUrl: normalized,
        draftUrl: normalized,
        history,
        historyIndex: history.length - 1,
        refreshKey: browser.refreshKey,
      };
    });
  };

  const moveBrowserHistory = (tabId: string, direction: -1 | 1) => {
    updateBrowserTab(tabId, (browser) => {
      const historyIndex = browser.historyIndex + direction;
      const currentUrl = browser.history[historyIndex] ?? browser.currentUrl;
      return {
        ...browser,
        historyIndex,
        currentUrl,
        draftUrl: currentUrl,
      };
    });
  };

  const refreshBrowser = (tabId: string) => {
    updateBrowserTab(tabId, (browser) => ({ ...browser, refreshKey: browser.refreshKey + 1 }));
  };

  return (
    <aside className="flex h-full w-[min(430px,calc(100vw-64px))] flex-col bg-popover">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-glass-border/25 bg-card/80 px-3">
        <PanelRightClose className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-foreground">Painel da Sessão</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {snapshot?.title || (conversationId ? "Sessão ativa" : "Sem conversa")}
          </div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" aria-label="Fechar painel da sessão" onClick={onClose}>
              <PanelRightClose className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Fechar</TooltipContent>
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
            onBrowserNavigate={(value) => navigateBrowser(activeTab.id, value)}
            onBrowserBack={() => moveBrowserHistory(activeTab.id, -1)}
            onBrowserForward={() => moveBrowserHistory(activeTab.id, 1)}
            onBrowserRefresh={() => refreshBrowser(activeTab.id)}
          />
        ) : !conversationId ? (
          <EmptyPanel text="Inicie ou abra uma conversa para ver dados da sessão." />
        ) : panel.isLoading ? (
          <div className="flex min-h-[220px] items-center justify-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Carregando painel
          </div>
        ) : panel.error ? (
          <EmptyPanel text={panel.error instanceof Error ? panel.error.message : String(panel.error)} />
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
            onBrowserNavigate={(value) => navigateBrowser(activeTab.id, value)}
            onBrowserBack={() => moveBrowserHistory(activeTab.id, -1)}
            onBrowserForward={() => moveBrowserHistory(activeTab.id, 1)}
            onBrowserRefresh={() => refreshBrowser(activeTab.id)}
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
    <div className="flex h-11 shrink-0 items-end border-b border-glass-border/25 bg-background/80 px-2 pt-1.5" role="tablist" aria-label="Abas do painel da sessão">
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
                  aria-label={`Fechar aba ${tab.title}`}
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
              aria-label="Nova aba do painel"
              className="mb-1 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="start" sideOffset={8} className="w-48 rounded-xl">
            <DropdownMenuLabel>Nova aba</DropdownMenuLabel>
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
          ["Arquivos", snapshot?.changed_files.length ?? 0],
          ["Fontes", snapshot?.sources.length ?? 0],
          ["Tools", usage.tool_calls.value],
          ["Planos", usage.plans_created.value],
        ]}
      />
      <UsageSection usage={usage} />
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

function FilesSection({
  files,
  onOpenDetail,
}: {
  files: ChangedFile[];
  onOpenDetail: (detail: SessionDetailView) => void;
}) {
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<FilePenLine className="h-3.5 w-3.5" />} title="Arquivos Alterados" />
      {files.length === 0 ? <EmptyList text="Nenhum arquivo alterado nesta sessão." /> : null}
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
      <SectionTitle icon={<ExternalLink className="h-3.5 w-3.5" />} title="Fontes" />
      {sources.length === 0 ? <EmptyList text="Nenhuma fonte registrada." /> : null}
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
        <EmptyList text="Projeto indisponível." />
      </section>
    );
  }
  return (
    <section className="border-t border-glass-border/25 pt-3">
      <SectionTitle icon={<GitBranch className="h-3.5 w-3.5" />} title="Project Details" />
      <div className="mt-2 space-y-4">
        <div className="space-y-1 text-xs text-muted-foreground">
          <div className="truncate">{project.repo?.name_with_owner || "Repositório não detectado"}</div>
          <div className="truncate">Branch padrão: {project.repo?.default_branch || "N/A"}</div>
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
        {items.length === 0 ? <div className="py-2 text-[11px] text-muted-foreground">Sem dados.</div> : null}
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
  onBrowserDraftChange,
  onBrowserNavigate,
  onBrowserBack,
  onBrowserForward,
  onBrowserRefresh,
}: {
  tab: BrowserTab;
  onBrowserDraftChange: (value: string) => void;
  onBrowserNavigate: (value: string) => void;
  onBrowserBack: () => void;
  onBrowserForward: () => void;
  onBrowserRefresh: () => void;
}) {
  if (isBrowserTab(tab)) {
    return (
      <BrowserTabContent
        browser={tab.browser ?? createEmptyBrowserState()}
        onDraftChange={onBrowserDraftChange}
        onNavigate={onBrowserNavigate}
        onBack={onBrowserBack}
        onForward={onBrowserForward}
        onRefresh={onBrowserRefresh}
      />
    );
  }
  if (!tab.detail) return <EmptyPanel text="Aba vazia." />;
  const detail = tab.detail;
  return (
    <div className="space-y-3">
      <div className="border-b border-glass-border/25 pb-3">
        <div className="truncate text-sm font-medium text-foreground">{detail.title}</div>
        {detail.subtitle ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{detail.subtitle}</div> : null}
        {detail.url ? (
          <a href={detail.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
            Abrir URL
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
  onDraftChange,
  onNavigate,
  onBack,
  onForward,
  onRefresh,
}: {
  browser: BrowserState;
  onDraftChange: (value: string) => void;
  onNavigate: (value: string) => void;
  onBack: () => void;
  onForward: () => void;
  onRefresh: () => void;
}) {
  const canGoBack = browser.historyIndex > 0;
  const canGoForward = browser.historyIndex >= 0 && browser.historyIndex < browser.history.length - 1;
  const canRefresh = Boolean(browser.currentUrl);
  return (
    <div className="flex min-h-[calc(100vh-170px)] flex-col">
      <div className="-mx-3 -mt-3 flex h-11 shrink-0 items-center gap-1.5 border-b border-glass-border/25 bg-background/70 px-3">
        <BrowserNavButton label="Voltar" disabled={!canGoBack} onClick={onBack}>
          {"<"}
        </BrowserNavButton>
        <BrowserNavButton label="Avançar" disabled={!canGoForward} onClick={onForward}>
          {">"}
        </BrowserNavButton>
        <BrowserNavButton label="Recarregar página" disabled={!canRefresh} onClick={onRefresh}>
          <RefreshCw className="h-3.5 w-3.5" />
        </BrowserNavButton>
        <form
          className="ml-1 min-w-0 flex-1"
          onSubmit={(event) => {
            event.preventDefault();
            onNavigate(browser.draftUrl);
          }}
        >
          <input
            aria-label="Digite sua url"
            className="h-8 w-full rounded-full border border-glass-border/35 bg-card/70 px-3 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/50 focus:bg-background"
            placeholder="digite sua url"
            value={browser.draftUrl}
            onChange={(event) => onDraftChange(event.currentTarget.value)}
          />
        </form>
      </div>
      {browser.currentUrl ? (
        <div className="-mx-3 -mb-4 min-h-0 flex-1 bg-background">
          <iframe
            key={`${browser.currentUrl}:${browser.refreshKey}`}
            title={`Browser ${browser.currentUrl}`}
            src={browser.currentUrl}
            className="h-full min-h-[calc(100vh-220px)] w-full border-0 bg-background"
          />
        </div>
      ) : (
        <div className="flex min-h-[260px] flex-1 items-center justify-center px-8 text-center text-xs leading-5 text-muted-foreground">
          Digite uma URL para abrir uma página nesta aba.
        </div>
      )}
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

function mergeUsage(snapshot: SessionUsage | undefined, live: SessionUsage): SessionUsage {
  const base = snapshot ?? emptySessionUsage();
  const next = emptySessionUsage();
  for (const key of Object.keys(next) as Array<keyof SessionUsage>) {
    next[key] = {
      value: (base[key]?.value ?? 0) + (live[key]?.value ?? 0),
      estimated: Boolean(base[key]?.estimated || live[key]?.estimated),
    };
  }
  return next;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatValue(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function labelize(value: string) {
  return value.replace(/_/g, " ");
}

function normalizeBrowserUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}
