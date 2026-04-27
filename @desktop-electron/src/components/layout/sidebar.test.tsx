import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "../ui/tooltip";
import { Sidebar } from "./sidebar";
import { useAppStore } from "../../stores/app-store";

describe("Sidebar", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const conversations = [
          { id: "conversation_1", title: "Debug Session", created_at: "", updated_at: "", message_count: 2 },
          ...Array.from({ length: 24 }, (_, index) => ({
            id: `conversation_${index + 2}`,
            title: `Long History ${index + 1}`,
            created_at: "",
            updated_at: "",
            message_count: 1,
          })),
        ];
        return new Response(JSON.stringify(conversations), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const map: Record<string, string> = { conversation_1: "/home/user/my-project" };
    for (let i = 2; i <= 25; i++) map[`conversation_${i}`] = "/home/user/other-project";

    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      apiStatus: "online",
      apiError: undefined,
      section: "chat",
      sidebarCollapsed: false,
      selectedWorkspace: "/home/user/my-project",
      recentWorkspaces: ["/home/user/my-project"],
      convWorkspaceMap: map,
    });

  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("groups chats by workspace folder", async () => {
    renderSidebar();

    expect(screen.getByText("New Chat")).toBeInTheDocument();
    expect(screen.getByText("Lab")).toBeInTheDocument();
    expect(screen.getByText("Chats")).toBeInTheDocument();

    expect(await screen.findByText("my-project")).toBeInTheDocument();
    expect(await screen.findByText("other-project")).toBeInTheDocument();

    expect(screen.getByText("Debug Session")).toBeInTheDocument();

    expect(screen.getByTestId("session-history-list")).toHaveClass("overflow-y-auto");
  });

  it("shows collapsible MCP section and Lab navigation", async () => {
    renderSidebar();

    expect(screen.getByText("MCP Connections")).toBeInTheDocument();
    fireEvent.click(screen.getByText("MCP Connections"));
    expect(screen.getByTestId("mcp-connections-region")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Lab"));
    expect(useAppStore.getState().section).toBe("lab");
  });
});

function renderSidebar() {
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
        <Sidebar />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}
