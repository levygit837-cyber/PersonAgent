import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  actSessionBrowser,
  clickSessionBrowser,
  createSessionBrowserAnnotation,
  getSessionBrowserView,
  getSessionPanel,
  getSessionProjectDetail,
  keySessionBrowser,
  listChatCommands,
  listModels,
  moveSessionBrowserHistory,
  navigateSessionBrowser,
  reloadSessionBrowser,
  scrollSessionBrowser,
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
  createSessionBrowserAnnotation: vi.fn(),
  getSessionBrowserView: vi.fn(),
  getSessionPanel: vi.fn(),
  getSessionProjectDetail: vi.fn(),
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
  const actSessionBrowserMock = vi.mocked(actSessionBrowser);
  const createSessionBrowserAnnotationMock = vi.mocked(createSessionBrowserAnnotation);
  const keySessionBrowserMock = vi.mocked(keySessionBrowser);
  const scrollSessionBrowserMock = vi.mocked(scrollSessionBrowser);
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
    moveSessionBrowserHistoryMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com", browserId, "Example Domain"),
    );
    reloadSessionBrowserMock.mockReset();
    reloadSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com", browserId, "Example Domain"),
    );
    clickSessionBrowserMock.mockReset();
    clickSessionBrowserMock.mockImplementation(async (_baseUrl, browserId) =>
      browserView("https://example.com/clicked", browserId, "Clicked"),
    );
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

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

    await screen.findByText("Preparando o ambiente...");

    const urlInput = screen.getByRole("textbox", { name: "Enter URL" });
    fireEvent.change(urlInput, { target: { value: "example.com" } });
    fireEvent.submit(urlInput.closest("form")!);

    resolveInitialLoad(browserView("about:blank", "conversation-1"));

    await waitFor(() => expect(navigateSessionBrowserMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Preparando o ambiente...")).toBeInTheDocument();

    resolveNavigation(browserView("https://example.com", "conversation-1", "Example Domain"));

    await waitFor(() => expect(urlInput).toHaveValue("https://example.com"));
    expect(screen.getByTitle("Browser https://example.com")).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
  });

  it("uses stored URLs for browser back, forward, and reload controls", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

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
    expect(navigateSessionBrowser).toHaveBeenLastCalledWith(
      "http://localhost:8000",
      expect.any(String),
      expect.objectContaining({ url: "https://example.com" }),
      "conversation-1",
    );

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));
    await waitFor(() => expect(urlInput).toHaveValue("https://example.org"));
    expect(navigateSessionBrowser).toHaveBeenLastCalledWith(
      "http://localhost:8000",
      expect.any(String),
      expect.objectContaining({ url: "https://example.org" }),
      "conversation-1",
    );

    fireEvent.click(screen.getByRole("button", { name: "Reload page" }));
    await waitFor(() =>
      expect(navigateSessionBrowser).toHaveBeenLastCalledWith(
        "http://localhost:8000",
        expect.any(String),
        expect.objectContaining({ url: "https://example.org" }),
        "conversation-1",
      ),
    );
    expect(moveSessionBrowserHistory).not.toHaveBeenCalled();
    expect(reloadSessionBrowser).not.toHaveBeenCalled();
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

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Session Panel" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "New panel tab" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

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
