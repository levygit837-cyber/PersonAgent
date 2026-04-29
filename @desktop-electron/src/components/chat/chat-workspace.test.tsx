import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "../../stores/app-store";
import { emptySessionUsage } from "../../types/chat";
import { TooltipProvider } from "../ui/tooltip";
import { ChatWorkspace } from "./chat-workspace";
import { useChatStore } from "../../stores/chat-store";

describe("ChatWorkspace", () => {
  beforeEach(() => {
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/workspaces/test-repo-gpt-oss-120b-scale",
      recentWorkspaces: ["/workspaces/test-repo-gpt-oss-120b-scale"],
      convWorkspaceMap: {},
      section: "chat",
    });
    useChatStore.setState({
      workspaceRoot: "/workspaces/test-repo-gpt-oss-120b-scale",
      messages: [],
      composerAnnotations: [],
      conversationId: undefined,
      conversationTitle: undefined,
      error: undefined,
      isStreaming: false,
      isFinalizing: false,
      loadingConversationId: undefined,
      activeController: undefined,
      activeAgentId: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
    });
  });

  it("updates the main pane workspace when the global workspace selection changes", async () => {
    renderChatWorkspace();

    expect(screen.getAllByText("test-repo-gpt-oss-120b-scale").length).toBeGreaterThan(0);

    await act(async () => {
      await useAppStore.getState().selectWorkspace("/workspaces/Neuralilux");
    });

    expect((await screen.findAllByText("Neuralilux")).length).toBeGreaterThan(0);
    expect(screen.queryByText("test-repo-gpt-oss-120b-scale")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(useChatStore.getState().workspaceRoot).toBe("/workspaces/Neuralilux");
    });
  });
});

function renderChatWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <ChatWorkspace />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}
