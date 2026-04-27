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
});

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
