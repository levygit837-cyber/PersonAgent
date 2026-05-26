import { useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Trash2 } from "lucide-react";
import { deleteConversation } from "../../../../api/client";
import type { ConversationSummary, ConversationStatus } from "../../../../types/chat";
import { ConversationMenu, setConversationDragPayload } from "./conversation-menu";
import { ConversationStatusIndicator } from "./conversation-status-indicator";

export function ConversationItem({
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
  conversation: ConversationSummary;
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
