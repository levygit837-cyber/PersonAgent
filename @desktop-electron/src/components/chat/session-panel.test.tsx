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
  listModels: vi.fn().mockResolvedValue([]),
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

    fireEvent.click(screen.getByRole("button", { name: "Painel da Sessão" }));

    expect(screen.getByRole("tab", { name: "Resumo" })).toBeInTheDocument();
    expect(await screen.findByText("Agent Usage")).toBeInTheDocument();
    expect(screen.getByText("Arquivos Alterados")).toBeInTheDocument();
    expect(screen.getByText("Project Details")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fechar painel da sessão" }));

    await waitFor(() => expect(screen.queryByRole("tab", { name: "Resumo" })).not.toBeInTheDocument());
    expect(screen.getByTestId("session-panel-shell")).toHaveClass("w-0");
  });

  it("opens project item details as a closeable browser tab inside the panel", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Painel da Sessão" }));
    await screen.findByText("Project Details");
    fireEvent.click(await screen.findByText("feat: session panel"));

    expect(await screen.findByRole("tab", { name: "feat: session panel" })).toBeInTheDocument();
    expect(screen.getByText(/Adds the session panel shell/)).toBeInTheDocument();
    expect(getSessionProjectDetailMock).toHaveBeenCalledWith("http://localhost:8000", "conversation-1", {
      type: "commit",
      id: "abc123",
      workspaceRoot: "/tmp/personagent",
    });

    fireEvent.click(screen.getByRole("button", { name: "Fechar aba feat: session panel" }));
    await waitFor(() => expect(screen.queryByText(/Adds the session panel shell/)).not.toBeInTheDocument());
    expect(screen.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens and closes an empty browser-style tab from the plus button", async () => {
    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Painel da Sessão" }));
    await screen.findByText("Agent Usage");
    const addTabButton = screen.getByRole("button", { name: "Nova aba do painel" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Voltar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Avançar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Recarregar página" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Digite sua url" })).toHaveAttribute("placeholder", "digite sua url");
    expect(screen.getByText("Digite uma URL para abrir uma página nesta aba.")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Digite sua url" }), {
      target: { value: "example.com" },
    });
    fireEvent.submit(screen.getByRole("textbox", { name: "Digite sua url" }).closest("form")!);

    expect(screen.getByRole("textbox", { name: "Digite sua url" })).toHaveValue("https://example.com");
    expect(screen.getByTitle("Browser https://example.com")).toHaveAttribute("src", "https://example.com");
    expect(screen.getByRole("button", { name: "Recarregar página" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Fechar aba Browser" }));
    expect(screen.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps browser controls visible even when there is no active conversation", async () => {
    useChatStore.setState({
      conversationId: undefined,
      conversationTitle: undefined,
      messages: [],
    });

    renderWithProviders(<ChatWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Painel da Sessão" }));
    expect(screen.getByText("Inicie ou abra uma conversa para ver dados da sessão.")).toBeInTheDocument();

    const addTabButton = screen.getByRole("button", { name: "Nova aba do painel" });
    fireEvent.pointerDown(addTabButton, { button: 0, ctrlKey: false });
    fireEvent.click(addTabButton);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));

    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Voltar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Avançar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Recarregar página" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Digite sua url" })).toBeInTheDocument();
    expect(screen.queryByText("Inicie ou abra uma conversa para ver dados da sessão.")).not.toBeInTheDocument();
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
