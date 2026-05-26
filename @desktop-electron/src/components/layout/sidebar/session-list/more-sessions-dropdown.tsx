import { ChevronDown, MessageSquare } from "lucide-react";
import { Button } from "../../../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../../ui/dropdown-menu";
import type { ConversationSummary, ConversationStatus } from "../../../../types/chat";
import { ConversationMenu } from "./conversation-menu";
import { ConversationStatusIndicator } from "./conversation-status-indicator";

export function MoreSessionsDropdown({
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
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  loadingConversationId: string | null;
  splitConversationIds: Set<string>;
  conversationStatuses: Record<string, ConversationStatus>;
  workspaceRoot: string;
  onLoadConversation: (conversationId: string) => void;
  onAddToSplit: (conversation: ConversationSummary) => void;
  onCompactWindow: (conversation: ConversationSummary) => void;
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
