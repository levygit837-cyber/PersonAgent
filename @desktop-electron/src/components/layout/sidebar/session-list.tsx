import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FolderOpen } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { MAIN_CHAT_PANE_ID, useChatLayoutStore } from "../../stores/chat-layout-store";
import { workspaceName } from "../../lib/utils";
import { useGroupedConversations } from "./session-list/use-grouped-conversations";
import { MAX_VISIBLE_CONVERSATIONS } from "./session-list/types";
import { ConversationItem } from "./session-list/conversation-item";
import { MoreSessionsDropdown } from "./session-list/more-sessions-dropdown";

export function SessionList() {
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
