import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCodexAuthStatus, getGitStatus, gitCheckoutBranch, gitCreateBranch, listBrowserTabMentions, listChatCommands, listGitBranches, listModels, listSkills, listWorkspaceMentions, logoutCodex } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import type { ChatMessageUi, ToolBlockUi } from "../../types/chat";
import { InputDock } from "./input-dock";

vi.mock("../../api/client", () => ({
  getConversation: vi.fn(),
  getCodexAuthStatus: vi.fn().mockResolvedValue({
    authenticated: false,
    error: "Run codex login",
  }),
  getGitStatus: vi.fn().mockResolvedValue({
    branch: "",
    ahead: 0,
    behind: 0,
    modified_count: 0,
    untracked_count: 0,
    is_dirty: false,
    remote_url: null,
  }),
  getGitRecentActions: vi.fn().mockResolvedValue({ is_repo: false, actions: [], errors: [] }),
  forkConversation: vi.fn(),
  generateGitCommitMessage: vi.fn().mockResolvedValue({ message: "Update workspace" }),
  listGitBranches: vi.fn().mockResolvedValue({
    is_repo: false,
    current: "",
    branches: [],
  }),
  gitCreateBranch: vi.fn().mockResolvedValue({ success: true, branch: "feature/new" }),
  gitCreateWorktree: vi.fn(),
  gitCheckoutBranch: vi.fn().mockResolvedValue({ success: true, branch: "feature/api" }),
  gitCommit: vi.fn(),
  gitPush: vi.fn(),
  gitOpenPr: vi.fn(),
  listModels: vi.fn().mockResolvedValue([]),
  listBrowserTabMentions: vi.fn().mockResolvedValue([]),
  listChatCommands: vi.fn().mockResolvedValue([]),
  listSkills: vi.fn().mockResolvedValue([]),
  listWorkspaceMentions: vi.fn().mockResolvedValue([]),
  logoutCodex: vi.fn().mockResolvedValue({ authenticated: false, logout_started: true }),
  resolveBackendUrl: vi.fn().mockResolvedValue("http://localhost:8000"),
  streamChatCompletion: vi.fn(),
  streamTeamChat: vi.fn(),
}));

const originalSendMessage = useChatStore.getState().sendMessage;

describe("InputDock", () => {
  const listModelsMock = vi.mocked(listModels);
  const listBrowserTabMentionsMock = vi.mocked(listBrowserTabMentions);
  const listChatCommandsMock = vi.mocked(listChatCommands);
  const listSkillsMock = vi.mocked(listSkills);
  const listWorkspaceMentionsMock = vi.mocked(listWorkspaceMentions);
  const getCodexAuthStatusMock = vi.mocked(getCodexAuthStatus);
  const logoutCodexMock = vi.mocked(logoutCodex);
  const getGitStatusMock = vi.mocked(getGitStatus);
  const listGitBranchesMock = vi.mocked(listGitBranches);
  const gitCreateBranchMock = vi.mocked(gitCreateBranch);
  const gitCheckoutBranchMock = vi.mocked(gitCheckoutBranch);

  beforeEach(() => {
    listModelsMock.mockReset();
    listModelsMock.mockResolvedValue([]);
    listBrowserTabMentionsMock.mockReset();
    listBrowserTabMentionsMock.mockResolvedValue([]);
    listChatCommandsMock.mockReset();
    listChatCommandsMock.mockResolvedValue([]);
    listSkillsMock.mockReset();
    listSkillsMock.mockResolvedValue([]);
    listWorkspaceMentionsMock.mockReset();
    listWorkspaceMentionsMock.mockResolvedValue([]);
    getCodexAuthStatusMock.mockReset();
    getCodexAuthStatusMock.mockResolvedValue({
      authenticated: false,
      error: "Run codex login",
    });
    logoutCodexMock.mockReset();
    logoutCodexMock.mockResolvedValue({ authenticated: false, logout_started: true });
    getGitStatusMock.mockReset();
    getGitStatusMock.mockResolvedValue({
      branch: "",
      ahead: 0,
      behind: 0,
      modified_count: 0,
      untracked_count: 0,
      is_dirty: false,
      remote_url: null,
    });
    listGitBranchesMock.mockReset();
    listGitBranchesMock.mockResolvedValue({
      is_repo: false,
      current: "",
      branches: [],
    });
    gitCreateBranchMock.mockReset();
    gitCreateBranchMock.mockResolvedValue({ success: true, branch: "feature/new" });
    gitCheckoutBranchMock.mockReset();
    gitCheckoutBranchMock.mockResolvedValue({ success: true, branch: "feature/api" });
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      provider: "llama",
      selectedModelId: "local-model",
      reasoningPreset: "low",
      selectedWorkspace: undefined,
      recentWorkspaces: [],
      teamMode: false,
    });
    useChatStore.setState({
      sendMessage: originalSendMessage,
      messages: [],
      composerAnnotations: [],
      isStreaming: false,
      isFinalizing: false,
      conversationId: undefined,
      error: undefined,
      nextStepSuggestion: undefined,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps the old status chips out of the composer", () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.queryByText("http://localhost:8000")).not.toBeInTheDocument();
    expect(screen.queryByText("local-model")).not.toBeInTheDocument();
    expect(screen.queryByText(/Reasoning:/)).not.toBeInTheDocument();
  });

  it("toggles Teams from the agents feature submenu", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /system features/i }));

    const agentsItem = screen.getByRole("menuitem", { name: /agentes/i });
    fireEvent.pointerMove(agentsItem, { pointerType: "mouse" });

    const teamsItem = await screen.findByRole("menuitemcheckbox", { name: /teams/i });
    expect(teamsItem).toHaveAttribute("aria-checked", "false");

    fireEvent.click(teamsItem);

    expect(useAppStore.getState().teamMode).toBe(true);
    expect(teamsItem).toHaveAttribute("aria-checked", "true");
  });

  it("keeps the agents submenu clickable while the pointer crosses the hover gap", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /system features/i }));

    const agentsItem = screen.getByRole("menuitem", { name: /agentes/i });
    const agentsBranch = agentsItem.parentElement;
    expect(agentsBranch).not.toBeNull();
    fireEvent.pointerEnter(agentsBranch!);

    const teamsItem = await screen.findByRole("menuitemcheckbox", { name: /teams/i });
    vi.useFakeTimers();
    fireEvent.pointerLeave(agentsBranch!);
    fireEvent.click(teamsItem);

    expect(useAppStore.getState().teamMode).toBe(true);

    act(() => {
      vi.advanceTimersByTime(180);
    });
  });

  it("shows every hosted model returned by the backend catalog", async () => {
    listModelsMock.mockImplementation(async (_baseUrl, provider) => {
      if (provider === "nvidia") {
        return [
          {
            id: "google/gemma-3-4b-it",
            name: "google/gemma-3-4b-it",
            provider: "nvidia",
            capabilities: ["chat"],
          },
          {
            id: "nvidia/llama-nemotron-embed-1b-v2",
            name: "nvidia/llama-nemotron-embed-1b-v2",
            provider: "nvidia",
            capabilities: ["chat"],
          },
        ];
      }
      if (provider === "vertex") {
        return [
          {
            id: "gemini-3.1-custom-preview",
            name: "gemini-3.1-custom-preview",
            provider: "vertex",
            capabilities: ["chat", "thinking"],
          },
        ];
      }
      if (provider === "kimi") {
        return [
          {
            id: "kimi-for-coding",
            name: "Kimi K2.6",
            provider: "kimi",
            capabilities: ["chat", "reasoning_chat", "tools"],
            context_length: 262144,
          },
        ];
      }
      if (provider === "zenmux") {
        return [
          {
            id: "deepseek/deepseek-v4-flash-free",
            name: "DeepSeek V4 Flash Free",
            provider: "zenmux",
            capabilities: ["chat", "reasoning_chat", "tools", "streaming"],
            context_length: 1000000,
          },
        ];
      }
      if (provider === "codex") {
        return [
          {
            id: "gpt-5.5",
            name: "GPT-5.5",
            provider: "codex",
            capabilities: ["chat", "reasoning_chat", "tools", "streaming"],
            context_length: 272000,
          },
          {
            id: "gpt-5.4-mini",
            name: "GPT-5.4-Mini",
            provider: "codex",
            capabilities: ["chat", "reasoning_chat", "tools", "streaming"],
            context_length: 272000,
          },
        ];
      }
      return [];
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect(await screen.findByText("gemma 3 4B it")).toBeInTheDocument();
    expect(await screen.findByText("Llama Nemotron embed 1B v2")).toBeInTheDocument();
    expect(await screen.findByText(/Gemini 3\.1 custom preview/i)).toBeInTheDocument();
    expect(await screen.findByText("Kimi K2.6")).toBeInTheDocument();
    expect(await screen.findByText("DeepSeek V4 Flash Free")).toBeInTheDocument();
  });

  it("shows the curated Vertex Gemini 3 models in the model selector", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect(await screen.findByText("Google Vertex")).toBeInTheDocument();
    expect(screen.getByText("Gemini 3.1 Flash-Lite")).toBeInTheDocument();
    expect(screen.getByText("Gemini 3 Pro Image")).toBeInTheDocument();
    expect(screen.queryByText("gemini-3-pro-preview")).not.toBeInTheDocument();
  });

  it("separates DeepSeek API models from DeepSeek NVIDIA models", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    const apiLabel = await screen.findByText("DeepSeek API");
    const nvidiaLabel = await screen.findByText("DeepSeek NVIDIA");

    const apiGroup = apiLabel.parentElement;
    const nvidiaGroup = nvidiaLabel.parentElement;
    expect(apiGroup).not.toBeNull();
    expect(nvidiaGroup).not.toBeNull();
    expect(apiGroup).not.toBe(nvidiaGroup);
    expect(within(apiGroup!).getByText("DeepSeek V4 Flash")).toBeInTheDocument();
    expect(within(apiGroup!).getByText("DeepSeek V4 Pro")).toBeInTheDocument();
    expect(within(nvidiaGroup!).getByText("DeepSeek V4 Flash")).toBeInTheDocument();
    expect(within(nvidiaGroup!).getByText("DeepSeek V4 Pro")).toBeInTheDocument();
  });

  it("shows ZenMux DeepSeek free models and selects the zenmux provider", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect(await screen.findByText("ZenMux")).toBeInTheDocument();
    const zenmuxItem = screen.getByText("DeepSeek V4 Pro Free");
    fireEvent.click(zenmuxItem);

    expect(useAppStore.getState().provider).toBe("zenmux");
    expect(useAppStore.getState().selectedModelId).toBe("deepseek/deepseek-v4-pro-free");
  });

  it("shows Kimi K2.6 and selects the kimi provider", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect(await screen.findByText("Kimi Code")).toBeInTheDocument();
    const kimiItem = screen.getByText("Kimi K2.6");
    fireEvent.click(kimiItem);

    expect(useAppStore.getState().provider).toBe("kimi");
    expect(useAppStore.getState().selectedModelId).toBe("kimi-for-coding");
  });

  it("shows ChatGPT Subscription models and selects the codex provider", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect((await screen.findAllByText("ChatGPT Subscription")).length).toBeGreaterThan(0);
    const codexItem = screen.getByText("GPT-5.5");
    fireEvent.click(codexItem);

    expect(useAppStore.getState().provider).toBe("codex");
    expect(useAppStore.getState().selectedModelId).toBe("gpt-5.5");
  });

  it("shows Codex auth status and runs logout", async () => {
    getCodexAuthStatusMock.mockResolvedValue({
      authenticated: true,
      email: "user@example.com",
      account_id: "acct_123",
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: /model and reasoning/i }));

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("user@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /logout/i }));

    await waitFor(() => expect(logoutCodexMock).toHaveBeenCalledWith("http://localhost:8000"));
  });

  it("shows slash command autocomplete from the backend", async () => {
    listChatCommandsMock.mockResolvedValue([
      {
        name: "review",
        slash_name: "/review",
        description: "Review code",
        source: "command",
        path: "/tmp/.personagent/commands/review.md",
        user_invocable: true,
      },
    ]);

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByPlaceholderText(/ask the local agent/i), {
      target: { value: "/r" },
    });

    expect(await screen.findByText("/review")).toBeInTheDocument();
  });

  it("shows the next-step suggestion chip", () => {
    useChatStore.setState({ nextStepSuggestion: "Run focused tests" });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Run focused tests")).toBeInTheDocument();
  });

  it("shows composer annotation chips and sends them with the main chat text", () => {
    const sendMessage = vi.fn();
    useChatStore.setState({
      sendMessage,
      composerAnnotations: [
        {
          id: 1,
          fileName: "AGENTS.md",
          displayPath: "AGENTS.md",
          filePath: "/home/levybonito/Projetos/MindFlow/AGENTS.md",
          startLine: 8,
          endLine: 24,
          text: "Rewrite this guidance",
          selectedLines: "8: old guidance\n9: more guidance",
          language: "markdown",
        },
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("composer-annotations")).toBeInTheDocument();
    expect(screen.getByText("@Annotation#1")).toBeInTheDocument();
    expect(screen.getByText("AGENTS.md")).toBeInTheDocument();
    expect(screen.getByText("L8-24")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/ask the local agent/i), {
      target: { value: "Apply with a concise tone" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(sendMessage).toHaveBeenCalledWith(
      "Apply with a concise tone",
      undefined,
      expect.objectContaining({
        contextAttachments: [
          expect.objectContaining({
            type: "viewer_annotation",
            label: "@Annotation#1",
            file_path: "/home/levybonito/Projetos/MindFlow/AGENTS.md",
            display_path: "AGENTS.md",
            start_line: 8,
            end_line: 24,
            text: "Rewrite this guidance",
          }),
        ],
      }),
    );
    const options = sendMessage.mock.calls[0][2];
    expect(JSON.stringify(options)).not.toContain("Selected lines");
    expect(JSON.stringify(options)).not.toContain("8: old guidance");
    expect(useChatStore.getState().composerAnnotations).toEqual([]);
  });

  it("sends browser annotations as browser context attachments", () => {
    const sendMessage = vi.fn();
    useChatStore.setState({
      sendMessage,
      composerAnnotations: [
        {
          id: 2,
          source: "browser",
          fileName: "Search results",
          displayPath: "Search results · google.com",
          filePath: "https://www.google.com/search?q=personagent",
          startLine: 1,
          endLine: 1,
          text: "Use this result in the response",
          selectedLines: "Visible text: PersonAgent",
          language: "browser",
          browserUrl: "https://www.google.com/search?q=personagent",
          browserTitle: "Search results",
          browserNodeId: "pa_result_1",
          browserSelector: "html > body > a",
          browserRole: "link",
          browserQuote: "PersonAgent",
        },
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.getByText("DOM")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(sendMessage).toHaveBeenCalledWith(
      "Use this result in the response",
      undefined,
      expect.objectContaining({
        contextAttachments: [
          expect.objectContaining({
            type: "browser_annotation",
            url: "https://www.google.com/search?q=personagent",
            node_id: "pa_result_1",
            selector: "html > body > a",
            quote: "PersonAgent",
          }),
        ],
      }),
    );
  });

  it("turns @ file autocomplete selections into context attachments", async () => {
    const sendMessage = vi.fn();
    useAppStore.setState({ selectedWorkspace: "/workspace" });
    useChatStore.setState({ sendMessage });
    listWorkspaceMentionsMock.mockResolvedValue([
      {
        type: "file",
        name: "app.ts",
        path: "/workspace/src/app.ts",
        display_path: "src/app.ts",
        is_directory: false,
        score: 1,
      },
    ]);

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    const input = screen.getByPlaceholderText(/ask the local agent/i);
    fireEvent.change(input, { target: { value: "Review @app" } });

    const suggestion = await screen.findByText("src/app.ts");
    fireEvent.mouseDown(suggestion);

    expect(screen.getByTestId("composer-mentions")).toBeInTheDocument();
    expect(screen.getByText("@File")).toBeInTheDocument();
    expect(input).toHaveValue("Review @src/app.ts ");

    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(sendMessage).toHaveBeenCalledWith(
      "Review @src/app.ts",
      undefined,
      expect.objectContaining({
        contextAttachments: [
          expect.objectContaining({
            type: "file",
            label: "@File",
            file_path: "/workspace/src/app.ts",
            display_path: "src/app.ts",
          }),
        ],
      }),
    );
  });

  it("turns @ skill autocomplete selections into skill context attachments", async () => {
    const sendMessage = vi.fn();
    useAppStore.setState({ selectedWorkspace: "/workspace" });
    useChatStore.setState({ sendMessage });
    listSkillsMock.mockResolvedValue([
      {
        name: "Debug Root Cause",
        invocation_name: "debug-root-cause",
        slash_name: "/debug-root-cause",
        description: "Investigate failures end to end",
        source: "workspace",
        path: "/workspace/.personagent/skills/debug-root-cause/SKILL.md",
        enabled: true,
        user_invocable: true,
        model_invocable: true,
        allowed_tools: [],
        context: "inline",
      },
    ]);

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    const input = screen.getByPlaceholderText(/ask the local agent/i);
    fireEvent.change(input, { target: { value: "Use @skill:debug" } });

    const suggestion = await screen.findByText("@skill:debug-root-cause");
    fireEvent.mouseDown(suggestion);
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(sendMessage).toHaveBeenCalledWith(
      "Use @skill:debug-root-cause",
      undefined,
      expect.objectContaining({
        contextAttachments: [
          expect.objectContaining({
            type: "skill",
            label: "@skill:debug-root-cause",
            invocation_name: "debug-root-cause",
            slash_name: "/debug-root-cause",
          }),
        ],
      }),
    );
  });

  it("turns @Browser autocomplete selections into browser tab context attachments", async () => {
    const sendMessage = vi.fn();
    useChatStore.setState({ sendMessage, conversationId: "conversation-1" });
    listBrowserTabMentionsMock.mockResolvedValue([
      {
        type: "browser_tab",
        id: "browser_tab:conversation-1:page_github",
        label: "@Browser:github.com",
        token: "@Browser:github.com",
        browser_id: "conversation-1",
        tab_id: "page_github",
        page_id: "page_github",
        window_id: "page_github",
        url: "https://github.com/personagent/personagent",
        title: "GitHub - PersonAgent",
        runtime: "lightpanda",
        active: true,
        is_active: true,
        display_path: "GitHub - PersonAgent",
        domain: "github.com",
        state: { scroll: { y: 120 } },
        updated_at: "2026-04-29T10:00:00Z",
        score: 0,
      },
    ]);

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    const input = screen.getByPlaceholderText(/ask the local agent/i);
    fireEvent.change(input, { target: { value: "Use @Browser:github" } });

    const suggestion = await screen.findByText("GitHub - PersonAgent");
    fireEvent.mouseDown(suggestion);
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(listBrowserTabMentionsMock).toHaveBeenCalledWith("http://localhost:8000", "conversation-1", "github");
    expect(sendMessage).toHaveBeenCalledWith(
      "Use @Browser:github.com",
      undefined,
      expect.objectContaining({
        contextAttachments: [
          expect.objectContaining({
            type: "browser_tab",
            label: "@Browser",
            browser_id: "conversation-1",
            page_id: "page_github",
            url: "https://github.com/personagent/personagent",
            active: true,
          }),
        ],
      }),
    );
  });

  it("lets the user remove a composer annotation before sending", () => {
    useChatStore.setState({
      composerAnnotations: [
        {
          id: 2,
          fileName: "README.md",
          displayPath: "README.md",
          filePath: "/workspace/README.md",
          startLine: 3,
          endLine: 5,
          text: "Remove this paragraph",
          selectedLines: "3: old",
          language: "markdown",
        },
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Remove @Annotation#2" }));

    expect(screen.queryByTestId("composer-annotations")).not.toBeInTheDocument();
    expect(useChatStore.getState().composerAnnotations).toEqual([]);
  });

  it("keeps the composer usable while a completed turn is finalizing", () => {
    useChatStore.setState({ isStreaming: false, isFinalizing: true });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("button", { name: /stop/i })).not.toBeInTheDocument();
    const input = screen.getByPlaceholderText(/ask the local agent/i);
    expect(input).not.toBeDisabled();
    fireEvent.change(input, { target: { value: "next message" } });
    expect(screen.getByRole("button", { name: /send/i })).not.toBeDisabled();
  });

  it("opens the branch panel from the composer", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /branches/i }));

    expect(await screen.findByTestId("branch-switcher-panel")).toBeInTheDocument();
    expect(screen.getAllByText("No workspace selected").length).toBeGreaterThan(0);
  });

  it("lists branches and checks out a selected branch", async () => {
    useAppStore.setState({ selectedWorkspace: "/workspace/repo" });
    getGitStatusMock.mockResolvedValue({
      branch: "main",
      ahead: 0,
      behind: 0,
      modified_count: 1,
      untracked_count: 0,
      is_dirty: true,
      remote_url: null,
    });
    listGitBranchesMock.mockResolvedValue({
      is_repo: true,
      current: "main",
      branches: [
        {
          name: "main",
          kind: "local",
          current: true,
          upstream: "origin/main",
          last_commit_iso: "2026-04-28T10:00:00Z",
          last_commit_subject: "main commit",
        },
        {
          name: "feature/api",
          kind: "local",
          current: false,
          upstream: null,
          last_commit_iso: "2026-04-28T10:01:00Z",
          last_commit_subject: "api work",
        },
        {
          name: "cascade/worktree",
          kind: "local",
          current: false,
          upstream: null,
          last_commit_iso: "2026-04-28T10:03:00Z",
          last_commit_subject: "worktree branch",
          worktree_path: "/home/levybonito/.windsurf/worktrees/WebPilot/WebPilot-aa41215c",
          checked_out_elsewhere: true,
        },
        {
          name: "origin/preview",
          kind: "remote",
          current: false,
          upstream: null,
          last_commit_iso: "2026-04-28T10:02:00Z",
          last_commit_subject: "preview work",
        },
        {
          name: "origin/main",
          kind: "remote",
          current: false,
          upstream: null,
          last_commit_iso: "2026-04-28T10:00:00Z",
          last_commit_subject: "main commit",
        },
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /branches/i }));

    expect(await screen.findByText("main commit")).toBeInTheDocument();
    expect(screen.getByText("Working tree has local changes. Checkout may fail if Git cannot preserve them.")).toBeInTheDocument();
    expect(screen.getByText("Remote")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /origin\/main/i })).not.toBeInTheDocument();
    const lockedWorktreeBranch = screen.getByRole("button", { name: /cascade\/worktree/i });
    expect(lockedWorktreeBranch).toBeDisabled();
    expect(screen.getByText("In use: WebPilot/WebPilot-aa41215c")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /feature\/api/i }));

    await waitFor(() => {
      expect(gitCheckoutBranchMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "/workspace/repo",
        "feature/api",
        "local",
      );
    });
  });

  it("creates a branch from the branch panel", async () => {
    useAppStore.setState({ selectedWorkspace: "/workspace/repo" });
    getGitStatusMock.mockResolvedValue({
      branch: "main",
      ahead: 0,
      behind: 0,
      modified_count: 0,
      untracked_count: 0,
      is_dirty: false,
      remote_url: null,
    });
    listGitBranchesMock.mockResolvedValue({
      is_repo: true,
      current: "main",
      branches: [{ name: "main", kind: "local", current: true, upstream: null }],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /branches/i }));
    await screen.findByPlaceholderText("Search branches...");
    fireEvent.click(await screen.findByRole("button", { name: /create branch/i }));
    fireEvent.change(screen.getByPlaceholderText("new-branch-name"), {
      target: { value: "feature/new-panel" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: /create branch/i }).at(-1)!);

    await waitFor(() => {
      expect(gitCreateBranchMock).toHaveBeenCalledWith(
        "http://localhost:8000",
        "/workspace/repo",
        "feature/new-panel",
      );
    });
  });

  it("disables the branch button while streaming", () => {
    useChatStore.setState({ isStreaming: true });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("button", { name: /branches/i })).toBeDisabled();
  });

  it("renders active todos attached above the input dock while the agent is running", () => {
    useChatStore.setState({
      isStreaming: true,
      activeAgentId: "agent",
      messages: [
        agentMessage({
          id: "agent",
          isStreaming: true,
          toolBlocks: [
            todoBlock({
              id: "todo-1",
              data: {
                todos: [
                  { id: "inspect", content: "Inspect current renderer", status: "completed" },
                  { id: "build", content: "Build todo panel", status: "in_progress" },
                ],
              },
            }),
            todoBlock({
              id: "todo-2",
              data: {
                todos: [
                  { id: "inspect", content: "Inspect current renderer", status: "completed" },
                  { id: "build", content: "Build todo panel", status: "in_progress" },
                  { id: "verify", content: "Verify dock behavior", status: "pending" },
                ],
              },
            }),
          ],
        }),
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    const stack = screen.getByTestId("input-dock-stack");
    const tracker = screen.getByTestId("input-todo-tracker");
    const scrollRegion = screen.getByTestId("input-todo-scroll");
    const composer = screen.getByTestId("input-composer");

    expect(stack).toHaveClass("gap-0");
    expect(tracker).toHaveAttribute("data-state", "visible");
    expect(tracker).toHaveClass("rounded-b-none", "border-b-0");
    expect(tracker.nextElementSibling).toBe(composer);
    expect(scrollRegion).toHaveClass("max-h-24", "overflow-y-auto");
    expect(screen.getByText("TodoWrite - 2 updates")).toBeInTheDocument();
    expect(screen.getByText("1/3 done")).toBeInTheDocument();
    expect(screen.getByText("Verify dock behavior")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /minimize todo tracker/i })).toBeInTheDocument();
  });

  it("minimizes and restores the todo tracker from the header", () => {
    useChatStore.setState({
      isStreaming: true,
      activeAgentId: "agent",
      messages: [
        agentMessage({
          id: "agent",
          isStreaming: true,
          toolBlocks: [
            todoBlock({
              data: {
                todos: [
                  { id: "inspect", content: "Inspect current renderer", status: "completed" },
                  { id: "build", content: "Build todo panel", status: "in_progress" },
                  { id: "verify", content: "Verify dock behavior", status: "pending" },
                ],
              },
            }),
          ],
        }),
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    const tracker = screen.getByTestId("input-todo-tracker");
    const scrollRegion = screen.getByTestId("input-todo-scroll");

    fireEvent.click(screen.getByRole("button", { name: /minimize todo tracker/i }));

    expect(tracker).toHaveAttribute("data-state", "minimized");
    expect(screen.getByText("Todos 1/3")).toBeInTheDocument();
    expect(scrollRegion).toHaveClass("max-h-0", "opacity-0");
    expect(screen.getByRole("button", { name: /restore todo tracker/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /restore todo tracker/i }));

    expect(tracker).toHaveAttribute("data-state", "visible");
    expect(screen.getByText("TodoWrite")).toBeInTheDocument();
    expect(scrollRegion).toHaveClass("max-h-24", "opacity-100");
  });

  it("keeps completed todos visible until agent execution ends, then exits into the input dock", () => {
    vi.useFakeTimers();
    useChatStore.setState({
      isStreaming: true,
      activeAgentId: "agent",
      messages: [
        agentMessage({
          id: "agent",
          isStreaming: true,
          toolBlocks: [
            todoBlock({
              id: "todo-1",
              data: {
                todos: [
                  { id: "inspect", content: "Inspect current renderer", status: "completed" },
                  { id: "build", content: "Build todo panel", status: "completed" },
                ],
              },
            }),
          ],
        }),
      ],
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <InputDock />
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("input-todo-tracker")).toHaveAttribute("data-state", "visible");
    expect(screen.getByText("2/2 done")).toBeInTheDocument();

    act(() => {
      useChatStore.setState({ isStreaming: false, isFinalizing: false, activeAgentId: undefined });
    });

    const tracker = screen.getByTestId("input-todo-tracker");
    expect(tracker).toHaveAttribute("data-state", "exiting");

    act(() => {
      vi.advanceTimersByTime(280);
    });

    expect(screen.queryByTestId("input-todo-tracker")).not.toBeInTheDocument();
  });
});

function agentMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
  return {
    id: "agent",
    role: "agent",
    label: "PersonAgent",
    content: "",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
    ...overrides,
  };
}

function todoBlock(overrides: Partial<ToolBlockUi> = {}): ToolBlockUi {
  return {
    id: "todo",
    name: "TodoWrite",
    status: "completed",
    title: "TodoWrite",
    message: "",
    content: "",
    data: { todos: [] },
    isCollapsed: false,
    ...overrides,
  };
}
