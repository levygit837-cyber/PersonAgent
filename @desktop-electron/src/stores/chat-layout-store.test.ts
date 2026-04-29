import { beforeEach, describe, expect, it } from "vitest";
import { MAIN_CHAT_PANE_ID, MAX_CHAT_PANES, useChatLayoutStore } from "./chat-layout-store";

describe("chat layout store", () => {
  beforeEach(() => {
    useChatLayoutStore.setState({ panes: [], activePaneId: MAIN_CHAT_PANE_ID });
  });

  it("adds and focuses split panes by conversation", () => {
    const paneId = useChatLayoutStore.getState().addPane({
      conversationId: "conversation-1",
      workspaceRoot: "/workspace/a",
      title: "A",
    });

    expect(useChatLayoutStore.getState().activePaneId).toBe(paneId);
    expect(useChatLayoutStore.getState().panes).toHaveLength(1);
    expect(useChatLayoutStore.getState().panes[0]).toMatchObject({
      conversationId: "conversation-1",
      workspaceRoot: "/workspace/a",
      title: "A",
    });
  });

  it("focuses duplicate conversations instead of adding another pane", () => {
    const first = useChatLayoutStore.getState().addPane({ conversationId: "conversation-1" });
    const second = useChatLayoutStore.getState().addPane({ conversationId: "conversation-1" });

    expect(second).toBe(first);
    expect(useChatLayoutStore.getState().panes).toHaveLength(1);
  });

  it("keeps the total visible pane count capped at four including the main pane", () => {
    for (let index = 1; index <= MAX_CHAT_PANES + 2; index += 1) {
      useChatLayoutStore.getState().addPane({ conversationId: `conversation-${index}` });
    }

    expect(useChatLayoutStore.getState().panes).toHaveLength(MAX_CHAT_PANES - 1);
    expect(useChatLayoutStore.getState().panes.map((pane) => pane.conversationId)).toEqual([
      "conversation-4",
      "conversation-5",
      "conversation-6",
    ]);
  });

  it("returns focus to the main pane when the active split pane closes", () => {
    const paneId = useChatLayoutStore.getState().addPane({ conversationId: "conversation-1" });

    useChatLayoutStore.getState().closePane(paneId);

    expect(useChatLayoutStore.getState().panes).toEqual([]);
    expect(useChatLayoutStore.getState().activePaneId).toBe(MAIN_CHAT_PANE_ID);
  });
});
