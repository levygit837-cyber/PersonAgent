import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { AgentMessage, compactToolKindFor } from "./agent-message";
import { ReasoningBlock } from "./reasoning-block";
import { ToolBlock } from "./tool-block";
import type { ChatMessageUi, TeamRunUi, ToolBlockUi } from "../../types/chat";

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
      <ReasoningBlock reasoning={"**Identifying strategy**\n\nValidate streaming."} isStreaming={true} />,
    );

    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(container.querySelector("strong")?.textContent).toBe("Identifying strategy");
    expect(screen.getByText("Validate streaming.")).toBeInTheDocument();
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

  it("renders compact Team Mode cards with event previews and scrollable blackboard", () => {
    const message = baseAgentMessage({
      isStreaming: true,
      teamRun: compactTeamRun(),
    });

    render(<AgentMessage message={message} />);

    expect(screen.getByText("Analyst")).toBeInTheDocument();
    expect(screen.getByText("Blackboard compact snapshot")).toBeInTheDocument();
    expect(screen.getByText("actual phase")).toBeInTheDocument();
    expect(screen.queryByText("private agent reasoning")).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted claim from Analyst")).not.toBeInTheDocument();
    expect(screen.getByText("response")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Analyst"));
    expect(screen.getAllByText("thinking").length).toBeGreaterThan(0);
    expect(screen.getByText("private agent reasoning")).toBeInTheDocument();
    expect(screen.getAllByText("Agent response").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText("Blackboard compact snapshot"));
    expect(screen.getAllByText("Accepted claim from Analyst").length).toBeGreaterThan(0);
    expect(screen.getByText("Next action")).toBeInTheDocument();
  });

  it("renders compact Team Mode tool output behind a click target", () => {
    const message = baseAgentMessage({
      teamRun: compactTeamRun({
        agents: [
          {
            agentId: "builder",
            agentName: "Builder",
            agentRole: "tools",
            status: "running",
            phase: "read_tools",
            thinking: "",
            output: "",
            logs: [
              {
                id: "builder-tool-log",
                kind: "tool",
                title: "read tools",
                content: "1 result published",
                status: "completed",
                phase: "read_tools",
              },
            ],
            claims: [],
            tools: [
              {
                id: "tool-1",
                title: "read tools",
                phase: "read_tools",
                status: "completed",
                summary: "1 result published",
                calls: [{ name: "Read" }],
                results: [{ output: "file content" }],
                proposals: [],
              },
            ],
          },
        ],
      }),
    });

    render(<AgentMessage message={message} />);

    fireEvent.click(screen.getByText("Builder"));
    expect(screen.getAllByText("1 result published").length).toBeGreaterThan(0);
    expect(screen.queryByText("file content")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("output"));
    expect(screen.getByText(/file content/)).toBeInTheDocument();
  });

  it("hides the agent execution status when not streaming", () => {
    const message = baseAgentMessage({ isStreaming: false });
    render(<AgentMessage message={message} />);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("renders icon actions for completed agent output without speaker labels", () => {
    render(
      <AgentMessage
        message={baseAgentMessage({
          content: "Done",
          parts: [{ kind: "content", id: "content-1", content: "Done" }],
        })}
      />,
    );

    expect(screen.queryByText("PersonAgent")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Positive feedback" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Negative feedback" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Branch to worktree" })).toBeInTheDocument();
  });

  it("renders running read tools with a reading label", () => {
    render(<ToolBlock block={toolBlock({ name: "read_file", status: "running" })} />);
    expect(screen.getByText("Reading 1 File...")).toBeInTheDocument();
  });

  it("uses the same completed status dot size and color for tool events", () => {
    const { container } = render(
      <>
        <ToolBlock block={toolBlock({ name: "read_file", status: "completed" })} />
        <ToolBlock block={toolBlock({ name: "Edit", status: "completed", path: "src/app.ts" })} />
        <ToolBlock block={toolBlock({ name: "Grep", status: "completed", data: { pattern: "PersonAgent", matches: 1 } })} />
        <ToolBlock block={toolBlock({ name: "Glob", status: "completed", data: { pattern: "**", count: 51 } })} />
      </>,
    );

    const dots = Array.from(container.querySelectorAll<HTMLElement>(".personagent-tool-status-dot"));
    expect(dots).toHaveLength(4);
    dots.forEach((dot) => {
      expect(dot.style.width).toBe("6px");
      expect(dot.style.height).toBe("6px");
      expect(dot).toHaveClass("bg-success");
      expect(dot).toHaveClass("inline-flex");
    });
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

  it("renders Edit diffs through the file preview and starts collapsed", () => {
    window.localStorage.setItem("personagent.toolOutputVisibility", "show");

    render(
      <ToolBlock
        block={toolBlock({
          name: "Edit",
          title: "Edit",
          content: "Edited src/app.ts",
          path: "src/app.ts",
          data: {
            type: "file_edit",
            display_path: "src/app.ts",
            diff: "--- a/src/app.ts\n+++ b/src/app.ts\n@@ -3,2 +3,2 @@\n keep\n-old value\n+new value",
          },
          isCollapsed: false,
        })}
      />,
    );

    expect(screen.getByText("Edit - src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("+1")).toHaveClass("text-success");
    expect(screen.getByText("-1")).toHaveClass("text-destructive");
    expect(screen.getByText("Show")).toBeInTheDocument();
    expect(screen.queryByText("Edit preview: src/app.ts")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Show"));

    expect(screen.getByText("Edit preview: src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("new value").closest("div")).toHaveClass("text-success");
    expect(screen.getByText("old value").closest("div")).toHaveClass("text-destructive");
    expect(screen.getAllByText("4").length).toBeGreaterThan(0);
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

  it("shows the local artifact path for truncated tool output", () => {
    render(
      <ToolBlock
        forceExpanded
        block={toolBlock({
          name: "shell",
          title: "Run script",
          content: "preview line",
          data: {
            command: "python script.py",
            storage_ref: "/tmp/personagent/tool-results/conversation/call.txt",
            original_chars: 70_000,
          },
        })}
      />,
    );

    expect(screen.queryByText("/tmp/personagent/tool-results/conversation/call.txt")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show shell output" }));

    expect(screen.getByText("/tmp/personagent/tool-results/conversation/call.txt")).toBeInTheDocument();
    expect(screen.getByText("(70000 chars)")).toBeInTheDocument();
  });

  it("classifies shell find grep and rg commands as search tools", () => {
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "rg Reasoning src" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "grep -R foo src" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "find src -name '*.ts'" } }))).toBe("search");
    expect(compactToolKindFor(toolBlock({ name: "shell", data: { command: "pwd" } }))).toBe("shell");
    expect(compactToolKindFor(toolBlock({ name: "BrowserOpen" }))).toBe("browser_open");
    expect(compactToolKindFor(toolBlock({ name: "BrowserExtractContent" }))).toBe("browser_extract");
    expect(compactToolKindFor(toolBlock({ name: "TodoUpdate" }))).toBe("todo");
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

    expect(screen.getByText("Grep - PersonAgent 1 match")).toBeInTheDocument();
    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    expect(screen.queryByText("Pattern")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show search output" }));

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

    expect(screen.getByText("Glob - **/*.ts 2 files")).toBeInTheDocument();
    expect(screen.getByText("Glob - **/*.ts 2 files").closest("div")?.parentElement?.parentElement?.querySelector(".personagent-tool-status-dot")).not.toBeNull();
    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show search output" }));

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
    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show search output" }));

    expect(screen.getByText("Command")).toBeInTheDocument();
    expect(screen.getByText("find src -name '*.ts'")).toBeInTheDocument();
    expect(screen.getAllByText("src/app.ts").length).toBeGreaterThan(0);
    expect(screen.getByText("src/chat.ts")).toBeInTheDocument();
  });

  it("toggles shell output from the tool row with the shared status dot", () => {
    const { container } = render(
      <ToolBlock
        block={toolBlock({
          name: "shell",
          title: "Shell command",
          content: "command output\nexpanded only",
          data: {
            type: "shell",
            command: "pwd",
            content: "command output\nexpanded only",
            return_code: 0,
          },
        })}
      />,
    );

    expect(screen.getByText("pwd")).toBeInTheDocument();
    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    expect(container.querySelector(".personagent-tool-status-dot")).not.toBeNull();
    expect(screen.queryByText("expanded only")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show shell output" }));

    expect(screen.getByText(/expanded only/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide shell output" }));
    expect(screen.queryByText("expanded only")).not.toBeInTheDocument();
  });

  it("auto-collapses every tool output even when visibility is set to show", () => {
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

    const generic = render(
      <ToolBlock
        block={toolBlock({
          name: "WebFetch",
          title: "WebFetch",
          content: "fetched page",
          data: { url: "https://example.com" },
        })}
      />,
    );

    expect(screen.getByText("Fetch https://example.com - Show")).toBeInTheDocument();
    expect(screen.queryByText("fetched page")).not.toBeInTheDocument();
    generic.unmount();

    render(
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

    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    expect(screen.getByText("Grep - PersonAgent 1 match")).toBeInTheDocument();
    expect(screen.queryByText("Pattern")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show search output" }));

    expect(screen.getByText("Pattern")).toBeInTheDocument();
    expect(screen.getAllByText("PersonAgent").length).toBeGreaterThan(0);
  });

  it("keeps grouped search calls individually collapsed after the group opens", () => {
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
              id: "grep_1",
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
            }),
            toolBlock({
              id: "find_1",
              name: "shell",
              title: "Shell command",
              content: "src/app.ts\nsrc/chat.ts",
              data: {
                type: "shell",
                command: "find src -name '*.ts'",
                content: "src/app.ts\nsrc/chat.ts",
                return_code: 0,
              },
            }),
          ],
          parts: [
            { kind: "tool", id: "part_grep_1", toolBlockId: "grep_1" },
            { kind: "tool", id: "part_find_1", toolBlockId: "find_1" },
          ],
        })}
      />,
    );

    expect(screen.getByText("Search 2 times >")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Search 2 times >"));

    expect(screen.queryByText("Output - Show")).not.toBeInTheDocument();
    expect(screen.getByText("Grep - PersonAgent 1 match")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Show search output" })).toHaveLength(2);
    expect(screen.queryByText("Pattern")).not.toBeInTheDocument();
    expect(screen.queryByText("Command")).not.toBeInTheDocument();
  });

  it("keeps future tool calls collapsed after a manual expand", () => {
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
          name: "WebFetch",
          title: "WebFetch",
          content: "fetched page",
          data: { url: "https://example.com" },
        })}
      />,
    );

    expect(screen.getByText("Fetch https://example.com - Show")).toBeInTheDocument();
    expect(screen.queryByText("fetched page")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Fetch https:\/\/example\.com - Show/ }));
    expect(screen.getByText("fetched page")).toBeInTheDocument();
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

  it("keeps grouped generic tool outputs individually collapsed", () => {
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

    expect(screen.getByText("Fetched 2 URLs >")).toBeInTheDocument();
    expect(screen.queryByText("first page")).not.toBeInTheDocument();
    expect(screen.queryByText("second page")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Fetched 2 URLs >"));

    expect(screen.getByText("Fetch https://one.example - Show")).toBeInTheDocument();
    expect(screen.getByText("Fetch https://two.example - Show")).toBeInTheDocument();
    expect(screen.queryByText("first page")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Fetch https:\/\/one\.example - Show/ }));

    expect(screen.getByText("first page")).toBeInTheDocument();
    expect(screen.queryByText("second page")).not.toBeInTheDocument();
  });

  it("groups BrowserOpen calls as opened tabs with normalized output", () => {
    window.localStorage.setItem("personagent.toolOutputVisibility", "hide");
    const message = baseAgentMessage({
      toolBlocks: [
        browserOpenBlock("open_1", "https://one.example", "One"),
        browserOpenBlock("open_2", "https://two.example", "Two"),
        browserOpenBlock("open_3", "https://three.example", "Three"),
      ],
      parts: [
        { kind: "tool", id: "part_open_1", toolBlockId: "open_1" },
        { kind: "tool", id: "part_open_2", toolBlockId: "open_2" },
        { kind: "tool", id: "part_open_3", toolBlockId: "open_3" },
      ],
    });

    render(<AgentMessage message={message} />);

    expect(screen.getByText("Opened 3 Tabs >")).toBeInTheDocument();
    expect(screen.queryByText(/Final URL: https:\/\/one\.example/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Opened 3 Tabs >"));

    expect(screen.getByText("Opened One - Show")).toBeInTheDocument();
    expect(screen.queryByText(/Final URL: https:\/\/one\.example/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Opened One - Show"));

    expect(screen.getByText(/Final URL: https:\/\/one\.example/)).toBeInTheDocument();
    expect(screen.queryByText(/Page ID: page-open_2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"type":"browser_open"/)).not.toBeInTheDocument();
  });

  it("groups BrowserExtractContent calls by URL and keeps content in code blocks", () => {
    window.localStorage.setItem("personagent.toolOutputVisibility", "hide");
    const message = baseAgentMessage({
      toolBlocks: [
        toolBlock({
          id: "extract_1",
          name: "BrowserExtractContent",
          title: "BrowserExtractContent",
          content: "First article content",
          path: "https://one.example",
          data: {
            type: "browser_extract_content",
            title: "One",
            url: "https://one.example",
            page_id: "page-one",
            cache_key: "page_111",
            content: "First article content",
            content_chars: 21,
            chunk_count: 1,
          },
        }),
        toolBlock({
          id: "extract_2",
          name: "BrowserExtractContent",
          title: "BrowserExtractContent",
          content: "Second article content",
          path: "https://two.example",
          data: {
            type: "browser_extract_content",
            title: "Two",
            url: "https://two.example",
            page_id: "page-two",
            cache_key: "page_222",
            content: "Second article content",
            content_chars: 22,
            chunk_count: 1,
          },
        }),
      ],
      parts: [
        { kind: "tool", id: "part_extract_1", toolBlockId: "extract_1" },
        { kind: "tool", id: "part_extract_2", toolBlockId: "extract_2" },
      ],
    });

    render(<AgentMessage message={message} />);

    expect(screen.getByText("Extracted content from 2 URLs >")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Extracted content from 2 URLs >"));

    expect(screen.getByText("Extracted content from One - Show")).toBeInTheDocument();
    expect(screen.queryByText(/Cache key: page_111/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Extracted content from One - Show"));

    expect(screen.getByText(/Cache key: page_111/)).toBeInTheDocument();
    expect(screen.getByText(/First article content/).tagName.toLowerCase()).toBe("pre");
  });

  it("keeps running Browser tool input collapsed while showing the target query", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "BrowserSearch",
          title: "BrowserSearch",
          status: "running",
          content: JSON.stringify({ query: "open source LLM comparison", max_results: 4 }),
          data: {
            query: "open source LLM comparison",
            max_results: 4,
          },
          isCollapsed: false,
        })}
      />,
    );

    expect(screen.getByText("Searching open source LLM comparison - Show")).toBeInTheDocument();
    expect(screen.queryByText(/max_results/)).not.toBeInTheDocument();
  });

  it("keeps grouped parallel tool rows visible while running with outputs collapsed", () => {
    window.localStorage.setItem("personagent.toolOutputVisibility", "hide");
    const runningMessage = baseAgentMessage({
      toolBlocks: [
        toolBlock({
          id: "fetch_1",
          name: "WebFetch",
          title: "WebFetch",
          status: "completed",
          content: "first page",
          data: { url: "https://one.example" },
        }),
        toolBlock({
          id: "fetch_2",
          name: "WebFetch",
          title: "WebFetch",
          status: "running",
          content: "second page partial",
          data: { url: "https://two.example" },
          isCollapsed: false,
        }),
      ],
      parts: [
        { kind: "tool", id: "part_fetch_1", toolBlockId: "fetch_1" },
        { kind: "tool", id: "part_fetch_2", toolBlockId: "fetch_2" },
      ],
      isStreaming: true,
    });
    const completedMessage = {
      ...runningMessage,
      toolBlocks: runningMessage.toolBlocks.map((block) => ({ ...block, status: "completed" as const, isCollapsed: true })),
      isStreaming: false,
    };

    const { rerender } = render(<AgentMessage message={runningMessage} />);

    expect(screen.getByText("Fetching 2 URLs...")).toBeInTheDocument();
    expect(screen.getByText("Fetch https://one.example - Show")).toBeInTheDocument();
    expect(screen.getByText("Fetch https://two.example running - Show")).toBeInTheDocument();
    expect(screen.queryByText("first page")).not.toBeInTheDocument();
    expect(screen.queryByText("second page partial")).not.toBeInTheDocument();

    rerender(<AgentMessage message={completedMessage} />);

    expect(screen.getByText("Fetched 2 URLs >")).toBeInTheDocument();
    expect(screen.queryByText("first page")).not.toBeInTheDocument();
    expect(screen.queryByText("second page partial")).not.toBeInTheDocument();
  });

  it("renders TodoWrite as an exposed checklist with item status dots", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "TodoWrite",
          title: "TodoWrite",
          status: "completed",
          content: "Updated 3 todos.",
          data: {
            type: "todos",
            todos: [
              { id: "inspect", content: "Inspect current renderer", status: "completed" },
              { id: "build", content: "Build todo panel", status: "in_progress" },
              { id: "verify", content: "Verify chat rendering", status: "pending" },
            ],
          },
          isCollapsed: true,
        })}
      />,
    );

    expect(screen.getByTestId("todo-tracker")).toBeInTheDocument();
    expect(screen.getByText("Todos")).toBeInTheDocument();
    expect(screen.getByText("1/3 done")).toBeInTheDocument();

    const completedRow = screen.getByText("Inspect current renderer").closest("li");
    const activeRow = screen.getByText("Build todo panel").closest("li");
    const pendingRow = screen.getByText("Verify chat rendering").closest("li");

    expect(completedRow).not.toBeNull();
    expect(activeRow).not.toBeNull();
    expect(pendingRow).not.toBeNull();
    expect(within(completedRow!).getByLabelText("completed")).toHaveClass("bg-success");
    expect(within(activeRow!).getByLabelText("in progress")).toHaveClass("bg-warning");
    expect(within(pendingRow!).getByLabelText("pending")).toHaveClass("bg-warning");
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("keeps completed todos visible when rendered as a static tool block", () => {
    render(
      <ToolBlock
        block={toolBlock({
          name: "TodoWrite",
          title: "TodoWrite",
          status: "completed",
          data: {
            type: "todos",
            todos: [
              { id: "inspect", content: "Inspect current renderer", status: "completed" },
              { id: "build", content: "Build todo panel", status: "completed" },
            ],
          },
        })}
      />,
    );

    expect(screen.getByTestId("todo-tracker")).toBeInTheDocument();
    expect(screen.getByText("2/2 done")).toBeInTheDocument();
  });

  it("does not render todo tool blocks inside the agent message flow", () => {
    const message = baseAgentMessage({
      toolBlocks: [
        toolBlock({
          id: "todo_1",
          name: "TodoWrite",
          data: {
            todos: [
              { id: "inspect", content: "Inspect current renderer", status: "in_progress" },
              { id: "build", content: "Build todo panel", status: "pending" },
            ],
          },
        }),
        toolBlock({
          id: "todo_2",
          name: "TodoWrite",
          data: {
            todos: [
              { id: "inspect", content: "Inspect current renderer", status: "completed" },
              { id: "build", content: "Build todo panel", status: "in_progress" },
            ],
          },
        }),
      ],
      parts: [
        { kind: "tool", id: "part_todo_1", toolBlockId: "todo_1" },
        { kind: "tool", id: "part_todo_2", toolBlockId: "todo_2" },
      ],
    });

    render(<AgentMessage message={message} />);

    expect(screen.queryByTestId("todo-tracker")).not.toBeInTheDocument();
    expect(screen.queryByText("Inspect current renderer")).not.toBeInTheDocument();
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

  it("renders generated image artifact refs without base64 data", () => {
    const message = baseAgentMessage({
      parts: [
        {
          kind: "image",
          id: "image-ref-1",
          image: {
            mime_type: "image/png",
            url: "http://localhost:8000/artifacts/conversation/generated-images/image.png",
            artifact_id: "image.png",
            alt: "Stored generated image",
            size_bytes: 128,
            sha256: "abc",
          },
        },
      ],
    });

    render(<AgentMessage message={message} />);

    expect(screen.getByRole("img", { name: "Stored generated image" })).toHaveAttribute(
      "src",
      "http://localhost:8000/artifacts/conversation/generated-images/image.png",
    );
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

function browserOpenBlock(id: string, url: string, title: string): ToolBlockUi {
  return toolBlock({
    id,
    name: "BrowserOpen",
    title: `Open ${url}`,
    content: JSON.stringify({
      type: "browser_open",
      url,
      final_url: url,
      title,
      page_id: `page-${id}`,
      window_id: `page-${id}`,
    }),
    path: url,
    data: {
      type: "browser_open",
      url,
      final_url: url,
      title,
      page_id: `page-${id}`,
      window_id: `page-${id}`,
      opened_page_count: 3,
    },
  });
}

function compactTeamRun(overrides: Partial<TeamRunUi> = {}): TeamRunUi {
  return {
    runId: "run-1",
    title: "Team Mode",
    status: "running",
    round: 1,
    actualPhase: "independent",
    agents: [
      {
        agentId: "analyst",
        agentName: "Analyst",
        agentRole: "requirements",
        status: "running",
        phase: "independent",
        thinking: "private agent reasoning",
        output: "Agent response",
        digest: "Agent digest",
        logs: [
          {
            id: "analyst-thinking-1",
            kind: "thinking",
            title: "Thinking",
            content: "private agent reasoning",
            status: "running",
            phase: "independent",
          },
          {
            id: "analyst-response-1",
            kind: "response",
            title: "Response",
            content: "Agent response",
            status: "running",
            phase: "independent",
          },
        ],
        claims: [
          {
            id: "claim-1",
            type: "claim",
            text: "Accepted claim from Analyst",
            agentId: "analyst",
            agentName: "Analyst",
          },
        ],
        tools: [],
      },
    ],
    blackboard: {
      status: "running",
      actualPhase: "independent",
      nextAction: "Debate",
      claims: [
        {
          id: "claim-1",
          type: "claim",
          text: "Accepted claim from Analyst",
          agentId: "analyst",
          agentName: "Analyst",
        },
      ],
      evidence: [],
      decisions: [],
      blockers: [],
      coverage: [],
      coverageComplete: 1,
      coverageTotal: 2,
      coherencyScore: 0.84,
      tools: [],
    },
    votes: [],
    ...overrides,
  };
}
