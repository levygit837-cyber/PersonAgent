import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "../ui/tooltip";
import { Sidebar } from "./sidebar";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { CHAT_SESSION_DRAG_MIME, MAIN_CHAT_PANE_ID, useChatLayoutStore } from "../../stores/chat-layout-store";

const originalLoadConversation = useChatStore.getState().loadConversation;

describe("Sidebar", () => {
  const deprecatedSectionLabel = ["L", "ab"].join("");

  beforeEach(() => {
    delete window.personAgent;
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
    useChatStore.setState({
      conversationId: undefined,
      loadConversation: originalLoadConversation,
    });
    useChatLayoutStore.setState({ panes: [], activePaneId: MAIN_CHAT_PANE_ID });

  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows four recent sessions by default and reveals the rest in a dropdown", async () => {
    renderSidebar();

    expect(screen.getByText("New Chat")).toBeInTheDocument();
    expect(screen.queryByText(deprecatedSectionLabel)).not.toBeInTheDocument();
    expect(screen.getByText("Chats")).toBeInTheDocument();

    expect(await screen.findByText("my-project")).toBeInTheDocument();
    expect(await screen.findByText("other-project")).toBeInTheDocument();

    expect(screen.getByText("Debug Session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /other-project/i }));

    for (const title of ["Long History 1", "Long History 2", "Long History 3", "Long History 4"]) {
      expect(await screen.findByText(title)).toBeInTheDocument();
    }

    expect(screen.queryByText("Long History 5")).not.toBeInTheDocument();
    const moreSessionsButton = screen.getByRole("button", { name: /show more sessions/i });
    expect(moreSessionsButton).toBeInTheDocument();

    fireEvent.pointerDown(moreSessionsButton);
    expect(await screen.findByText("Long History 5")).toBeInTheDocument();

    expect(screen.getByTestId("session-history-list")).toHaveClass("overflow-y-auto");
  });

  it("shows collapsible MCP section without deprecated secondary navigation", async () => {
    renderSidebar();

    expect(screen.getByText("Skills")).toBeInTheDocument();
    expect(screen.getByText("MCP Connections")).toBeInTheDocument();
    fireEvent.click(screen.getByText("MCP Connections"));
    expect(screen.getByTestId("mcp-connections-region")).toBeInTheDocument();
    expect(screen.queryByText(deprecatedSectionLabel)).not.toBeInTheDocument();
    expect(useAppStore.getState().section).toBe("chat");
  });

  it("switches to the Skills section from the sidebar", async () => {
    renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: /^skills$/i }));

    expect(useAppStore.getState().section).toBe("skills");
  });

  it("switches to the Open PR section from the expanded sidebar", async () => {
    renderSidebar();

    expect(screen.getByRole("button", { name: /open pr/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open pr/i }));

    expect(useAppStore.getState().section).toBe("openPr");
  });

  it("shows Open PR as an icon action in the collapsed sidebar", async () => {
    useAppStore.setState({ sidebarCollapsed: true });

    renderSidebar();

    const openPrButton = screen.getByRole("button", { name: /^open pr$/i });
    expect(openPrButton).toBeInTheDocument();

    fireEvent.click(openPrButton);
    expect(useAppStore.getState().section).toBe("openPr");
  });

  it("loads sessions with the workspace from their folder group", async () => {
    const loadConversation = vi.fn(async () => undefined);
    useChatStore.setState({ loadConversation });

    renderSidebar();

    fireEvent.click(await screen.findByRole("button", { name: /other-project/i }));
    fireEvent.click(await screen.findByText("Long History 1"));

    await waitFor(() => {
      expect(loadConversation).toHaveBeenCalledWith("conversation_2", "/home/user/other-project");
    });
  });

  it("adds sessions to split from the right-click menu", async () => {
    renderSidebar();

    fireEvent.contextMenu(await screen.findByText("Debug Session"));
    fireEvent.click(await screen.findByRole("menuitem", { name: /add to split/i }));

    expect(useChatLayoutStore.getState().panes).toHaveLength(1);
    expect(useChatLayoutStore.getState().panes[0]).toMatchObject({
      conversationId: "conversation_1",
      workspaceRoot: "/home/user/my-project",
      title: "Debug Session",
    });
  });

  it("opens compact windows from the right-click menu", async () => {
    const openSession = vi.fn(async () => true);
    window.personAgent = {
      compact: {
        openSession,
        getLaunchContext: vi.fn(),
      },
    } as unknown as Window["personAgent"];

    renderSidebar();

    fireEvent.contextMenu(await screen.findByText("Debug Session"));
    fireEvent.click(await screen.findByRole("menuitem", { name: /compact window/i }));

    expect(openSession).toHaveBeenCalledWith({
      conversationId: "conversation_1",
      workspaceRoot: "/home/user/my-project",
      title: "Debug Session",
    });
  });

  it("serializes sessions for drag and drop into the main workspace", async () => {
    renderSidebar();
    const data: Record<string, string> = {};
    const dataTransfer = {
      effectAllowed: "",
      setData: vi.fn((type: string, value: string) => {
        data[type] = value;
      }),
    };

    fireEvent.dragStart(await screen.findByText("Debug Session"), { dataTransfer });

    expect(dataTransfer.setData).toHaveBeenCalledWith(CHAT_SESSION_DRAG_MIME, expect.any(String));
    expect(JSON.parse(data[CHAT_SESSION_DRAG_MIME])).toMatchObject({
      conversationId: "conversation_1",
      workspaceRoot: "/home/user/my-project",
      title: "Debug Session",
    });
  });

  it("does not hide backend sessions when local workspace mapping is empty", async () => {
    useAppStore.setState({
      convWorkspaceMap: {},
      selectedWorkspace: "/home/user/my-project",
      recentWorkspaces: ["/home/user/my-project"],
    });

    renderSidebar();

    expect(await screen.findByText("my-project")).toBeInTheDocument();
    expect(await screen.findByText("Debug Session")).toBeInTheDocument();
    expect(screen.queryByText("No chats yet")).not.toBeInTheDocument();
  });

  it("uses workspace roots returned by the backend before the selected fallback", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            id: "conversation_backend",
            title: "Backend Workspace Session",
            created_at: "",
            updated_at: "",
            message_count: 1,
            workspace_root: "/home/user/backend-project",
          },
        ]),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    useAppStore.setState({
      convWorkspaceMap: {},
      selectedWorkspace: "/home/user/my-project",
      recentWorkspaces: ["/home/user/my-project"],
    });

    renderSidebar();

    expect(await screen.findByText("backend-project")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /backend-project/i }));
    expect(await screen.findByText("Backend Workspace Session")).toBeInTheDocument();
  });

  it("keeps workspace folder order stable after the selected workspace changes", async () => {
    renderSidebar();

    expect(await screen.findByText("my-project")).toBeInTheDocument();
    expect(await screen.findByText("other-project")).toBeInTheDocument();
    expect(workspaceFolderNames()).toEqual(["my-project", "other-project"]);

    await act(async () => {
      await useAppStore.getState().selectWorkspace("/home/user/other-project");
    });

    expect(workspaceFolderNames()).toEqual(["my-project", "other-project"]);
  });

  it("opens the desktop workspace picker from the workspace menu", async () => {
    const selectWorkspace = vi.fn(async () => ({ workspaceId: "wks_new", root: "/home/user/new-project" }));
    window.personAgent = {
      dialog: {
        selectWorkspace,
      },
      settings: {
        get: vi.fn(),
        set: vi.fn(async () => true),
      },
      workspace: {
        grant: vi.fn(async () => ({ workspaceId: "wks_new", root: "/home/user/new-project" })),
      },
    } as unknown as Window["personAgent"];

    renderSidebar();

    fireEvent.pointerDown(screen.getAllByRole("button", { name: /my-project/i })[0]);
    fireEvent.click(await screen.findByRole("menuitem", { name: /select workspace/i }));

    await waitFor(() => {
      expect(selectWorkspace).toHaveBeenCalledWith("/home/user/my-project");
      expect(useAppStore.getState().selectedWorkspace).toBe("/home/user/new-project");
    });
  });

  it("renders visual session state indicators", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          { id: "running_session", title: "Running Session", created_at: "", updated_at: "", message_count: 1, status: "running" },
          { id: "pending_session", title: "Pending Session", created_at: "", updated_at: "", message_count: 1, status: "pending" },
          { id: "error_session", title: "Error Session", created_at: "", updated_at: "", message_count: 1, status: "error" },
        ]),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    useAppStore.setState({
      convWorkspaceMap: {},
      selectedWorkspace: "/home/user/my-project",
      recentWorkspaces: ["/home/user/my-project"],
    });

    renderSidebar();

    expect(await screen.findByLabelText("Agent running")).toBeInTheDocument();
    expect(screen.getByLabelText("Pending approval")).toBeInTheDocument();
    expect(screen.getByLabelText("Error in last request")).toBeInTheDocument();
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

function workspaceFolderNames() {
  const history = screen.getByTestId("session-history-list");
  return within(history)
    .getAllByRole("button", { name: /workspace folder/i })
    .map((button) => button.getAttribute("aria-label")?.replace(/^(Expand|Collapse) workspace folder /, "") ?? "");
}
