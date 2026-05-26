import { useState, type DragEvent, type MouseEvent, type ReactNode } from "react";
import type { ConversationSummary } from "../../../../types/chat";
import { CHAT_SESSION_DRAG_MIME } from "../../../../stores/chat-layout-store";

export function setConversationDragPayload(
  event: DragEvent<HTMLElement>,
  conversation: ConversationSummary,
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

export function ConversationMenu({
  conversation,
  workspaceRoot,
  onOpen,
  onAddToSplit,
  onCompactWindow,
  onDelete,
  children,
}: {
  conversation: ConversationSummary;
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
