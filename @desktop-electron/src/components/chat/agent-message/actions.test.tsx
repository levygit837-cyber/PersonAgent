import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  AgentMessageActions,
  MemoryTraceInspector,
  memoryTraceFromMetadata,
  type MemoryTraceTab,
} from "./actions";
import { useChatStore } from "../../../stores/chat-store";
import type { ChatMessageUi, MemoryTrace } from "../../../types/chat";

describe("AgentMessageActions", () => {
  beforeEach(() => {
    useChatStore.setState({
      isStreaming: false,
      setAgentFeedback: vi.fn(),
      regenerateAgentMessage: vi.fn(),
      branchAgentMessage: vi.fn(),
    });
  });

  it("renders feedback buttons", () => {
    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByRole("button", { name: /Positive feedback/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Negative feedback/i })).toBeInTheDocument();
  });

  it("calls setAgentFeedback with positive when thumbs up clicked", () => {
    const setAgentFeedback = vi.fn();
    useChatStore.setState({ setAgentFeedback });

    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /Positive feedback/i }));
    expect(setAgentFeedback).toHaveBeenCalledWith("msg-1", "positive");
  });

  it("calls setAgentFeedback with negative when thumbs down clicked", () => {
    const setAgentFeedback = vi.fn();
    useChatStore.setState({ setAgentFeedback });

    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /Negative feedback/i }));
    expect(setAgentFeedback).toHaveBeenCalledWith("msg-1", "negative");
  });

  it("disables feedback buttons while streaming", () => {
    useChatStore.setState({ isStreaming: true });

    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByRole("button", { name: /Positive feedback/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Negative feedback/i })).toBeDisabled();
  });

  it("calls regenerateAgentMessage when regenerate clicked", () => {
    const regenerateAgentMessage = vi.fn();
    useChatStore.setState({ regenerateAgentMessage });

    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(regenerateAgentMessage).toHaveBeenCalledWith("msg-1");
  });

  it("calls branchAgentMessage when branch clicked", () => {
    const branchAgentMessage = vi.fn();
    useChatStore.setState({ branchAgentMessage });

    render(<AgentMessageActions message={baseMessage()} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /Branch to worktree/i }));
    expect(branchAgentMessage).toHaveBeenCalledWith("msg-1");
  });

  it("shows feedback saved indicator when feedback is set", () => {
    const message = baseMessage();
    message.metadata = { feedback: "positive" };

    render(<AgentMessageActions message={message} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByText("Feedback saved")).toBeInTheDocument();
  });

  it("shows worktree ready badge when worktree_status is ready", () => {
    const message = baseMessage();
    message.metadata = { worktree_status: "ready", worktree_path: "/tmp/worktrees/feature", worktree_branch: "feature" };

    render(<AgentMessageActions message={message} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByText(/Worktree: feature/)).toBeInTheDocument();
  });

  it("shows worktree error badge when worktree_status is error", () => {
    const message = baseMessage();
    message.metadata = { worktree_status: "error", worktree_error: "Workspace not found" };

    render(<AgentMessageActions message={message} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByText("Workspace not found")).toBeInTheDocument();
  });

  it("disables branch button while worktree is running", () => {
    const message = baseMessage();
    message.metadata = { worktree_status: "running" };

    render(<AgentMessageActions message={message} memoryInspectorOpen={false} onToggleMemoryInspector={() => {}} />);

    expect(screen.getByRole("button", { name: /Creating worktree/i })).toBeDisabled();
  });

  it("shows memory trace badge when memoryTrace is provided", () => {
    render(
      <AgentMessageActions
        message={baseMessage()}
        memoryTrace={sampleMemoryTrace()}
        memoryInspectorOpen={false}
        onToggleMemoryInspector={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /Memory trace: 2 memories used/i })).toBeInTheDocument();
  });

  it("calls onToggleMemoryInspector when memory badge clicked", () => {
    const onToggle = vi.fn();
    render(
      <AgentMessageActions
        message={baseMessage()}
        memoryTrace={sampleMemoryTrace()}
        memoryInspectorOpen={false}
        onToggleMemoryInspector={onToggle}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Memory trace: 2 memories used/i }));
    expect(onToggle).toHaveBeenCalled();
  });
});

describe("MemoryTraceInspector", () => {
  it("renders used tab by default", () => {
    render(<MemoryTraceInspector trace={sampleMemoryTrace()} activeTab="used" onTabChange={() => {}} />);

    expect(screen.getByText("Memory trace")).toBeInTheDocument();
    expect(screen.getByText("Keep Python preferences visible")).toBeInTheDocument();
  });

  it("switches to filters tab", () => {
    render(<MemoryTraceInspector trace={sampleMemoryTrace()} activeTab="filters" onTabChange={() => {}} />);

    expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
    expect(screen.getByText("Latency")).toBeInTheDocument();
    expect(screen.getByText("62ms")).toBeInTheDocument();
  });

  it("switches to prompt tab", () => {
    render(
      <MemoryTraceInspector
        trace={sampleMemoryTrace()}
        activeTab="prompt"
        onTabChange={() => {}}
      />,
    );

    expect(screen.getByText(/Injected memory block/)).toBeInTheDocument();
  });

  it("calls onTabChange when tab button clicked", () => {
    const onTabChange = vi.fn();
    render(<MemoryTraceInspector trace={sampleMemoryTrace()} activeTab="used" onTabChange={onTabChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(onTabChange).toHaveBeenCalledWith("filters");
  });

  it("shows empty state when no memory items in used tab", () => {
    const trace: MemoryTrace = {
      classic: [],
      operational: [],
      summary: { total_used: 0, classic_count: 0, rag_count: 0, omitted_count: 0, budget_used: 0, budget_tokens: 0, latency_ms: 0 },
    };
    render(<MemoryTraceInspector trace={trace} activeTab="used" onTabChange={() => {}} />);

    expect(screen.getByText(/No memory items were attached/)).toBeInTheDocument();
  });

  it("shows filters empty state when no filters", () => {
    const trace: MemoryTrace = {
      classic: [],
      operational: [],
      summary: { total_used: 0, classic_count: 0, rag_count: 0, omitted_count: 0, budget_used: 0, budget_tokens: 0, latency_ms: 0 },
    };
    render(<MemoryTraceInspector trace={trace} activeTab="filters" onTabChange={() => {}} />);

    expect(screen.getByText(/No recall filters were reported/)).toBeInTheDocument();
  });

  it("shows prompt empty state when no prompt", () => {
    const trace: MemoryTrace = {
      classic: [],
      operational: [],
      summary: { total_used: 1, classic_count: 0, rag_count: 0, omitted_count: 0, budget_used: 0, budget_tokens: 0, latency_ms: 0 },
    };
    render(<MemoryTraceInspector trace={trace} activeTab="prompt" onTabChange={() => {}} />);

    expect(screen.getByText(/No prompt memory block was captured/)).toBeInTheDocument();
  });
});

describe("memoryTraceFromMetadata", () => {
  it("returns undefined for non-object input", () => {
    expect(memoryTraceFromMetadata(null)).toBeUndefined();
    expect(memoryTraceFromMetadata("string")).toBeUndefined();
    expect(memoryTraceFromMetadata(42)).toBeUndefined();
  });

  it("returns undefined when total_used is 0", () => {
    expect(memoryTraceFromMetadata({ summary: { total_used: 0 } })).toBeUndefined();
  });

  it("parses classic and operational memory items", () => {
    const result = memoryTraceFromMetadata({
      classic: [{ path: "/tmp/test.md", name: "test", header: "Header", mtime_ms: 1000, snippet: "snippet" }],
      operational: [{ type: "fact", summary: "Summary", score: 0.95, status: "active" }],
      summary: { total_used: 2, classic_count: 1, rag_count: 1, omitted_count: 0, budget_used: 10, budget_tokens: 100, latency_ms: 50 },
      filters_applied: { workspace: "test" },
      prompt: { formatted: "prompt text", truncated: true },
    });

    expect(result).toBeDefined();
    expect(result!.classic).toHaveLength(1);
    expect(result!.classic[0].path).toBe("/tmp/test.md");
    expect(result!.operational).toHaveLength(1);
    expect(result!.operational[0].summary).toBe("Summary");
    expect(result!.summary.total_used).toBe(2);
    expect(result!.summary.latency_ms).toBe(50);
    expect(result!.filters_applied).toEqual({ workspace: "test" });
    expect(result!.prompt?.formatted).toBe("prompt text");
    expect(result!.prompt?.truncated).toBe(true);
  });

  it("computes defaults for missing summary fields", () => {
    const result = memoryTraceFromMetadata({
      classic: [{ path: "a.md" }],
      operational: [{ summary: "b" }],
    });

    expect(result).toBeDefined();
    expect(result!.summary.total_used).toBe(2);
    expect(result!.summary.classic_count).toBe(1);
    expect(result!.summary.rag_count).toBe(1);
    expect(result!.summary.omitted_count).toBe(0);
    expect(result!.summary.budget_used).toBe(0);
    expect(result!.summary.budget_tokens).toBe(0);
    expect(result!.summary.latency_ms).toBe(0);
  });

  it("returns undefined for malformed arrays", () => {
    expect(memoryTraceFromMetadata({ classic: "not-array", operational: "not-array", summary: { total_used: 0 } })).toBeUndefined();
  });
});

function baseMessage(): ChatMessageUi {
  return {
    id: "msg-1",
    role: "agent",
    label: "Agent",
    content: "Hello",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
  };
}

function sampleMemoryTrace(): MemoryTrace {
  return {
    classic: [
      {
        path: "/home/user/.codex/memories/python_pref.md",
        name: "python_pref.md",
        header: "Python preference",
        mtime_ms: 1770000000000,
        snippet: "Uses pytest for backend validation.",
      },
    ],
    operational: [
      {
        type: "session_fact",
        summary: "Keep Python preferences visible",
        evidence: ["Use uv run pytest for backend checks."],
        paths: ["sessions/chat-1"],
        source_ids: ["mem_1"],
        score: 0.83,
        status: "active",
        created_at: "2026-04-30T10:00:00Z",
      },
    ],
    summary: {
      total_used: 2,
      classic_count: 1,
      rag_count: 1,
      omitted_count: 1,
      budget_used: 120,
      budget_tokens: 400,
      latency_ms: 62,
    },
    filters_applied: {
      workspace_slug: "personagent",
    },
    prompt: {
      formatted: "Injected memory block",
      truncated: false,
    },
  };
}
