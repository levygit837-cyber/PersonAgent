import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentMessage, MarkdownContent } from "./agent-message";
import type { ChatMessageUi } from "../../types/chat";

describe("MarkdownContent", () => {
  it("renders wide tables inside a constrained horizontal scroller", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "| Tendencia | Evidencia principal | Impactos chave | Principais desafios |",
          "| --- | --- | --- | --- |",
          "| Deflacao da bolha | Forbes e MIT Sloan<br>Stanford AI Index | Pressao para justificar ROI | Risco de under-investment |",
        ].join("\n")}
      />,
    );

    const table = container.querySelector("table");
    const scroller = table?.parentElement;

    expect(table).not.toBeNull();
    expect(scroller).not.toBeNull();
    expect(scroller).toHaveClass("overflow-x-auto");
    expect(scroller).toHaveClass("max-w-full");
    expect(container.querySelector("td br")).not.toBeNull();
  });
});

describe("AgentMessage Team Mode trace", () => {
  it("does not render persisted empty assistant shells", () => {
    render(<AgentMessage message={emptyPersistedAgentMessage()} />);

    expect(screen.queryByText("PersonAgent")).not.toBeInTheDocument();
  });

  it("keeps the live streaming shell visible before the first chunk", () => {
    render(<AgentMessage message={{ ...emptyPersistedAgentMessage(), isStreaming: true }} />);

    expect(screen.queryByText("PersonAgent")).not.toBeInTheDocument();
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("shows real agent thinking/output content instead of fixed empty Thinking placeholders", () => {
    render(<AgentMessage message={teamModeMessage()} />);

    expect(screen.getByText("Real thought")).toBeInTheDocument();
    expect(screen.getByText("Agent output")).toBeInTheDocument();
    expect(screen.queryByText("Thinking")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Analyst/i }));

    expect(screen.getAllByText("Real thought").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Agent output").length).toBeGreaterThan(0);
    expect(screen.queryByText("Fixed placeholder")).not.toBeInTheDocument();
  });

  it("stages Team Mode agent and blackboard card arrivals in sequence", () => {
    const message = teamModeMessage();
    message.teamRun?.agents.push({
      ...message.teamRun.agents[0],
      agentId: "builder",
      agentName: "Builder",
      agentRole: "Implementation",
      logs: [],
    });

    const { container } = render(<AgentMessage message={message} />);
    const cards = container.querySelectorAll(".personagent-team-card-arrival");

    expect(cards).toHaveLength(3);
    expect((cards[0] as HTMLElement).style.getPropertyValue("--personagent-team-card-delay")).toBe("0ms");
    expect((cards[1] as HTMLElement).style.getPropertyValue("--personagent-team-card-delay")).toBe("120ms");
    expect((cards[2] as HTMLElement).style.getPropertyValue("--personagent-team-card-delay")).toBe("240ms");
  });
});

describe("AgentMessage memory trace", () => {
  it("shows a compact memory badge and opens the inline inspector", () => {
    render(<AgentMessage message={memoryTraceMessage()} />);

    const badge = screen.getByRole("button", { name: "Memory trace: 2 memories used" });
    expect(badge).toHaveTextContent("Memory 2 · 62ms");
    expect(screen.queryByText("Memory trace")).not.toBeInTheDocument();

    fireEvent.click(badge);

    expect(screen.getByText("Memory trace")).toBeInTheDocument();
    expect(screen.getByText("Keep Python preferences visible")).toBeInTheDocument();
    expect(screen.getByText("python_pref.md")).toBeInTheDocument();
    expect(screen.getByText("Uses pytest for backend validation.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(screen.getByText("62ms")).toBeInTheDocument();
    expect(screen.getByText(/workspace_slug/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Prompt" }));
    expect(screen.getByText(/Injected memory block/)).toBeInTheDocument();
  });
});

function emptyPersistedAgentMessage(): ChatMessageUi {
  return {
    id: "empty-agent",
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
  };
}

function memoryTraceMessage(): ChatMessageUi {
  return {
    ...emptyPersistedAgentMessage(),
    id: "agent-memory",
    content: "Answer using memory.",
    metadata: {
      memory_trace: {
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
      },
    },
  };
}

function teamModeMessage(): ChatMessageUi {
  return {
    id: "agent-team",
    role: "agent",
    label: "Team Mode",
    content: "",
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: true,
    isReasoningStreaming: false,
    teamRun: {
      runId: "run-1",
      title: "Team Mode",
      status: "running",
      round: 1,
      actualPhase: "independent",
      agents: [
        {
          agentId: "analyst",
          agentName: "Analyst",
          agentRole: "Risk Review",
          status: "running",
          phase: "independent",
          round: 1,
          thinking: "",
          output: "",
          logs: [
            {
              id: "empty-thinking-1",
              kind: "thinking",
              title: "Thinking",
              content: "",
              status: "running",
              phase: "independent",
              round: 1,
            },
            {
              id: "empty-thinking-2",
              kind: "thinking",
              title: "Fixed placeholder",
              status: "running",
              phase: "independent",
              round: 1,
            },
            {
              id: "real-thinking",
              kind: "thinking",
              title: "Thinking",
              content: "Real thought",
              status: "running",
              phase: "independent",
              round: 1,
            },
            {
              id: "real-output",
              kind: "response",
              title: "Output",
              content: "Agent output",
              status: "running",
              phase: "independent",
              round: 1,
            },
          ],
          claims: [],
          tools: [],
        },
      ],
      blackboard: {
        status: "running",
        actualPhase: "independent",
        claims: [],
        evidence: [],
        decisions: [],
        blockers: [],
        coverage: [],
        tools: [],
      },
      votes: [],
    },
  };
}
