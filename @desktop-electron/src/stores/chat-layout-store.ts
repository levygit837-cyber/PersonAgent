import { create } from "zustand";

export const MAIN_CHAT_PANE_ID = "main";
export const MAX_CHAT_PANES = 4;
export const CHAT_SESSION_DRAG_MIME = "application/personagent-conversation";

export interface ChatPane {
  id: string;
  conversationId: string;
  workspaceRoot?: string | null;
  title?: string;
  mode: "split";
  createdAt: number;
}

interface AddPaneInput {
  conversationId: string;
  workspaceRoot?: string | null;
  title?: string;
}

interface ChatLayoutState {
  panes: ChatPane[];
  activePaneId: string;
  addPane: (input: AddPaneInput) => string;
  focusPane: (paneId: string) => void;
  closePane: (paneId: string) => void;
  closeAllSplitPanes: () => void;
}

function paneIdForConversation(conversationId: string) {
  return `pane:${conversationId}`;
}

export const useChatLayoutStore = create<ChatLayoutState>((set, get) => ({
  panes: [],
  activePaneId: MAIN_CHAT_PANE_ID,

  addPane: (input) => {
    const conversationId = input.conversationId.trim();
    if (!conversationId) return get().activePaneId;
    const existing = get().panes.find((pane) => pane.conversationId === conversationId);
    if (existing) {
      set({ activePaneId: existing.id });
      return existing.id;
    }

    const pane: ChatPane = {
      id: paneIdForConversation(conversationId),
      conversationId,
      workspaceRoot: input.workspaceRoot?.trim() || undefined,
      title: input.title?.trim() || undefined,
      mode: "split",
      createdAt: Date.now(),
    };

    set((state) => {
      const maxExtraPanes = MAX_CHAT_PANES - 1;
      const panes = [...state.panes, pane].slice(-maxExtraPanes);
      return { panes, activePaneId: pane.id };
    });
    return pane.id;
  },

  focusPane: (paneId) => set({ activePaneId: paneId }),

  closePane: (paneId) =>
    set((state) => {
      const panes = state.panes.filter((pane) => pane.id !== paneId);
      const activePaneId = state.activePaneId === paneId ? MAIN_CHAT_PANE_ID : state.activePaneId;
      return { panes, activePaneId };
    }),

  closeAllSplitPanes: () => set({ panes: [], activePaneId: MAIN_CHAT_PANE_ID }),
}));
