import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getSessionPanel, getSessionProjectDetail, listChatCommands, listModels } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { emptySessionUsage, type SessionPanelSnapshot } from "../../types/chat";
import { TooltipProvider } from "../ui/tooltip";
import { ChatWorkspace } from "./chat-workspace";
import { SESSION_PANEL_CACHE_STORAGE_KEY } from "./session-panel";

vi.mock("../../api/client", () => ({
  approvePlan: vi.fn(),
  approveTool: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  getSessionPanel: vi.fn(),
  getSessionProjectDetail: vi.fn(),
  listChatCommands: vi.fn().mockResolvedValue([]),
  listWorkspaceFiles: vi.fn().mockResolvedValue([]),
  listModels: vi.fn().mockResolvedValue([]),
  readWorkspaceFile: vi.fn().mockResolvedValue({ path: "/tmp/personagent/README.md", name: "README.md", content: "# README" }),
  rejectTool: vi.fn(),
  resolveBackendUrl: vi.fn().mockResolvedValue("http://localhost:8000"),
  streamChatCompletion: vi.fn(),
  streamTeamChat: vi.fn(),
}));

const snapshot: SessionPanelSnapshot = {
  conversation_id: "conversation-1",
  title: "Debug Session",
  updated_at: "2026-04-27T10:00:00Z",
  changed_files: [
    {
      id: "file:/tmp/app.py",
      path: "/tmp/app.py",
      display_path: "app.py",
      added_lines: 12,
      removed_lines: 3,
      source: "Write",
      status: "changed",
      diff: "+print('panel')",
    },
  ],
  sources: [
    {
      id: "source:https://example.com/docs",
      title: "Example Docs",
      description: "Brief site description",
      url: "https://example.com/docs",
      domain: "example.com",
      favicon_url: "https://www.google.com/s2/favicons?domain=example.com&sz=32",
      tool_name: "WebFetch",
    },
  ],
  usage: {
    ...emptySessionUsage(),
    agent_output_tokens: { value: 42, estimated: false },
    tool_calls: { value: 3, estimated: false },
  },
  project: {
    repo: {
      name_with_owner: "levy/PersonAgent",
      url: "https://github.com/levy/PersonAgent",
      default_branch: "main",
      pushed_at: "2026-04-27T09:00:00Z",
      source: "gh",
    },
    prs: [],
    branches: [
      {
        id: "main",
        type: "branch",
        title: "main",
        subtitle: "active",
        active: true,
      },
    ],
    pushes: [],
    commits: [
      {
        id: "abc123",
        type: "commit",
        title: "feat: session panel",
        subtitle: "abc123 · Levy",
        timestamp: "2026-04-27T09:00:00Z",
      },
    ],
    errors: [],
  },
};

describe("SessionPanel", () => {
  const getSessionPanelMock = vi.mocked(getSessionPanel);
  const getSessionProjectDetailMock = vi.mocked(getSessionProjectDetail);
  const listModelsMock = vi.mocked(listModels);
  const listChatCommandsMock = vi.mocked(listChatCommands);

  beforeEach(() => {
    window.localStorage.clear();
    getSessionPanelMock.mockReset();
    getSessionPanelMock.mockResolvedValue(snapshot);
    getSessionProjectDetailMock.mockReset();
    getSessionProjectDetailMock.mockResolvedValue({
      type: "commit",
      id: "abc123",
      title: "feat: session panel",
      metadata: {
        sha: "abc123",
        message: "feat: session panel\n\nAdds the session panel shell.",
      },
      files: [{ filename: "app.py", additions: 12, deletions: 3, patch: "+print('panel')" }],
      source: "gh",
    });
    listModelsMock.mockReset();
    listModelsMock.mockResolvedValue([]);
    listChatCommandsMock.mockReset();
    listChatCommandsMock.mockResolvedValue([]);
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/tmp/personagent",
      recentWorkspaces: [],
      provider: "llama",
      selectedModelId: "local-model",
      reasoningPreset: "low",
      teamMode: false,
    });
    useChatStore.setState({
      messages: [],
      conversationId: "conversation-1",
      conversationTitle: "Debug Session",
      isStreaming: false,
      error: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
    });
  });

  it("opens and closes the persistent chat session panel button", async () => {
    renderWithProviders(<ChatWorkspace />);

    expect(screen.getAllByText("personagent").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Debug Session")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));

    expect(screen.getByRole("tab", { name: "Summary" })).toBeInTheDocument();
    expect(await screen.findByText("Agent Usage")).toBeInTheDocument();
    expect(screen.getByText("Changed Files")).toBeInTheDocument();
    expect(screen.getByText("Project Details")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close session panel" }));

    await waitFor(() => expect(screen.queryByRole("tab", { name: "Summary" })).not.toBeInTheDocument());
    expect(screen.getByTestId("session-panel-shell")).toHaveClass("w-0");
  });

  it("does not fetch the session summary while the panel is closed", async () => {
    renderWithProviders(<ChatWorkspace />);

    await waitFor(() => expect(screen.getByText("Debug Session")).toBeInTheDocument());
    expect(getSessionPanelMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(SESSION_PANEL_CACHE_STORAGE_KEY)).toBeNull();
  });

  it("opens the summary from the persisted snapshot while the background refresh is pending", async () => {
    const cachedSnapshot: SessionPanelSnapshot = {
      ...snapshot,
      title: "Cached Debug Session",
      updated_at: "2026-04-27T10:05:00Z",
      usage: {
        ...snapshot.usage,
        agent_output_tokens: { value: 99, estimated: false },
      },
    };
    window.localStorage.setItem(
      SESSION_PANEL_CACHE_STORAGE_KEY,
      JSON.stringify({
        [sessionPanelCacheKey("http://localhost:8000", "conversation-1", "/tmp/personagent")]: {
          cachedAt: Date.now() - 60_000,
          snapshot: cachedSnapshot,
        },
      }),
    );
    getSessionPanelMock.mockReturnValue(new Promise<SessionPanelSnapshot>(() => {}));

    renderWithProviders(<ChatWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));

    expect(await screen.findByText("Cached Debug Session")).toBeInTheDocument();
    expect(screen.getByText("99")).toBeInTheDocument();
    expect(getSessionPanelMock).toHaveBeenCalledWith("http://localhost:8000", "conversation-1", "/tmp/personagent");
  });

  it("opens project item details as a closeable browser tab inside the panel", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Project Details");
    fireEvent.click(await screen.findByText("feat: session panel"));

    expect(await screen.findByRole("tab", { name: "feat: session panel" })).toBeInTheDocument();
    expect(screen.getByText(/Adds the session panel shell/)).toBeInTheDocument();
    expect(getSessionProjectDetailMock).toHaveBeenCalledWith("http://localhost:8000", "conversation-1", {
      type: "commit",
      id: "abc123",
      workspaceRoot: "/tmp/personagent",
    });

    fireEvent.click(screen.getByRole("button", { name: "Close tab feat: session panel" }));
    await waitFor(() => expect(screen.queryByText(/Adds the session panel shell/)).not.toBeInTheDocument());
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens and closes an empty browser-style tab from the plus button", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveAttribute("placeholder", "enter url");
    expect(screen.getByText("Enter a URL to open a page in this tab.")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Enter URL" }), {
      target: { value: "example.com" },
    });
    fireEvent.submit(screen.getByRole("textbox", { name: "Enter URL" }).closest("form")!);

    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://example.com");
    expect(screen.getByTitle("Browser https://example.com")).toHaveAttribute("src", "https://example.com");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Close tab Browser" }));
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps browser controls visible even when there is no active conversation", async () => {
    useChatStore.setState({
      conversationId: undefined,
      conversationTitle: undefined,
      messages: [],
    });

    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    expect(screen.getByText("Start or open a conversation to view session data.")).toBeInTheDocument();

    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toBeInTheDocument();
    expect(screen.queryByText("Start or open a conversation to view session data.")).not.toBeInTheDocument();
  });
});

function renderWithProviders(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function sessionPanelCacheKey(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  return JSON.stringify([baseUrl.trim(), conversationId, workspaceRoot?.trim() || ""]);
}
