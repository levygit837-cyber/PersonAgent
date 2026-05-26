import { useEffect, useRef } from "react";
import { ChatStoreProvider, createChatStore, type ChatStoreApi } from "../../../stores/chat-store";
import { useChatLayoutStore, type ChatPane } from "../../../stores/chat-layout-store";
import { ChatPaneSurface } from "../chat-workspace";

export function ManagedSplitPane({ pane, active }: { pane: ChatPane; active: boolean }) {
  const storeRef = useRef<ChatStoreApi | null>(null);
  const closePane = useChatLayoutStore((state) => state.closePane);
  const focusPane = useChatLayoutStore((state) => state.focusPane);

  if (!storeRef.current) {
    storeRef.current = createChatStore({
      paneId: pane.id,
      initialWorkspaceRoot: pane.workspaceRoot,
      syncWorkspaceSelection: false,
    });
  }

  useEffect(() => {
    const store = storeRef.current;
    if (!store) return;
    store.getState().setWorkspaceRoot(pane.workspaceRoot);
    if (pane.conversationId && store.getState().conversationId !== pane.conversationId) {
      void store.getState().loadConversation(pane.conversationId, pane.workspaceRoot);
    }
  }, [pane.conversationId, pane.workspaceRoot]);

  return (
    <ChatStoreProvider store={storeRef.current}>
      <ChatPaneSurface
        paneId={pane.id}
        split
        active={active}
        onFocus={() => focusPane(pane.id)}
        onClose={() => closePane(pane.id)}
      />
    </ChatStoreProvider>
  );
}
