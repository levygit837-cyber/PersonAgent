import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AgentMessage, compactToolKindFor } from "./agent-message";
import { ReasoningBlock } from "./reasoning-block";
import { ToolBlock } from "./tool-block";
import type { ChatMessageUi, ToolBlockUi } from "../../types/chat";

describe("chat rendering", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("groups consecutive read events into a compact block", () => {
    const message: ChatMessageUi = {
      id: "agent",
      role: "agent",
      label: "PersonAgent",
      content: "",
      reasoning: "",
      reasoningBlocks: [],
      toolBlocks: [
        {
          id: "call_1",
          name: "read_file",
          status: "completed",
          title: "Read README.md",
          message: "",
          content: "",
          path: "README.md",
          isCollapsed: true,
        },
        {
          id: "call_2",
          name: "read_file",
          status: "completed",
          title: "Read package.json",
          message: "",
          content: "",
          path: "package.json",
          isCollapsed: true,
        },
      ],
      teamEvents: [],
      parts: [
        { kind: "tool", id: "part_1", toolBlockId: "call_1" },
        { kind: "tool", id: "part_2", toolBlockId: "call_2" },
      ],
      isStreaming: false,
      isReasoningStreaming: false,
    };

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Read 2 Files >")).toBeInTheDocument();
  });

  it("renders completed reasoning collapsed by default", () => {
    render(<ReasoningBlock reasoning="Read files\nPlan patch" isStreaming={false} />);
    expect(screen.getByText("Reasoning >")).toBeInTheDocument();
    expect(screen.queryByText("Read files")).not.toBeInTheDocument();
  });

  it("renders markdown emphasis inside reasoning blocks", () => {
    const { container } = render(
      <ReasoningBlock reasoning={"**Identificando estratégia**\n\nValidar streaming."} isStreaming={true} />,
    );

    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(container.querySelector("strong")?.textContent).toBe("Identificando estratégia");
    expect(screen.getByText("Validar streaming.")).toBeInTheDocument();
  });

  it("keeps reasoning-only agent output expanded for Qwen length stops", () => {
    const message = baseAgentMessage({
      reasoning: "Thinking Process:\n\n1. Analyze the request.",
      reasoningBlocks: [
        {
          id: "reasoning_1",
          content: "Thinking Process:\n\n1. Analyze the request.",
          isStreaming: false,
        },
      ],
      parts: [{ kind: "reasoning", id: "part_reasoning", reasoningBlockId: "reasoning_1" }],
      isStreaming: false,
      isReasoningStreaming: false,
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Reasoning Hide")).toBeInTheDocument();
    expect(screen.getByText("Thinking Process:")).toBeInTheDocument();
  });

  it("shows the agent execution status only while streaming", () => {
    const message = baseAgentMessage({ isStreaming: true });
    render(<AgentMessage message={message} />);
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("hides the agent execution status after streaming content starts", () => {
    const message = baseAgentMessage({
      content: "Visible answer",
      isStreaming: true,
      parts: [{ kind: "content", id: "part_content", content: "Visible answer" }],
    });

    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(screen.getByText("Visible answer")).toBeInTheDocument();
  });

  it("shows reasoning instead of the global execution status while reasoning streams", () => {
    const message = baseAgentMessage({
      reasoning: "Inspect files",
      reasoningBlocks: [{ id: "reasoning_1", content: "Inspect files", isStreaming: true }],
      parts: [{ kind: "reasoning", id: "part_reasoning", reasoningBlockId: "reasoning_1" }],
      isStreaming: true,
      isReasoningStreaming: true,
    });

    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(screen.getByText("Inspect files")).toBeInTheDocument();
  });

  it("renders Qwen reasoning even if the message parts list missed the reasoning block", () => {
    const message = baseAgentMessage({
      reasoning: "Thinking Process:\n\n1. Analyze the request.",
      reasoningBlocks: [
        {
          id: "reasoning_1",
          content: "Thinking Process:\n\n1. Analyze the request.",
          isStreaming: true,
        },
      ],
      parts: [],
      isStreaming: true,
      isReasoningStreaming: true,
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(screen.getByText("Thinking Process:")).toBeInTheDocument();
  });

  it("renders orphan Qwen reasoning when content or tool parts already exist", () => {
    const message = baseAgentMessage({
      content: "Final answer",
      reasoning: "Thinking Process:\n\n1. Analyze the request.",
      reasoningBlocks: [
        {
          id: "reasoning_1",
          content: "Thinking Process:\n\n1. Analyze the request.",
          isStreaming: true,
        },
      ],
      parts: [{ kind: "content", id: "part_content", content: "Final answer" }],
      isStreaming: true,
      isReasoningStreaming: true,
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(screen.getByText("Thinking Process:")).toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
  });

  it("keeps Kimi mixed reasoning collapsed while rendering visible output", () => {
    const message = baseAgentMessage({
      content: "OK",
      reasoning: 'The user wants me to respond with only "OK".',
      reasoningBlocks: [
        {
          id: "reasoning_1",
          content: 'The user wants me to respond with only "OK".',
          isStreaming: false,
        },
      ],
      parts: [
        { kind: "reasoning", id: "part_reasoning", reasoningBlockId: "reasoning_1" },
        { kind: "content", id: "part_content", content: "OK" },
      ],
      isStreaming: false,
      isReasoningStreaming: false,
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Reasoning >")).toBeInTheDocument();
    expect(screen.queryByText('The user wants me to respond with only "OK".')).not.toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("hides the agent execution status once a tool event exists", () => {
    const message = baseAgentMessage({
      isStreaming: true,
      toolBlocks: [toolBlock({ id: "call_1", name: "Grep", status: "running" })],
      parts: [{ kind: "tool", id: "part_tool", toolBlockId: "call_1" }],
    });

    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(screen.getByText("Searching...")).toBeInTheDocument();
  });

  it("renders Team Mode trace events as progress", () => {
    const message = baseAgentMessage({
      isStreaming: true,
      teamEvents: [
        {
          id: "run-1-round-1-analyst",
          kind: "turn",
          title: "Analyst",
          detail: "Analysis",
          status: "running",
          content: "Initial analysis",
        },
        {
          id: "run-1-vote-1-reviewer",
          kind: "vote",
          title: "Reviewer approved",
          detail: "Ready to synthesize",
          status: "approved",
        },
      ],
    });

    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(screen.getByText("Analyst")).toBeInTheDocument();
    expect(screen.getByText("Initial analysis")).toBeInTheDocument();
    expect(screen.getByText("Reviewer approved")).toBeInTheDocument();
  });

  it("renders Team Mode blackboard and coordinator trace events", () => {
    const message = baseAgentMessage({
      isStreaming: true,
      teamEvents: [
        {
          id: "run-1-blackboard-1",
          kind: "blackboard",
          title: "Analyst published",
          detail: "independent_round #1",
          status: "completed",
          content: "Initial decision",
        },
        {
          id: "run-1-debate-2",
          kind: "debate",
          title: "Debate round 2",
          detail: "Blackboard review",
          status: "running",
        },
        {
          id: "run-1-coordinator",
          kind: "coordinator",
          title: "Coordinator",
          detail: "Final synthesis",
          status: "running",
        },
      ],
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Analyst published")).toBeInTheDocument();
    expect(screen.getByText("Initial decision")).toBeInTheDocument();
    expect(screen.getByText("Debate round 2")).toBeInTheDocument();
    expect(screen.getByText("Coordinator")).toBeInTheDocument();
  });

  it("hides the agent execution status when not streaming", () => {
    const message = baseAgentMessage({ isStreaming: false });
    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("renders running read tools with a reading label", () => {
    render(<ToolBlock block={toolBlock({ name: "read_file", status: "running" })} />);
    expect(screen.getByText("Reading 1 File...")).toBeInTheDocument();
  });

  it("renders created Write output with added line count and scrollable content", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "Write",
          title: "Write",
          content: "Wrote hello.py",
          path: "hello.py",
          data: {
            type: "file_write",
            display_path: "hello.py",
            content: "Wrote hello.py",
            written_content: "alpha\nbeta\n",
            added_lines: 2,
            removed_lines: 0,
          },
          isCollapsed: true,
        })}
      />,
    );

    expect(screen.getByText("+2")).toHaveClass("text-success");
    expect(screen.getByText("Write - hello.py")).toBeInTheDocument();
    expect(screen.queryByText("Wrote hello.py")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Show"));

    expect(screen.getByText("Hide")).toBeInTheDocument();
    expect(screen.getByText("alpha").closest("div")).toHaveClass("text-success");
    expect(screen.getByText("beta").closest("div")).toHaveClass("text-success");
  });

  it("renders overwritten Write diff with added and removed line colors", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "Write",
          title: "Write",
          content: "Wrote hello.py",
          path: "hello.py",
          data: {
            type: "file_write",
            display_path: "hello.py",
            content: "Wrote hello.py",
            diff: "--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n unchanged\n-old\n+new",
            added_lines: 1,
            removed_lines: 1,
          },
          isCollapsed: true,
        })}
      />,
    );

    expect(screen.getByText("+1")).toHaveClass("text-success");
    expect(screen.getByText("-1")).toHaveClass("text-destructive");
    expect(screen.getByText("Write - hello.py")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Show"));

    expect(screen.getByText("new").closest("div")).toHaveClass("text-success");
    expect(screen.getByText("old").closest("div")).toHaveClass("text-destructive");
  });

  it("groups search tools into a compact block", () => {
    const message: ChatMessageUi = baseAgentMessage({
      toolBlocks: [
        toolBlock({ id: "call_1", name: "Grep", status: "completed" }),
        toolBlock({ id: "call_2", name: "Glob", status: "completed" }),
      ],
      parts: [
        { kind: "tool", id: "part_1", toolBlockId: "call_1" },
        { kind: "tool", id: "part_2", toolBlockId: "call_2" },
      ],
    });

    render(<AgentMessage message={message} />);
    expect(screen.getByText("Search 2 times >")).toBeInTheDocument();
  });

  it("renders running search tools with a searching label", () => {
    render(<ToolBlock block={toolBlock({ name: "Grep", status: "running" })} />);
    expect(screen.getByText("Searching...")).toBeInTheDocument();
  });

  it("classifies shell find grep and rg commands as search tools", () => {
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "rg Reasoning src" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "grep -R foo src" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "find src -name '*.ts'" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "pwd" } }))).toBe("shell");
  });

  it("shows structured grep output when expanded", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "Grep",
          title: "Grep PersonAgent",
          content: "src/components/chat/tool-block.tsx:84:function SearchToolEvent()",
          data: {
            type: "search_results",
            display_path: "src",
            pattern: "PersonAgent",
            matches: 1,
            shown: 1,
            content: "src/components/chat/tool-block.tsx:84:function SearchToolEvent()",
          },
        })}
      />,
    );

    expect(screen.queryByText("Pattern")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Output - Show"));

    expect(screen.getByText("Pattern")).toBeInTheDocument();
    expect(screen.getByText("PersonAgent")).toBeInTheDocument();
    expect(screen.getByText("src/components/chat/tool-block.tsx")).toBeInTheDocument();
    expect(screen.getByText("84")).toBeInTheDocument();
    expect(screen.getByText("function SearchToolEvent()")).toBeInTheDocument();
  });

  it("shows glob file results when expanded", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "Glob",
          title: "Glob **/*.ts",
          content: "src/app.ts\nsrc/chat.ts",
          data: {
            type: "glob_results",
            display_path: ".",
            pattern: "**/*.ts",
            matches: ["src/app.ts", "src/chat.ts"],
            count: 2,
            content: "src/app.ts\nsrc/chat.ts",
          },
        })}
      />,
    );

    fireEvent.click(screen.getByText("Output - Show"));

    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getAllByText("src/app.ts").length).toBeGreaterThan(0);
    expect(screen.getByText("src/chat.ts")).toBeInTheDocument();
  });

  it("shows shell find output through the search renderer", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "shell",
          title: "Shell command",
          content: "src/app.ts\nsrc/chat.ts",
          data: {
            type: "shell",
            command: "find src -name '*.ts'",
            content: "src/app.ts\nsrc/chat.ts",
            return_code: 0,
          },
        })}
      />,
    );

    expect(screen.getByText("Find src -name '*.ts'")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Output - Show"));

    expect(screen.getByText("Command")).toBeInTheDocument();
    expect(screen.getByText("find src -name '*.ts'")).toBeInTheDocument();
    expect(screen.getAllByText("src/app.ts").length).toBeGreaterThan(0);
    expect(screen.getByText("src/chat.ts")).toBeInTheDocument();
  });

  it("persists output visibility across future tool calls", () => {
    const first = render(
      <ToolBlock
        block={toolBlock({
          name: "Write",
          title: "Write",
          content: "Wrote first.py",
          path: "first.py",
          data: {
            type: "file_write",
            display_path: "first.py",
            written_content: "alpha\n",
          },
          isCollapsed: true,
        })}
      />,
    );

    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Show"));
    expect(screen.getByText("alpha")).toBeInTheDocument();
    first.unmount();

    const second = render(
      <ToolBlock
        block={toolBlock({
          name: "Grep",
          title: "Grep PersonAgent",
          content: "src/app.ts:1:PersonAgent",
          data: {
            type: "search_results",
            pattern: "PersonAgent",
            matches: 1,
            shown: 1,
            content: "src/app.ts:1:PersonAgent",
          },
        })}
      />,
    );

    expect(screen.getByText("Output - Hide")).toBeInTheDocument();
    expect(screen.getByText("Pattern")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Output - Hide"));
    expect(screen.queryByText("Pattern")).not.toBeInTheDocument();
    second.unmount();

    render(
      <ToolBlock
        block={toolBlock({
          name: "Write",
          title: "Write",
          content: "Wrote next.py",
          path: "next.py",
          data: {
            type: "file_write",
            display_path: "next.py",
            written_content: "beta\n",
          },
          isCollapsed: false,
        })}
      />,
    );

    expect(screen.getByText("Show")).toBeInTheDocument();
    expect(screen.queryByText("beta")).not.toBeInTheDocument();
  });

  it("applies persisted visibility to grouped generic tool outputs", () => {
    const setup = render(
      <ToolBlock
        block={toolBlock({
          name: "Write",
          title: "Write",
          content: "Wrote first.py",
          path: "first.py",
          data: {
            type: "file_write",
            display_path: "first.py",
            written_content: "alpha\n",
          },
          isCollapsed: true,
        })}
      />,
    );

    fireEvent.click(screen.getByText("Show"));
    setup.unmount();

    render(
      <AgentMessage
        message={baseAgentMessage({
          toolBlocks: [
            toolBlock({
              id: "fetch_1",
              name: "WebFetch",
              title: "WebFetch",
              content: "first page",
              data: { url: "https://one.example" },
            }),
            toolBlock({
              id: "fetch_2",
              name: "WebFetch",
              title: "WebFetch",
              content: "second page",
              data: { url: "https://two.example" },
            }),
          ],
          parts: [
            { kind: "tool", id: "part_fetch_1", toolBlockId: "fetch_1" },
            { kind: "tool", id: "part_fetch_2", toolBlockId: "fetch_2" },
          ],
        })}
      />,
    );

    expect(screen.getByText("Fetched 2 URLs")).toBeInTheDocument();
    expect(screen.getByText("first page")).toBeInTheDocument();
    expect(screen.getByText("second page")).toBeInTheDocument();
  });

  it("renders generated images inline without markdown conversion", () => {
    const message = baseAgentMessage({
      parts: [
        {
          kind: "image",
          id: "image-1",
          image: {
            mime_type: "image/png",
            data: "iVBORw0KGgo=",
            alt: "Vertex generated image",
          },
        },
      ],
      isStreaming: true,
    });

    render(<AgentMessage message={message} />);

    const image = screen.getByRole("img", { name: "Vertex generated image" });
    expect(image).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });
});

function baseAgentMessage(overrides: Partial<ChatMessageUi> = {}): ChatMessageUi {
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

function toolBlock(overrides: Partial<ToolBlockUi> = {}): ToolBlockUi {
  return {
    id: "call",
    name: "read_file",
    status: "completed",
    title: "Read README.md",
    message: "",
    content: "",
    path: "README.md",
    data: undefined,
    isCollapsed: true,
    ...overrides,
  };
}
