import { useEffect, useMemo, useState, type DragEvent, type MouseEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  GitPullRequest,
  MessageSquare,
  Plug,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { deleteConversation, listConversations } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { CHAT_SESSION_DRAG_MIME, MAIN_CHAT_PANE_ID, useChatLayoutStore } from "../../stores/chat-layout-store";
import { compactPath, workspaceName } from "../../lib/utils";
import type { ConversationStatus } from "../../../types/chat";
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

function getConversationTimestamp(conversation: import("../../../types/chat").ConversationSummary) {
  for (const value of [conversation.updated_at, conversation.created_at]) {
    const timestamp = Date.parse(value);
    if (Number.isFinite(timestamp)) return timestamp;
  }
  return 0;
}

function compareConversationsByRecency(
  left: import("../../../types/chat").ConversationSummary,
  right: import("../../../types/chat").ConversationSummary,
) {
  return getConversationTimestamp(right) - getConversationTimestamp(left);
}

interface WorkspaceGroup {
  workspace: string;
  name: string;
  conversations: import("../../../types/chat").ConversationSummary[];
}

function getWorkspaceGroupTimestamp(group: WorkspaceGroup) {
  return group.conversations.reduce(
    (latest, conversation) => Math.max(latest, getConversationTimestamp(conversation)),
    0,
  );
}

function compareWorkspaceGroupsByRecency(left: WorkspaceGroup, right: WorkspaceGroup) {
  return getWorkspaceGroupTimestamp(right) - getWorkspaceGroupTimestamp(left);
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
    const byWorkspace = new Map<string, import("../../../types/chat").ConversationSummary[]>();

    for (const conv of all) {
      const ws = workspaceForConversation(conv, convWorkspaceMap, selectedWorkspace);
      if (ws) {
        const list = byWorkspace.get(ws) ?? [];
        list.push(conv);
        byWorkspace.set(ws, list);
      }
    }

    const groups: WorkspaceGroup[] = Array.from(byWorkspace.entries()).map(([ws, convs]) => ({
      workspace: ws,
      name: workspaceName(ws) ?? ws,
      conversations: [...convs].sort(compareConversationsByRecency),
    })).sort(compareWorkspaceGroupsByRecency);

    return { groups };
  }, [conversations.data, convWorkspaceMap, selectedWorkspace]);

  return { groups, isLoading: conversations.isLoading, baseUrl };
}

function workspaceForConversation(
  conversation: import("../../../types/chat").ConversationSummary,
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
  const conversationStatuses = useChatStore((state) => state.conversationStatuses);
  const splitPanes = useChatLayoutStore((state) => state.panes);
  const addPane = useChatLayoutStore((state) => state.addPane);
  const focusPane = useChatLayoutStore((state) => state.focusPane);
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
  const splitConversationIds = useMemo(() => new Set(splitPanes.map((pane) => pane.conversationId)), [splitPanes]);

  const addConversationToSplit = (
    conversation: import("../../../types/chat").ConversationSummary,
    workspaceRoot: string,
  ) => {
    if (conversation.id === useChatStore.getState().conversationId) {
      focusPane(MAIN_CHAT_PANE_ID);
      return;
    }
    addPane({
      conversationId: conversation.id,
      workspaceRoot,
      title: conversation.title,
    });
    setSection("chat");
  };

  const openCompactWindow = (
    conversation: import("../../../types/chat").ConversationSummary,
    workspaceRoot: string,
  ) => {
    void window.personAgent?.compact.openSession({
      conversationId: conversation.id,
      workspaceRoot,
      title: conversation.title || "Untitled",
    });
  };

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
                    workspaceRoot={group.workspace}
                    active={conversation.id === activeConversationId || conversation.id === loadingConversationId || splitConversationIds.has(conversation.id)}
                    loading={conversation.id === loadingConversationId}
                    status={conversationStatuses[conversation.id] ?? conversation.status ?? "idle"}
                    baseUrl={baseUrl}
                    onLoad={() => { setSection("chat"); focusPane(MAIN_CHAT_PANE_ID); void loadConversation(conversation.id, group.workspace); }}
                    onAddToSplit={() => addConversationToSplit(conversation, group.workspace)}
                    onCompactWindow={() => openCompactWindow(conversation, group.workspace)}
                    queryClient={queryClient}
                  />
                ))}
                {group.conversations.length > MAX_VISIBLE_CONVERSATIONS ? (
                  <MoreSessionsDropdown
                    workspaceName={group.name}
                    conversations={group.conversations.slice(MAX_VISIBLE_CONVERSATIONS)}
                    activeConversationId={activeConversationId ?? null}
                    loadingConversationId={loadingConversationId ?? null}
                    splitConversationIds={splitConversationIds}
                    conversationStatuses={conversationStatuses}
                    workspaceRoot={group.workspace}
                    onLoadConversation={(conversationId) => {
                      setSection("chat");
                      focusPane(MAIN_CHAT_PANE_ID);
                      void loadConversation(conversationId, group.workspace);
                    }}
                    onAddToSplit={(conversation) => addConversationToSplit(conversation, group.workspace)}
                    onCompactWindow={(conversation) => openCompactWindow(conversation, group.workspace)}
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
  splitConversationIds,
  conversationStatuses,
  workspaceRoot,
  onLoadConversation,
  onAddToSplit,
  onCompactWindow,
}: {
  workspaceName: string;
  conversations: import("../../../types/chat").ConversationSummary[];
  activeConversationId: string | null;
  loadingConversationId: string | null;
  splitConversationIds: Set<string>;
  conversationStatuses: Record<string, ConversationStatus>;
  workspaceRoot: string;
  onLoadConversation: (conversationId: string) => void;
  onAddToSplit: (conversation: import("../../../types/chat").ConversationSummary) => void;
  onCompactWindow: (conversation: import("../../../types/chat").ConversationSummary) => void;
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
          {conversations.map((conversation) => {
            const active = conversation.id === activeConversationId || splitConversationIds.has(conversation.id);
            const status = conversationStatuses[conversation.id] ?? conversation.status ?? "idle";
            return (
              <ConversationMenu
                key={conversation.id}
                conversation={conversation}
                workspaceRoot={workspaceRoot}
                onOpen={() => onLoadConversation(conversation.id)}
                onAddToSplit={() => onAddToSplit(conversation)}
                onCompactWindow={() => onCompactWindow(conversation)}
              >
                <DropdownMenuItem
                  onClick={() => onLoadConversation(conversation.id)}
                  disabled={conversation.id === loadingConversationId}
                  className="gap-2 rounded-lg"
                >
                  <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{conversation.title || "Untitled"}</span>
                  <ConversationStatusIndicator status={status} compact />
                  {active || conversation.id === loadingConversationId ? (
                    <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-widest text-primary">
                      {conversation.id === loadingConversationId ? "Opening" : active ? "Visible" : "Current"}
                    </span>
                  ) : null}
                </DropdownMenuItem>
              </ConversationMenu>
            );
          })}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ConversationItem({
  conversation,
  workspaceRoot,
  active,
  loading,
  status,
  baseUrl,
  onLoad,
  onAddToSplit,
  onCompactWindow,
  queryClient,
}: {
  conversation: import("../../../types/chat").ConversationSummary;
  workspaceRoot: string;
  active: boolean;
  loading: boolean;
  status: ConversationStatus;
  baseUrl: string;
  onLoad: () => void;
  onAddToSplit: () => void;
  onCompactWindow: () => void;
  queryClient: ReturnType<typeof useQueryClient>;
}) {
  return (
    <ConversationMenu
      conversation={conversation}
      workspaceRoot={workspaceRoot}
      onOpen={onLoad}
      onAddToSplit={onAddToSplit}
      onCompactWindow={onCompactWindow}
      onDelete={async () => {
        await deleteConversation(baseUrl, conversation.id);
        await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }}
    >
      <div
        draggable
        onDragStart={(event) => setConversationDragPayload(event, conversation, workspaceRoot)}
        className={
          active
            ? "group flex w-full items-center gap-2 rounded-xl bg-accent/80 px-2 py-1.5 text-left text-[12px] text-foreground shadow-soft"
            : "group flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-[12px] text-muted-foreground hover:bg-glass/70 hover:text-foreground"
        }
      >
        <button
          type="button"
          onClick={onLoad}
          disabled={loading}
          aria-busy={loading}
          className="flex min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-wait disabled:opacity-70"
        >
          <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{conversation.title || "Untitled"}</span>
          <ConversationStatusIndicator status={loading ? "running" : status} />
        </button>
        <button
          type="button"
          aria-label="Delete conversation"
          onClick={async () => {
            await deleteConversation(baseUrl, conversation.id);
            await queryClient.invalidateQueries({ queryKey: ["conversations"] });
          }}
          className="shrink-0 rounded-md p-0.5 opacity-0 text-muted-foreground transition-opacity hover:bg-glass/60 hover:text-destructive focus:opacity-100 group-hover:opacity-100"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    </ConversationMenu>
  );
}

function ConversationStatusIndicator({
  status,
  compact = false,
}: {
  status: ConversationStatus;
  compact?: boolean;
}) {
  if (status === "idle") return null;

  const labelByStatus: Record<Exclude<ConversationStatus, "idle">, string> = {
    error: "Error in last request",
    pending: "Pending approval",
    running: "Agent running",
  };

  return (
    <span
      aria-label={labelByStatus[status]}
      title={labelByStatus[status]}
      data-status={status}
      className={[
        "personagent-session-status shrink-0",
        compact ? "h-2.5 w-2.5" : "h-3 w-3",
      ].join(" ")}
    />
  );
}

function setConversationDragPayload(
  event: DragEvent<HTMLElement>,
  conversation: import("../../../types/chat").ConversationSummary,
  workspaceRoot: string,
) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData(
    CHAT_SESSION_DRAG_MIME,
    JSON.stringify({
      conversationId: conversation.id,
      workspaceRoot,
      title: conversation.title || "Untitled",
    }),
  );
  event.dataTransfer.setData("text/plain", conversation.title || conversation.id);
}

function ConversationMenu({
  conversation,
  workspaceRoot,
  onOpen,
  onAddToSplit,
  onCompactWindow,
  onDelete,
  children,
}: {
  conversation: import("../../../types/chat").ConversationSummary;
  workspaceRoot: string;
  onOpen: () => void;
  onAddToSplit: () => void;
  onCompactWindow: () => void;
  onDelete?: () => void | Promise<void>;
  children: ReactNode;
}) {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);

  const close = () => setPosition(null);
  const run = (action: () => void | Promise<void>) => {
    close();
    void action();
  };

  return (
    <div
      draggable
      onContextMenu={(event: MouseEvent) => {
        event.preventDefault();
        setPosition({ x: event.clientX, y: event.clientY });
      }}
      onDragStart={(event) => setConversationDragPayload(event, conversation, workspaceRoot)}
    >
      {children}
      {position ? (
        <>
          <button type="button" aria-label="Close session menu" className="fixed inset-0 z-[70] cursor-default" onClick={close} />
          <div
            role="menu"
            className="fixed z-[71] min-w-44 overflow-hidden rounded-xl border border-glass-border/35 bg-popover/98 p-1 text-xs text-popover-foreground shadow-floating backdrop-blur-xl"
            style={{ left: position.x, top: position.y }}
          >
            <button type="button" role="menuitem" className="flex w-full items-center rounded-lg px-2 py-1.5 text-left hover:bg-glass/80" onClick={() => run(onOpen)}>
              Open
            </button>
            <button type="button" role="menuitem" className="flex w-full items-center rounded-lg px-2 py-1.5 text-left hover:bg-glass/80" onClick={() => run(onAddToSplit)}>
              Add to split
            </button>
            <button type="button" role="menuitem" className="flex w-full items-center rounded-lg px-2 py-1.5 text-left hover:bg-glass/80" onClick={() => run(onCompactWindow)}>
              Compact window
            </button>
            {onDelete ? (
              <>
                <div className="my-1 h-px bg-glass-border/30" />
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center rounded-lg px-2 py-1.5 text-left text-destructive hover:bg-destructive/10"
                  onClick={() => run(onDelete)}
                >
                  Delete
                </button>
              </>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

