import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listChatCommands, listModels } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { InputDock } from "./input-dock";

vi.mock("../../api/client", () => ({
  getConversation: vi.fn(),
  listModels: vi.fn().mockResolvedValue([]),
  listChatCommands: vi.fn().mockResolvedValue([]),
  resolveBackendUrl: vi.fn().mockResolvedValue("http://localhost:8000"),
  streamChatCompletion: vi.fn(),
  streamTeamChat: vi.fn(),
}));

describe("InputDock", () => {
  const listModelsMock = vi.mocked(listModels);
  const listChatCommandsMock = vi.mocked(listChatCommands);

  beforeEach(() => {
    listModelsMock.mockReset();
    listModelsMock.mockResolvedValue([]);
    listChatCommandsMock.mockReset();
    listChatCommandsMock.mockResolvedValue([]);
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
      messages: [],
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
});
