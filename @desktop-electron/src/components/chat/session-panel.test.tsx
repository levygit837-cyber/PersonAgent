import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  actSessionBrowser,
  clickSessionBrowser,
  connectSessionBrowserCooperation,
  createSessionBrowserAnnotation,
  getSessionBrowserView,
  getSessionPanel,
  getSessionProjectDetail,
  ingestSessionBrowserEvents,
  keySessionBrowser,
  listChatCommands,
  listModels,
  moveSessionBrowserHistory,
  navigateSessionBrowser,
  reloadSessionBrowser,
  scrollSessionBrowser,
  setSessionBrowserCooperation,
  type SessionBrowserView,
} from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { emptySessionUsage, type SessionPanelSnapshot } from "../../types/chat";
import { TooltipProvider } from "../ui/tooltip";
import { ChatWorkspace } from "./chat-workspace";
import {
  SESSION_PANEL_CACHE_STORAGE_KEY,
  browserMirrorSrcDoc,
  sanitizeBrowserMirrorHtml,
} from "./session-panel";

vi.mock("../../api/client", () => ({
  actSessionBrowser: vi.fn(),
  approvePlan: vi.fn(),
  approveTool: vi.fn(),
  cancelPlan: vi.fn(),
  continuePlan: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  getGitRecentActions: vi.fn().mockResolvedValue({ is_repo: false, actions: [], errors: [] }),
  getGitStatus: vi.fn().mockResolvedValue({
    branch: "",
    ahead: 0,
    behind: 0,
    modified_count: 0,
    untracked_count: 0,
    is_dirty: false,
    remote_url: null,
  }),
  forkConversation: vi.fn(),
  clickSessionBrowser: vi.fn(),
  connectSessionBrowserCooperation: vi.fn(),
  createSessionBrowserAnnotation: vi.fn(),
  getSessionBrowserView: vi.fn(),
  getSessionPanel: vi.fn(),
  getSessionProjectDetail: vi.fn(),
  ingestSessionBrowserEvents: vi.fn(),
  generateGitCommitMessage: vi.fn().mockResolvedValue({ message: "Update workspace" }),
  gitCreateWorktree: vi.fn(),
  gitCommit: vi.fn(),
  gitOpenPr: vi.fn(),
  gitPush: vi.fn(),
  listChatCommands: vi.fn().mockResolvedValue([]),
  listWorkspaceFiles: vi.fn().mockResolvedValue([]),
  listModels: vi.fn().mockResolvedValue([]),
  keySessionBrowser: vi.fn(),
  moveSessionBrowserHistory: vi.fn(),
  navigateSessionBrowser: vi.fn(),
  readWorkspaceFile: vi.fn().mockResolvedValue({ path: "/tmp/personagent/README.md", name: "README.md", content: "# README" }),
  rejectTool: vi.fn(),
  reloadSessionBrowser: vi.fn(),
  resolveBackendUrl: vi.fn().mockResolvedValue("http://localhost:8000"),
  scrollSessionBrowser: vi.fn(),
  setSessionBrowserCooperation: vi.fn(),
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

function browserView(
  url = "about:blank",
  browserId = "browser:test",
  title = "",
  overrides: Partial<SessionBrowserView> = {},
): SessionBrowserView {
  return {
    type: "browser_view",
    browser_id: browserId,
    url,
    title,
    html: "<html><body>Example</body></html>",
    document_html: "<html><body>Example</body></html>",
    render_mode: "screenshot",
    css_fidelity: "pixel",
    element_map: [],
    annotations: [],
    timeline_events: [],
    user_agent: "Chrome",
    image_data: "iVBORw0KGgo=",
    image_mime_type: "image/png",
    screenshot_method: "playwright_page_screenshot",
    screenshot_error: "",
    viewport_width: 1024,
    viewport_height: 720,
    can_capture: true,
    ...overrides,
  };
}

describe("SessionPanel", () => {
  const getSessionBrowserViewMock = vi.mocked(getSessionBrowserView);
  const getSessionPanelMock = vi.mocked(getSessionPanel);
  const getSessionProjectDetailMock = vi.mocked(getSessionProjectDetail);
  const navigateSessionBrowserMock = vi.mocked(navigateSessionBrowser);
  const moveSessionBrowserHistoryMock = vi.mocked(moveSessionBrowserHistory);
  const reloadSessionBrowserMock = vi.mocked(reloadSessionBrowser);
  const clickSessionBrowserMock = vi.mocked(clickSessionBrowser);
  const connectSessionBrowserCooperationMock = vi.mocked(connectSessionBrowserCooperation);
  const actSessionBrowserMock = vi.mocked(actSessionBrowser);
  const createSessionBrowserAnnotationMock = vi.mocked(createSessionBrowserAnnotation);
  const keySessionBrowserMock = vi.mocked(keySessionBrowser);
  const scrollSessionBrowserMock = vi.mocked(scrollSessionBrowser);
  const setSessionBrowserCooperationMock = vi.mocked(setSessionBrowserCooperation);
  const listModelsMock = vi.mocked(listModels);
  const listChatCommandsMock = vi.mocked(listChatCommands);

  beforeEach(() => {
    window.localStorage.clear();
    getSessionBrowserViewMock.mockReset();
    getSessionBrowserViewMock.mockResolvedValue(browserView());
    navigateSessionBrowserMock.mockReset();
    navigateSessionBrowserMock.mockImplementation(async (_baseUrl, browserId, input) =>
      browserView(input.url, browserId, "Example Domain"),
    );
    moveSessionBrowserHistoryMock.mockReset();
    moveSessionBrowserHistoryMock.mockImplementation(async (_baseUrl, browserId, input) =>
      browserView(input.direction < 0 ? "https://example.com" : "https://example.org", browserId, "Example Domain"),
    );
    reloadSessionBrowserMock.mockReset();
    reloadSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.org", browserId, "Example Domain"),
    );
    clickSessionBrowserMock.mockReset();
    clickSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com/clicked", browserId, "Clicked"),
    );
    connectSessionBrowserCooperationMock.mockReset();
    connectSessionBrowserCooperationMock.mockReturnValue({
      readyState: WebSocket.CLOSED,
      close: vi.fn(),
      send: vi.fn(),
    } as unknown as WebSocket);
    actSessionBrowserMock.mockReset();
    actSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com/action", browserId, "Action"),
    );
    createSessionBrowserAnnotationMock.mockReset();
    createSessionBrowserAnnotationMock.mockResolvedValue({
      annotation: {
        id: "ann_test",
        browser_id: "conversation-1",
        node_id: "pa_test",
        body: "note",
        created_at: "2026-04-27T10:00:00Z",
      },
      annotations: [],
      timeline_events: [],
    });
    keySessionBrowserMock.mockReset();
    keySessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com", browserId, "Example Domain"),
    );
    scrollSessionBrowserMock.mockReset();
    scrollSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com", browserId, "Example Domain"),
    );
    setSessionBrowserCooperationMock.mockReset();
    setSessionBrowserCooperationMock.mockResolvedValue({
      cooperation: { enabled: true, mode: "observe_only", agent_control: "observe_only", browser_id: "conversation-1" },
      state_patch: {
        cooperation: { enabled: true, mode: "observe_only", agent_control: "observe_only", browser_id: "conversation-1" },
      },
    });
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

  it("resizes the session panel from the left border and shows the active drag state", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));

    await screen.findByText("Agent Usage");

    const shell = screen.getByTestId("session-panel-shell");
    const handle = screen.getByTestId("session-panel-resize-handle");
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    const originalWidth = window.innerWidth - 430;
    const resizedWidth = window.innerWidth - 400;
    const pointerId = 1;

    Object.defineProperty(handle, "setPointerCapture", {
      configurable: true,
      value: setPointerCapture,
    });
    Object.defineProperty(handle, "releasePointerCapture", {
      configurable: true,
      value: releasePointerCapture,
    });

    expect(shell).toHaveStyle({ width: "430px" });
    expect(handle).toHaveAttribute("data-resizing", "false");

    fireEvent.pointerDown(handle, { button: 0, clientX: originalWidth, pointerId });

    expect(shell).toHaveAttribute("data-resizing", "true");
    expect(handle).toHaveAttribute("data-resizing", "true");
    expect(setPointerCapture).toHaveBeenCalledWith(pointerId);

    fireEvent.pointerMove(window, { clientX: 400, pointerId });

    await waitFor(() => expect(shell).toHaveStyle({ width: `${resizedWidth}px` }));

    fireEvent.pointerUp(window, { clientX: 400, pointerId });

    await waitFor(() => expect(handle).toHaveAttribute("data-resizing", "false"));
    expect(shell).toHaveAttribute("data-resizing", "false");
    expect(releasePointerCapture).toHaveBeenCalledWith(pointerId);
  });

  it("does not fetch the session summary while the panel is closed", async () => {
    renderWithProviders(<ChatWorkspace />);

    await waitFor(() => expect(screen.getByText("Debug Session")).toBeInTheDocument());
    expect(getSessionPanelMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(SESSION_PANEL_CACHE_STORAGE_KEY)).toBeNull();
  });

  it("opens the summary from the persisted snapshot and refreshes only after a state event", async () => {
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
    getSessionPanelMock.mockResolvedValue(snapshot);

    renderWithProviders(<ChatWorkspace />);
    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));

    expect(await screen.findByText("Cached Debug Session")).toBeInTheDocument();
    expect(screen.getByText("99")).toBeInTheDocument();
    expect(getSessionPanelMock).not.toHaveBeenCalled();

    fireEvent(window, new CustomEvent("personagent:session-panel-changed"));
    await waitFor(() =>
      expect(getSessionPanelMock).toHaveBeenCalledWith("http://localhost:8000", "conversation-1", "/tmp/personagent"),
    );
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

    await openBrowserPanelTab();

    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Forward" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveAttribute("placeholder", "Enter URL");

    fireEvent.change(screen.getByRole("textbox", { name: "Enter URL" }), {
      target: { value: "example.com" },
    });
    fireEvent.submit(screen.getByRole("textbox", { name: "Enter URL" }).closest("form")!);

    await waitFor(() => expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://example.com"));
    expect(screen.getByTitle("Browser https://example.com")).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Close tab Browser" }));
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows browser tracing data and changes cooperation mode from the toolbar", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://example.com", "conversation-1", "Example", {
        element_map: [
          {
            node_id: "node-apply",
            text: "Apply",
            role: "button",
            tag: "button",
            selector: "#apply",
            bounds: { x: 20, y: 30, width: 80, height: 24 },
          },
        ],
        cooperation: {
          enabled: true,
          mode: "observe_only",
          agent_control: "observe_only",
          browser_id: "conversation-1",
          page_state: {
            modal_open: false,
            focused_field: null,
            visible_primary_buttons: ["Apply"],
          },
          useful_timeline: [{ event_id: "evt-1", role: "user", kind: "click", label: "clicked Apply" }],
          raw_events: [
            {
              event_id: "evt-1",
              sequence: 1,
              trace_role: "user",
              kind: "click",
              semantic_label: "clicked Apply",
            },
          ],
          recent_agent_events: [{ event_id: "agent-1", kind: "click", label: "agent highlighted Apply", target: { node_id: "node-apply" } }],
          pending_action_proposals: [
            {
              proposal_id: "proposal-1",
              approval_id: "approval-1",
              tool_name: "BrowserClick",
              target: { node_id: "node-apply" },
              status: "awaiting_approval",
            },
          ],
        },
      }),
    );
    setSessionBrowserCooperationMock.mockResolvedValue({
      cooperation: { enabled: true, mode: "agent_control", agent_control: "agent_control", browser_id: "conversation-1" },
      state_patch: {
        cooperation: { enabled: true, mode: "agent_control", agent_control: "agent_control", browser_id: "conversation-1" },
      },
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    expect(await screen.findByRole("button", { name: "Tracing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browser cooperation mode" })).toHaveTextContent("Observe");

    fireEvent.click(screen.getByRole("button", { name: "Tracing" }));
    expect(await screen.findByText("Useful Timeline")).toBeInTheDocument();
    expect(screen.getAllByText("clicked Apply").length).toBeGreaterThan(0);
    expect(screen.getByText("Proposals")).toBeInTheDocument();

    const modeButton = screen.getByRole("button", { name: "Browser cooperation mode" });
    fireEvent.pointerDown(modeButton, { button: 0, ctrlKey: false });
    fireEvent.click(modeButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Control" }));
    await waitFor(() =>
      expect(setSessionBrowserCooperationMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "conversation-1",
        "conversation-1",
        { enabled: true, mode: "agent_control" },
      ),
    );
  });

  it("renders browser tool highlights and ghost cursor from chat tool blocks", async () => {
    const signInElement = {
      node_id: "pa_signin",
      text: "Sign in",
      role: "link",
      tag: "a",
      selector: "a[href='/login']",
      href: "https://github.com/login",
      bounds: { x: 930, y: 24, width: 76, height: 34 },
      visible: true,
      interactable: true,
    };
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/", "conversation-1", "GitHub", {
        element_map: [signInElement],
        active_tab_id: "conversation-1",
        render_cache_status: "hit",
      }),
    );
    useChatStore.setState({
      messages: [
        {
          id: "agent-browser-tools",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_map",
              name: "BrowserGetElementMap",
              status: "completed",
              title: "Mapped browser elements",
              message: "Mapped browser elements",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_element_map",
                browser_id: "conversation-1",
                page_id: "conversation-1",
                active_tab_id: "conversation-1",
                url: "https://github.com/",
                title: "GitHub",
                element_count: 1,
                elements: [signInElement],
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: false,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    expect(await screen.findByTitle("Browser https://github.com/")).toHaveAttribute(
      "src",
      "data:image/png;base64,iVBORw0KGgo=",
    );
    expect(screen.queryByTestId("browser-tool-highlight-pa_signin")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
    expect(screen.queryByText("Mapped 1 elements")).not.toBeInTheDocument();
  });

  it("keeps running browser click effects hidden while resolving node_id against the current element map", async () => {
    const signInElement = {
      node_id: "pa_signin",
      text: "Sign in",
      role: "link",
      tag: "a",
      selector: "a[href='/login']",
      bounds: { x: 930, y: 24, width: 76, height: 34 },
      visible: true,
    };
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/", "conversation-1", "GitHub", {
        element_map: [signInElement],
        active_tab_id: "conversation-1",
      }),
    );
    useChatStore.setState({
      messages: [
        {
          id: "agent-browser-running-click",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_click_running",
              name: "BrowserClick",
              status: "running",
              title: "Clicking Sign in",
              message: "Clicking Sign in",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_click",
                browser_id: "conversation-1",
                page_id: "conversation-1",
                node_id: "pa_signin",
                url: "https://github.com/",
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: true,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    expect(await screen.findByTitle("Browser https://github.com/")).toBeInTheDocument();
    expect(screen.queryByTestId("browser-tool-highlight-pa_signin")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
  });

  it("automatically opens the browser panel surface for active Browser tool usage", async () => {
    const signInElement = {
      node_id: "pa_signin",
      text: "Sign in",
      role: "link",
      tag: "a",
      selector: "a[href='/login']",
      bounds: { x: 930, y: 24, width: 76, height: 34 },
      visible: true,
    };
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/", "conversation-1", "GitHub", {
        element_map: [signInElement],
        active_tab_id: "conversation-1",
      }),
    );
    useChatStore.setState({
      isStreaming: true,
      messages: [
        {
          id: "agent-browser-auto-open",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_click_running",
              name: "BrowserClick",
              status: "running",
              title: "Clicking Sign in",
              message: "Clicking Sign in",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_click",
                browser_id: "conversation-1",
                page_id: "conversation-1",
                node_id: "pa_signin",
                url: "https://github.com/",
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: true,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    expect(await screen.findByRole("tab", { name: "Browser" })).toBeInTheDocument();
    expect(await screen.findByTitle("Browser https://github.com/")).toBeInTheDocument();
    expect(screen.queryByTestId("browser-tool-highlight-pa_signin")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
    expect(screen.getByTestId("session-panel-shell")).not.toHaveClass("w-0");
  });

  it("hydrates the visible browser tab from a completed BrowserOpen tool result", async () => {
    getSessionBrowserViewMock
      .mockResolvedValueOnce(
        browserView("about:blank", "conversation-1", "", {
          active_tab_id: "",
          image_data: "",
          image_mime_type: "",
          can_capture: false,
        }),
      )
      .mockResolvedValue(
        browserView("https://github.com/login", "conversation-1", "Sign in to GitHub", {
          active_tab_id: "page_login",
          render_cache_status: "hit",
        }),
      );
    useChatStore.setState({
      messages: [
        {
          id: "agent-browser-open",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_open",
              name: "BrowserOpen",
              status: "completed",
              title: "Opened GitHub",
              message: "Opened GitHub",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_open",
                browser_id: "conversation-1",
                page_id: "page_login",
                window_id: "page_login",
                url: "https://github.com",
                final_url: "https://github.com/login",
                title: "Sign in to GitHub",
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: false,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await waitFor(
      () => expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com/login"),
      { timeout: 2000 },
    );
    await waitFor(
      () =>
        expect(getSessionBrowserViewMock).toHaveBeenCalledWith(
          "http://localhost:8000",
          "conversation-1",
          expect.objectContaining({ height: expect.any(Number), width: expect.any(Number) }),
          "conversation-1",
        ),
      { timeout: 2500 },
    );
  });

  it("does not replace the current browser page with about:blank for passive element mapping", async () => {
    const repoElement = {
      node_id: "pa_repo",
      text: "PersonAgent",
      role: "link",
      tag: "a",
      selector: "a[href='/levy/PersonAgent']",
      href: "https://github.com/levy/PersonAgent",
      bounds: { x: 120, y: 80, width: 180, height: 32 },
      visible: true,
      interactable: true,
    };
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/levy/PersonAgent", "conversation-1", "PersonAgent", {
        active_tab_id: "page_github",
        element_map: [repoElement],
        render_cache_status: "hit",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();
    expect(await screen.findByTitle("Browser https://github.com/levy/PersonAgent")).toBeInTheDocument();
    getSessionBrowserViewMock.mockClear();

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-map-blank",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_map_blank",
                name: "BrowserGetElementMap",
                status: "completed",
                title: "Mapped browser elements",
                message: "Mapped browser elements",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_element_map",
                  browser_id: "conversation-1",
                  page_id: "page_github",
                  active_tab_id: "page_github",
                  url: "about:blank",
                  title: "",
                  element_count: 1,
                  elements: [repoElement],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
          },
        ],
      });
    });

    expect(screen.queryByTestId("browser-tool-highlight-pa_repo")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com/levy/PersonAgent");
    expect(screen.getByTitle("Browser https://github.com/levy/PersonAgent")).toBeInTheDocument();
    expect(screen.queryByText("Preparando o ambiente...")).not.toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 800));
    expect(getSessionBrowserViewMock).not.toHaveBeenCalled();
  });

  it("keeps BrowserListTabs from reloading the visible browser page", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/levy/PersonAgent", "conversation-1", "PersonAgent", {
        active_tab_id: "page_github",
        render_cache_status: "hit",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();
    expect(await screen.findByTitle("Browser https://github.com/levy/PersonAgent")).toBeInTheDocument();
    getSessionBrowserViewMock.mockClear();

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-list-tabs",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_list_tabs",
                name: "BrowserListTabs",
                status: "completed",
                title: "Listed browser tabs",
                message: "Listed browser tabs",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_tabs",
                  browser_id: "conversation-1",
                  active_tab_id: "page_github",
                  tabs: [{ page_id: "page_github", url: "https://github.com/levy/PersonAgent", title: "PersonAgent" }],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
          },
        ],
      });
    });

    await new Promise((resolve) => window.setTimeout(resolve, 500));

    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com/levy/PersonAgent");
    expect(screen.getByTitle("Browser https://github.com/levy/PersonAgent")).toBeInTheDocument();
    expect(screen.queryByText("Preparando o ambiente...")).not.toBeInTheDocument();
    expect(getSessionBrowserViewMock).not.toHaveBeenCalled();
  });

  it("deduplicates BrowserListTabs against an already rendered browser URL", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/", "conversation-1", "GitHub", {
        active_tab_id: "conversation-1",
        render_cache_status: "hit",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();
    expect(await screen.findByTitle("Browser https://github.com/")).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
    getSessionBrowserViewMock.mockClear();

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-list-tabs-duplicate-url",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_list_tabs_duplicate_url",
                name: "BrowserListTabs",
                status: "completed",
                title: "Listed browser tabs",
                message: "Listed browser tabs",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_tabs",
                  browser_id: "conversation-1",
                  active_tab_id: "page_github_from_list",
                  tabs: [
                    {
                      page_id: "page_github_from_list",
                      tab_id: "page_github_from_list",
                      url: "https://github.com",
                      final_url: "https://github.com",
                      title: "GitHub",
                      active: true,
                    },
                  ],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
          },
        ],
      });
    });

    await new Promise((resolve) => window.setTimeout(resolve, 500));

    expect(screen.getAllByRole("tab", { name: "GitHub" })).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com");
    expect(screen.getByTitle("Browser https://github.com")).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
    expect(getSessionBrowserViewMock).not.toHaveBeenCalled();
  });

  it("syncs BrowserListTabs results into visible browser panel tabs", async () => {
    renderWithProviders(<ChatWorkspace />);

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-tabs-sync",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_list_tabs_sync",
                name: "BrowserListTabs",
                status: "running",
                title: "Listed browser tabs",
                message: "Listed browser tabs",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_tabs",
                  browser_id: "conversation-1",
                  active_tab_id: "page_docs",
                  tabs: [
                    {
                      page_id: "page_docs",
                      tab_id: "page_docs",
                      url: "https://docs.example.com/guide",
                      title: "Docs Guide",
                      active: true,
                    },
                    {
                      page_id: "page_api",
                      tab_id: "page_api",
                      url: "https://api.example.com/reference",
                      title: "API Reference",
                      active: false,
                    },
                  ],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: true,
            isReasoningStreaming: false,
          },
        ],
        isStreaming: true,
      });
    });

    const shell = await screen.findByTestId("session-panel-shell");
    await waitFor(() => expect(shell).not.toHaveClass("w-0"));
    expect(await screen.findByRole("tab", { name: "Docs Guide" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "API Reference" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://docs.example.com/guide");
  });

  it("does not create a blank browser tab for passive element mapping without a page URL", async () => {
    getSessionBrowserViewMock.mockClear();

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-map-without-page",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_map_without_page",
                name: "BrowserGetElementMap",
                status: "completed",
                title: "Mapped browser elements",
                message: "Mapped browser elements",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_element_map",
                  browser_id: "page_github",
                  page_id: "page_github",
                  active_tab_id: "page_github",
                  url: "about:blank",
                  title: "",
                  element_count: 1,
                  elements: [
                    {
                      node_id: "pa_repo",
                      text: "PersonAgent",
                      role: "link",
                      tag: "a",
                      bounds: { x: 120, y: 80, width: 180, height: 32 },
                      visible: true,
                    },
                  ],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
          },
        ],
      });
    });

    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByRole("tab", { name: "Summary" });
    await new Promise((resolve) => window.setTimeout(resolve, 300));

    expect(screen.queryByRole("tab", { name: "Browser" })).not.toBeInTheDocument();
    expect(getSessionBrowserViewMock).not.toHaveBeenCalled();
  });

  it("keeps browser read-content chunk effects hidden on the current page", async () => {
    const contentBlock = {
      node_id: "pa_article",
      text: "Repository content",
      role: "article",
      tag: "main",
      selector: "main",
      bounds: { x: 120, y: 96, width: 720, height: 420 },
      visible: true,
    };
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/levy/PersonAgent", "conversation-1", "PersonAgent", {
        active_tab_id: "page_repo",
        element_map: [contentBlock],
        render_cache_status: "hit",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();
    expect(await screen.findByTitle("Browser https://github.com/levy/PersonAgent")).toBeInTheDocument();
    getSessionBrowserViewMock.mockClear();

    act(() => {
      useChatStore.setState({
        messages: [
          {
            id: "agent-browser-read-chunk",
            role: "agent",
            label: "PersonAgent",
            content: "",
            reasoning: "",
            reasoningBlocks: [],
            toolBlocks: [
              {
                id: "call_chunk",
                name: "BrowserReadContentChunk",
                status: "completed",
                title: "Read content chunk",
                message: "Read content chunk",
                content: "",
                isCollapsed: false,
                data: {
                  type: "browser_content_chunks",
                  browser_id: "conversation-1",
                  page_id: "page_repo",
                  window_id: "page_repo",
                  url: "https://github.com/levy/PersonAgent",
                  title: "PersonAgent",
                  chunks: [{ index: 1, content: "Repository content", char_start: 0, char_end: 18 }],
                },
              },
            ],
            teamEvents: [],
            parts: [],
            isStreaming: false,
            isReasoningStreaming: false,
          },
        ],
      });
    });

    expect(screen.queryByTestId("browser-tool-highlight-pa_article")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    expect(getSessionBrowserViewMock).not.toHaveBeenCalled();
  });

  it("updates the visible browser tab from a completed click snapshot after navigation", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com/", "conversation-1", "GitHub", {
        active_tab_id: "browser:panel-tab",
      }),
    );
    useChatStore.setState({
      messages: [
        {
          id: "agent-browser-click",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_click",
              name: "BrowserClick",
              status: "completed",
              title: "Clicked Sign in",
              message: "Clicked Sign in",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_click",
                browser_id: "browser:panel-tab",
                page_id: "browser:panel-tab",
                window_id: "browser:panel-tab",
                active_tab_id: "browser:panel-tab",
                url: "https://github.com/login",
                title: "Sign in to GitHub",
                html: "<html><body><main>Login form</main></body></html>",
                document_html: "<html><body><main>Login form</main></body></html>",
                render_mode: "html_mirror",
                css_fidelity: "embedded",
                image_data: "",
                image_mime_type: "",
                viewport_width: 1024,
                viewport_height: 720,
                can_capture: false,
                last_action: {
                  action: "click",
                  node_id: "pa_signin",
                  target: {
                    node_id: "pa_signin",
                    text: "Sign in",
                    role: "link",
                    tag: "a",
                    selector: "a[href='/login']",
                    bounds: { x: 930, y: 24, width: 76, height: 34 },
                  },
                  result: {
                    ok: true,
                    bounds: { x: 930, y: 24, width: 76, height: 34 },
                  },
                },
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: false,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com/login"),
    );
    expect(screen.queryByText("Enter a URL to open a page in this tab.")).not.toBeInTheDocument();
  });

  it("syncs a lightweight completed browser click result and hydrates the cached live view", async () => {
    const signInElement = {
      node_id: "pa_signin",
      text: "Sign in",
      role: "link",
      tag: "a",
      selector: "a[href='/login']",
      href: "https://github.com/login",
      bounds: { x: 930, y: 24, width: 76, height: 34 },
      visible: true,
      interactable: true,
    };
    getSessionBrowserViewMock
      .mockResolvedValueOnce(
        browserView("https://github.com/", "conversation-1", "GitHub", {
          active_tab_id: "browser:panel-tab",
          element_map: [signInElement],
          render_cache_status: "hit",
        }),
      )
      .mockResolvedValue(
        browserView("https://github.com/login", "browser:panel-tab", "Sign in to GitHub", {
          active_tab_id: "browser:panel-tab",
          render_cache_status: "hit",
        }),
      );
    useChatStore.setState({
      messages: [
        {
          id: "agent-browser-lightweight-click",
          role: "agent",
          label: "PersonAgent",
          content: "",
          reasoning: "",
          reasoningBlocks: [],
          toolBlocks: [
            {
              id: "call_click_lightweight",
              name: "BrowserClick",
              status: "completed",
              title: "Clicked Sign in",
              message: "Clicked Sign in",
              content: "",
              isCollapsed: false,
              data: {
                type: "browser_click",
                browser_id: "browser:panel-tab",
                page_id: "browser:panel-tab",
                window_id: "browser:panel-tab",
                active_tab_id: "browser:panel-tab",
                url: "https://github.com/login",
                title: "Sign in to GitHub",
                render_cache_key: "browser:panel-tab::cached-login",
                render_cache_status: "stored",
                viewport_width: 1024,
                viewport_height: 720,
                elements: [signInElement],
                last_action: {
                  action: "click",
                  node_id: "pa_signin",
                  target: signInElement,
                  result: { ok: true, bounds: signInElement.bounds },
                },
              },
            },
          ],
          teamEvents: [],
          parts: [],
          isStreaming: false,
          isReasoningStreaming: false,
        },
      ],
    });

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com/login"),
    );
    await waitFor(() =>
      expect(getSessionBrowserViewMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "browser:panel-tab",
        expect.objectContaining({ cache_mode: "prefer_cached", wait_for_styles: false }),
        "conversation-1",
      ),
    );
    expect(await screen.findByTitle("Browser https://github.com/login")).toHaveAttribute(
      "src",
      "data:image/png;base64,iVBORw0KGgo=",
    );
    expect(screen.queryByTestId("browser-ghost-cursor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("browser-tool-highlight-pa_signin")).not.toBeInTheDocument();
  });

  it("hides the empty browser hint while a navigation is rendering and shows the loaded url after", async () => {
    let resolveInitialLoad!: (value: SessionBrowserView) => void;
    getSessionBrowserViewMock.mockImplementation(
      () =>
        new Promise<SessionBrowserView>((resolve) => {
          resolveInitialLoad = resolve;
        }),
    );

    let resolveNavigation!: (value: SessionBrowserView) => void;
    navigateSessionBrowserMock.mockReturnValueOnce(
      new Promise<SessionBrowserView>((resolve) => {
        resolveNavigation = resolve;
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await screen.findByText("Preparando o ambiente...");

    const urlInput = screen.getByRole("textbox", { name: "Enter URL" });
    fireEvent.change(urlInput, { target: { value: "delayed.example" } });
    fireEvent.submit(urlInput.closest("form")!);

    resolveInitialLoad(browserView("about:blank", "conversation-1"));

    await waitFor(() => expect(navigateSessionBrowserMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Preparando o ambiente...")).toBeInTheDocument();

    resolveNavigation(browserView("https://delayed.example", "conversation-1", "Example Domain"));

    await waitFor(() => expect(urlInput).toHaveValue("https://delayed.example"));
    expect(screen.getByTitle("Browser https://delayed.example")).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
  });

  it("uses stored URLs for browser back, forward, and reload controls", async () => {
    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    const urlInput = screen.getByRole("textbox", { name: "Enter URL" });
    fireEvent.change(urlInput, { target: { value: "example.com" } });
    fireEvent.submit(urlInput.closest("form")!);
    await waitFor(() => expect(urlInput).toHaveValue("https://example.com"));

    fireEvent.change(urlInput, { target: { value: "example.org" } });
    fireEvent.submit(urlInput.closest("form")!);
    await waitFor(() => expect(urlInput).toHaveValue("https://example.org"));
    vi.mocked(navigateSessionBrowser).mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(urlInput).toHaveValue("https://example.com"));
    expect(moveSessionBrowserHistory).toHaveBeenLastCalledWith(
      "http://localhost:8000",
      expect.any(String),
      expect.objectContaining({ direction: -1, cache_mode: "prefer_cached", wait_for_styles: false }),
      "conversation-1",
    );

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));
    await waitFor(() => expect(urlInput).toHaveValue("https://example.org"));
    expect(moveSessionBrowserHistory).toHaveBeenLastCalledWith(
      "http://localhost:8000",
      expect.any(String),
      expect.objectContaining({ direction: 1, cache_mode: "prefer_cached", wait_for_styles: false }),
      "conversation-1",
    );

    fireEvent.click(screen.getByRole("button", { name: "Reload page" }));
    await waitFor(() =>
      expect(reloadSessionBrowser).toHaveBeenLastCalledWith(
        "http://localhost:8000",
        expect.any(String),
        expect.objectContaining({
          width: expect.any(Number),
          height: expect.any(Number),
          cache_mode: "prefer_cached",
          wait_for_styles: false,
        }),
        "conversation-1",
      ),
    );
    expect(navigateSessionBrowser).not.toHaveBeenCalled();
  });

  it("opens the browser annotation editor from iframe-selected element metadata", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://example.com", "conversation-1", "Example Domain", {
        document_html: "<html><body><main><div>Unmapped content</div></main></body></html>",
        html: "<html><body><main><div>Unmapped content</div></main></body></html>",
        render_mode: "html_mirror",
        css_fidelity: "embedded",
        image_data: "",
        image_mime_type: "",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await waitFor(() => expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://example.com"));
    fireEvent.click(screen.getByRole("button", { name: "Inspect and annotate" }));

    fireEvent(
      window,
      new MessageEvent("message", {
        data: {
          type: "personagent-session-browser:element",
          browserId: "conversation-1",
          nodeId: "pa_dom_unmapped",
          element: {
            node_id: "pa_dom_unmapped",
            role: "div",
            tag: "div",
            text: "Unmapped content",
            selector: "body > main:nth-of-type(1) > div:nth-of-type(1)",
            bounds: { x: 12, y: 20, width: 240, height: 64 },
            visible: true,
            color: "rgb(229, 238, 251)",
            font: "16px Inter",
          },
        },
      }),
    );

    expect(await screen.findByText("div · Unmapped content")).toBeInTheDocument();
    const annotationInput = screen.getByPlaceholderText("Ask the agent about this element or describe a change");
    fireEvent.keyDown(annotationInput, { key: "A", code: "KeyA" });
    expect(keySessionBrowserMock).not.toHaveBeenCalled();
    fireEvent.change(annotationInput, { target: { value: "Use this block as context" } });
    fireEvent.keyDown(annotationInput, { key: "Enter", code: "Enter" });

    await waitFor(() =>
      expect(createSessionBrowserAnnotationMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "conversation-1",
        "conversation-1",
        expect.objectContaining({
          node_id: "pa_dom_unmapped",
          body: "Use this block as context",
          quote: "Unmapped content",
          url: "https://example.com",
          title: "Example Domain",
        }),
      ),
    );
  });

  it("keeps the HTML mirror hidden until the iframe reports style readiness", async () => {
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:browser-mirror");
    URL.revokeObjectURL = vi.fn();
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://example.com", "conversation-1", "Example Domain", {
        document_html: "<html><head><link rel=\"stylesheet\" href=\"/style.css\"></head><body><main>Example</main></body></html>",
        html: "<html><head><link rel=\"stylesheet\" href=\"/style.css\"></head><body><main>Example</main></body></html>",
        render_mode: "html_mirror",
        css_fidelity: "embedded",
        image_data: "",
        image_mime_type: "",
      }),
    );

    try {
      renderWithProviders(<ChatWorkspace />);

      await openBrowserPanelTab();

      const iframe = (await screen.findByTitle("Browser https://example.com")) as HTMLIFrameElement;
      expect(iframe).toHaveClass("opacity-0");
      expect(screen.getByText("Aguardando CSS da pagina...")).toBeInTheDocument();

      fireEvent(
        window,
        new MessageEvent("message", {
          data: {
            type: "personagent-session-browser:ready",
            browserId: "conversation-1",
            styleReady: true,
          },
        }),
      );

      await waitFor(() => expect(iframe).not.toHaveClass("opacity-0"));
    } finally {
      URL.createObjectURL = originalCreateObjectUrl;
      URL.revokeObjectURL = originalRevokeObjectUrl;
    }
  });

  it("adds selected browser text as a composer reference", async () => {
    getSessionBrowserViewMock.mockResolvedValue(
      browserView("https://github.com", "conversation-1", "GitHub", {
        document_html: "<html><body><main><h1>The future of building happens together</h1></main></body></html>",
        html: "<html><body><main><h1>The future of building happens together</h1></main></body></html>",
        render_mode: "html_mirror",
        css_fidelity: "embedded",
        image_data: "",
        image_mime_type: "",
      }),
    );

    renderWithProviders(<ChatWorkspace />);

    await openBrowserPanelTab();

    await waitFor(() => expect(screen.getByRole("textbox", { name: "Enter URL" })).toHaveValue("https://github.com"));
    fireEvent(
      window,
      new MessageEvent("message", {
        data: {
          type: "personagent-session-browser:text-selection",
          browserId: "conversation-1",
          selection: {
            text: "The future of building",
            node_id: "pa_dom_heading",
            selector: "body > main:nth-of-type(1) > h1:nth-of-type(1)",
            role: "heading",
            tag: "h1",
            start_offset: 0,
            end_offset: 22,
            bounds: { x: 96, y: 250, width: 198, height: 78 },
          },
        },
      }),
    );

    const annotations = useChatStore.getState().composerAnnotations;
    expect(annotations.at(-1)).toEqual(
      expect.objectContaining({
        source: "browser",
        browserUrl: "https://github.com",
        browserTitle: "GitHub",
        browserNodeId: "pa_dom_heading",
        browserSelector: "body > main:nth-of-type(1) > h1:nth-of-type(1)",
        browserQuote: "The future of building",
      }),
    );
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
    expect(screen.queryByRole("button", { name: "Action mode" })).not.toBeInTheDocument();
    expect(screen.queryByText("Start or open a conversation to view session data.")).not.toBeInTheDocument();
  });
});

describe("browser mirror sanitizer", () => {
  it("removes active content while preserving normal links and safe images", () => {
    const html = sanitizeBrowserMirrorHtml(`
      <html>
        <head>
          <base href="https://evil.example/">
          <meta http-equiv="refresh" content="0;url=https://evil.example">
          <link rel="modulepreload" href="/app.js">
          <link rel="preload" as="script" href="/worker.js">
        </head>
        <body onload="steal()">
          <script>alert("x")</script>
          <iframe srcdoc="<script>alert(1)</script>"></iframe>
          <object data="https://evil.example/payload"></object>
          <a href="javascript:alert(1)" onclick="steal()">Bad</a>
          <a href="https://example.com/docs">Docs</a>
          <form action="javascript:alert(1)" formaction="javascript:alert(2)"></form>
          <img src="data:image/png;base64,abc" onerror="steal()">
          <img src="data:text/html;base64,PHNjcmlwdD4=">
        </body>
      </html>
    `);

    expect(html).not.toContain("<script>alert");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("<object");
    expect(html).not.toContain("<base");
    expect(html).not.toContain("http-equiv");
    expect(html).not.toContain("modulepreload");
    expect(html).not.toContain("onload");
    expect(html).not.toContain("onclick");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("data:text/html");
    expect(html).toContain('href="https://example.com/docs"');
    expect(html).toContain('src="data:image/png;base64,abc"');
  });

  it("uses a nonce-only script policy for injected mirror controls", () => {
    const srcDoc = browserMirrorSrcDoc(
      "<html><head></head><body><button onclick=\"steal()\">Open</button></body></html>",
      "https://example.com/page",
      "browser:test",
      [],
    );

    const nonce = srcDoc.match(/<script nonce="([^"]+)">/)?.[1];
    expect(nonce).toBeTruthy();
    expect(srcDoc).toContain(`script-src 'nonce-${nonce}'`);
    expect(srcDoc).not.toContain("script-src 'self' 'unsafe-inline'");
    expect(srcDoc).not.toContain('onclick="steal()"');
    expect(srcDoc).toContain('<base href="https://example.com/page">');
    expect(srcDoc).toContain("waitForStylesReady");
    expect(srcDoc).toContain("stylesheetLoadedCount");
    expect(srcDoc).not.toContain("personagent-session-browser:tool-visual");
    expect(srcDoc).not.toContain("personagent-session-browser:tool-point");
    expect(srcDoc).not.toContain("pa-tool-highlight");
    expect(srcDoc).not.toContain("scrollIntoView");
    expect(srcDoc).not.toContain('data-pa-browser-mode="action"');
    expect(srcDoc).not.toContain('mode === "action"');
  });

  it("injects browser cooperation event batching and safe redaction hooks", () => {
    const srcDoc = browserMirrorSrcDoc(
      "<html><head></head><body><form><input type=\"password\" name=\"password\"><button>Apply</button></form></body></html>",
      "https://example.com/checkout",
      "browser:test",
      [],
      true,
    );

    expect(srcDoc).toContain("let cooperationEnabled = true");
    expect(srcDoc).toContain("personagent-session-browser:event-batch");
    expect(srcDoc).toContain('trace_role: "user"');
    expect(srcDoc).toContain("correlation_id");
    expect(srcDoc).toContain("trace_effect");
    expect(srcDoc).toContain('trackEvent("click"');
    expect(srcDoc).toContain('trackEvent("input"');
    expect(srcDoc).toContain('trackEvent("route_change"');
    expect(srcDoc).toContain("MutationObserver");
    expect(srcDoc).toContain("ResizeObserver");
    expect(srcDoc).toContain("IntersectionObserver");
    expect(srcDoc).toContain('value: "[REDACTED]"');
    expect(srcDoc).toContain("value_char_count");
    expect(srcDoc).toContain("selected_text");
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

async function openBrowserPanelTab() {
  const shell = screen.getByTestId("session-panel-shell");
  if (shell.classList.contains("w-0")) {
    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
  }
  await waitFor(() => expect(shell).not.toHaveClass("w-0"));

  const browserTab = screen.queryAllByRole("tab", { name: "Browser" })[0];
  if (browserTab) {
    if (browserTab.getAttribute("aria-selected") !== "true") {
      fireEvent.click(browserTab);
    }
    return;
  }
  const existingBrowserTab = screen
    .queryAllByRole("tab")
    .find((tab) => tab.getAttribute("aria-label") && tab.getAttribute("aria-label") !== "Summary");
  if (existingBrowserTab) {
    if (existingBrowserTab.getAttribute("aria-selected") !== "true") {
      fireEvent.click(existingBrowserTab);
    }
    return;
  }

  const addTabButton = await screen.findByRole("button", { name: "New panel tab" });
  fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
  fireEvent.click(addTabButton);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
  await screen.findByRole("tab", { name: "Browser" });
}

function sessionPanelCacheKey(baseUrl: string, conversationId: string, workspaceRoot?: string | null) {
  return JSON.stringify([baseUrl.trim(), conversationId, workspaceRoot?.trim() || ""]);
}
