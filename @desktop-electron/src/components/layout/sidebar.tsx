import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  MessageSquare,
  Plug,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { deleteConversation, listConversations } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { compactPath, workspaceName } from "../../lib/utils";
import { Button } from "../ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

const MAX_VISIBLE_CONVERSATIONS = 4;

export function Sidebar() {
  const collapsed = useAppStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);
  const setSection = useAppStore((state) => state.setSection);
  const section = useAppStore((state) => state.section);

  if (collapsed) {
    return (
      <aside className="hidden w-12 shrink-0 flex-col items-center border-r border-glass-border/25 bg-card/95 py-2.5 min-[720px]:flex">
        <div className="mb-3 grid h-6 w-6 place-items-center rounded-lg bg-primary/15 text-[10px] font-bold text-primary">
          P
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="iconSm" className="mb-1" aria-label="New chat" onClick={() => { setSection("chat"); useChatStore.getState().startNewConversation(); }}>
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">New Chat</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={section === "skills" ? "secondary" : "ghost"}
              size="iconSm"
              className="mb-1"
              aria-label="Skills"
              onClick={() => setSection("skills")}
            >
              <Sparkles className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">Skills</TooltipContent>
        </Tooltip>
        <div className="mt-auto">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="iconSm" onClick={toggleSidebar}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Expand</TooltipContent>
          </Tooltip>
        </div>
      </aside>
    );
  }

  return (
    <aside className="hidden w-[240px] shrink-0 flex-col border-r border-glass-border/25 bg-card/95 min-[720px]:flex">
      <SidebarHeader />
      <SidebarActions />
      <SessionList />
      <SidebarFooter />
    </aside>
  );
}

function SidebarHeader() {
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const recent = useAppStore((state) => state.recentWorkspaces);
  const selectWorkspace = useAppStore((state) => state.selectWorkspace);
  const pickWorkspace = useAppStore((state) => state.pickWorkspace);

  return (
    <div className="flex items-center gap-2 border-b border-glass-border/25 px-2.5 py-2">
      <div className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-primary/15 text-[10px] font-bold text-primary">
        P
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className="flex min-w-0 flex-1 items-center gap-1 rounded-lg px-1.5 py-1 text-left hover:bg-glass/80"
          >
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
              {selectedWorkspace ? workspaceName(selectedWorkspace) : "PersonAgent"}
            </span>
            <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="personagent-dropdown-fade w-64">
          <DropdownMenuLabel className="text-[10px]">Workspace</DropdownMenuLabel>
          {selectedWorkspace ? (
            <DropdownMenuItem disabled className="flex-col items-start gap-0.5 text-[11px]">
              <span className="max-w-full truncate font-medium text-foreground">{workspaceName(selectedWorkspace)}</span>
              <span className="max-w-full truncate text-muted-foreground">{compactPath(selectedWorkspace)}</span>
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="text-[10px]">Recent</DropdownMenuLabel>
          {recent.length === 0 ? (
            <DropdownMenuItem disabled className="text-[11px]">No recent workspaces</DropdownMenuItem>
          ) : null}
          {recent.map((path) => (
            <DropdownMenuItem key={path} onClick={() => void selectWorkspace(path)} className="text-[12px]">
              <FolderOpen className="mr-1.5 h-3 w-3 text-muted-foreground" />
              <span className="truncate">{workspaceName(path)}</span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void pickWorkspace()} className="text-[12px]">
            <FolderOpen className="mr-1.5 h-3 w-3 text-muted-foreground" />
            Select workspace…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button variant="ghost" size="iconSm" aria-label="Collapse sidebar" onClick={toggleSidebar} className="shrink-0">
        <ChevronLeft className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function SidebarActions() {
  const setSection = useAppStore((state) => state.setSection);
  const section = useAppStore((state) => state.section);
  const startNewConversation = useChatStore((state) => state.startNewConversation);

  return (
    <div className="space-y-0.5 px-2 py-2">
      <button
        type="button"
        onClick={() => { setSection("chat"); startNewConversation(); }}
        className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-glass/80 hover:text-foreground"
      >
        <Plus className="h-3.5 w-3.5" />
        <span>New Chat</span>
      </button>
      <button
        type="button"
        onClick={() => setSection("skills")}
        className={
          section === "skills"
            ? "flex w-full items-center gap-2 rounded-xl bg-accent/80 px-2 py-1.5 text-[13px] text-foreground shadow-soft"
            : "flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-[13px] text-muted-foreground hover:bg-glass/80 hover:text-foreground"
        }
      >
        <Sparkles className="h-3.5 w-3.5" />
        <span>Skills</span>
      </button>
    </div>
  );
}

function getConversationTimestamp(conversation: import("../../types/chat").ConversationSummary) {
  for (const value of [conversation.updated_at, conversation.created_at]) {
    const timestamp = Date.parse(value);
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return 0;
}

function compareConversationsByRecency(
  left: import("../../types/chat").ConversationSummary,
  right: import("../../types/chat").ConversationSummary,
) {
  return getConversationTimestamp(right) - getConversationTimestamp(left);
}

interface WorkspaceGroup {
  workspace: string;
  name: string;
  conversations: import("../../types/chat").ConversationSummary[];
}

function useGroupedConversations() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const convWorkspaceMap = useAppStore((state) => state.convWorkspaceMap);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const queryClient = useQueryClient();

  const conversations = useQuery({
    queryKey: ["conversations", baseUrl],
    queryFn: () => listConversations(baseUrl),
    enabled: Boolean(baseUrl),
  });

  useEffect(() => {
    const handler = () => void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    window.addEventListener("personagent:conversations-changed", handler);
    return () => window.removeEventListener("personagent:conversations-changed", handler);
  }, [queryClient]);

  const { groups } = useMemo(() => {
    const all = conversations.data ?? [];
    const byWorkspace = new Map<string, import("../../types/chat").ConversationSummary[]>();

    for (const conv of all) {
      const ws = workspaceForConversation(conv, convWorkspaceMap, selectedWorkspace);
      if (ws) {
        const list = byWorkspace.get(ws) ?? [];
        list.push(conv);
        byWorkspace.set(ws, list);
      }
    }

    // Preserve API list order. Opening a session changes selectedWorkspace, and sorting by it makes folders jump.
    const groups: WorkspaceGroup[] = Array.from(byWorkspace.entries()).map(([ws, convs]) => ({
      workspace: ws,
      name: workspaceName(ws) ?? ws,
      conversations: [...convs].sort(compareConversationsByRecency),
    }));

    return { groups };
  }, [conversations.data, convWorkspaceMap, selectedWorkspace]);

  return { groups, isLoading: conversations.isLoading, baseUrl };
}

function workspaceForConversation(
  conversation: import("../../types/chat").ConversationSummary,
  convWorkspaceMap: Record<string, string>,
  selectedWorkspace?: string,
) {
  const mapped = convWorkspaceMap[conversation.id]?.trim();
  if (mapped) return mapped;
  const fromBackend = conversation.workspace_root?.trim();
  if (fromBackend) return fromBackend;
  return selectedWorkspace?.trim();
}

function SessionList() {
  const { groups, isLoading, baseUrl } = useGroupedConversations();
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const setSection = useAppStore((state) => state.setSection);
  const loadConversation = useChatStore((state) => state.loadConversation);
  const activeConversationId = useChatStore((state) => state.conversationId);
  const loadingConversationId = useChatStore((state) => state.loadingConversationId);
  const queryClient = useQueryClient();

  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(() => new Set(selectedWorkspace ? [selectedWorkspace] : []));

  useEffect(() => {
    if (selectedWorkspace) {
      setExpandedFolders((prev) => {
        if (prev.has(selectedWorkspace)) return prev;
        return new Set([...prev, selectedWorkspace]);
      });
    }
  }, [selectedWorkspace]);

  const toggleFolder = (ws: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(ws)) next.delete(ws);
      else next.add(ws);
      return next;
    });
  };

  const totalCount = groups.reduce((sum, g) => sum + g.conversations.length, 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col px-2">
      <div className="mb-1 flex shrink-0 items-center gap-2 px-2">
        <span className="min-w-0 flex-1 text-[9px] font-semibold uppercase tracking-widest text-muted-foreground">
          Chats
        </span>
      </div>
      <div data-testid="session-history-list" className="min-h-0 flex-1 overflow-y-auto">
        {groups.map((group) => (
          <div key={group.workspace} className="mb-1">
            <button
              type="button"
              aria-label={`${expandedFolders.has(group.workspace) ? "Collapse" : "Expand"} workspace folder ${group.name}`}
              onClick={() => toggleFolder(group.workspace)}
              className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left hover:bg-glass/80"
            >
              <ChevronRight
                className={`h-2.5 w-2.5 shrink-0 text-muted-foreground transition-transform duration-150 ${expandedFolders.has(group.workspace) ? "rotate-90" : ""}`}
              />
              <FolderOpen className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-muted-foreground">
                {group.name}
              </span>
              <span className="text-[10px] tabular-nums text-muted-foreground/60">{group.conversations.length}</span>
            </button>
            {expandedFolders.has(group.workspace) ? (
              <div className="ml-3 space-y-px border-l border-glass-border/20 pl-1.5 pt-0.5">
                {group.conversations.slice(0, MAX_VISIBLE_CONVERSATIONS).map((conversation) => (
                  <ConversationItem
                    key={conversation.id}
                    conversation={conversation}
                    active={conversation.id === activeConversationId || conversation.id === loadingConversationId}
                    loading={conversation.id === loadingConversationId}
                    baseUrl={baseUrl}
                    onLoad={() => { setSection("chat"); void loadConversation(conversation.id, group.workspace); }}
                    queryClient={queryClient}
                  />
                ))}
                {group.conversations.length > MAX_VISIBLE_CONVERSATIONS ? (
                  <MoreSessionsDropdown
                    workspaceName={group.name}
                    conversations={group.conversations.slice(MAX_VISIBLE_CONVERSATIONS)}
                    activeConversationId={activeConversationId ?? null}
                    loadingConversationId={loadingConversationId ?? null}
                    onLoadConversation={(conversationId) => {
                      setSection("chat");
                      void loadConversation(conversationId, group.workspace);
                    }}
                  />
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
        {isLoading ? (
          <div className="px-2 py-2 text-[11px] text-muted-foreground">Loading…</div>
        ) : null}
        {!isLoading && totalCount === 0 ? (
          <div className="px-2 py-2 text-[11px] text-muted-foreground">No chats yet</div>
        ) : null}
      </div>
    </div>
  );
}

function MoreSessionsDropdown({
  workspaceName,
  conversations,
  activeConversationId,
  loadingConversationId,
  onLoadConversation,
}: {
  workspaceName: string;
  conversations: import("../../types/chat").ConversationSummary[];
  activeConversationId: string | null;
  loadingConversationId: string | null;
  onLoadConversation: (conversationId: string) => void;
}) {
  const remainingCount = conversations.length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="subtle"
          size="xs"
          aria-label={`Show more sessions from ${workspaceName}`}
          title={`Show more sessions from ${workspaceName}`}
          className="mt-1 h-7 w-full justify-between rounded-xl border-glass-border/30 bg-background/[0.35] px-2 text-[11px] font-medium text-muted-foreground hover:border-glass-border/45 hover:bg-glass/80 hover:text-foreground data-[state=open]:border-primary/35 data-[state=open]:bg-glass data-[state=open]:text-foreground"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <ChevronDown className="h-3 w-3 shrink-0" />
            <span className="truncate">More sessions</span>
          </span>
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
            +{remainingCount}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="start" sideOffset={8} className="personagent-dropdown-fade w-72 rounded-xl">
        <DropdownMenuLabel>Additional sessions</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="max-h-72 overflow-y-auto">
          {conversations.map((conversation) => (
            <DropdownMenuItem
              key={conversation.id}
              onClick={() => onLoadConversation(conversation.id)}
              disabled={conversation.id === loadingConversationId}
              className="gap-2 rounded-lg"
            >
              <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{conversation.title || "Untitled"}</span>
              {conversation.id === activeConversationId || conversation.id === loadingConversationId ? (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-primary">
                  {conversation.id === loadingConversationId ? "Opening" : "Current"}
                </span>
              ) : null}
            </DropdownMenuItem>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ConversationItem({
  conversation,
  active,
  loading,
  baseUrl,
  onLoad,
  queryClient,
}: {
  conversation: import("../../types/chat").ConversationSummary;
  active: boolean;
  loading: boolean;
  baseUrl: string;
  onLoad: () => void;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  return (
    <button
      type="button"
      onClick={onLoad}
      disabled={loading}
      aria-busy={loading}
      className={
        active
          ? "group flex w-full items-center gap-2 rounded-xl bg-accent/80 px-2 py-1.5 text-left text-[12px] text-foreground shadow-soft"
          : "group flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-[12px] text-muted-foreground hover:bg-glass/70 hover:text-foreground"
      }
    >
      <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate">{conversation.title || "Untitled"}</span>
      <button
        type="button"
        aria-label="Delete conversation"
        onClick={async (event) => {
          event.stopPropagation();
          await deleteConversation(baseUrl, conversation.id);
          await queryClient.invalidateQueries({ queryKey: ["conversations"] });
        }}
        className="opacity-0 text-muted-foreground hover:text-destructive group-hover:opacity-100"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </button>
  );
}

function SidebarFooter() {
  const [mcpOpen, setMcpOpen] = useState(false);

  return (
    <div className="shrink-0 border-t border-glass-border/25 px-2 py-1.5">
      <CollapsibleSection
        label="MCP Connections"
        count={0}
        open={mcpOpen}
        onToggle={() => setMcpOpen(!mcpOpen)}
      >
        <div data-testid="mcp-connections-region" className="px-2 pb-1">
          <div className="flex items-start gap-2 py-1">
            <Plug className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <div className="text-[12px] font-medium text-foreground">No connections</div>
              <div className="text-[11px] leading-4 text-muted-foreground">Backend MCP not available.</div>
            </div>
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
}

function CollapsibleSection({
  label,
  count,
  open,
  onToggle,
  children,
}: {
  label: string;
  count?: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left hover:bg-glass/80"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-150 ${open ? "rotate-90" : ""}`}
        />
        <span className="min-w-0 flex-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          {label}
        </span>
        {count != null ? (
          <span className="text-[10px] tabular-nums text-muted-foreground">{count}</span>
        ) : null}
      </button>
      {open ? children : null}
    </div>
  );
}
