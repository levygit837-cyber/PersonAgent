import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessageUi } from "../../types/chat";
import { useChatStore } from "../../stores/chat-store";
import { UserMessage } from "./user-message";

const originalRewindUserMessage = useChatStore.getState().rewindUserMessage;

describe("UserMessage", () => {
  beforeEach(() => {
    useChatStore.setState({ isStreaming: false, rewindUserMessage: originalRewindUserMessage });
  });

  it("renders user messages with a background and no speaker label", () => {
    const { container } = render(<UserMessage message={message("Plain request")} />);

    expect(screen.queryByText("User")).not.toBeInTheDocument();
    expect(screen.getByText("Plain request").closest(".bg-foreground\\/\\[0\\.055\\]")).not.toBeNull();
    expect(container.querySelector("article")?.className).toContain("justify-end");
  });

  it("renders structured context attachments without raw selected lines", () => {
    render(
      <UserMessage
        message={message("Apply with a concise tone", {
          context_attachments: [
            {
              type: "viewer_annotation",
              label: "@Annotation#1",
              display_path: "src/app.ts",
              start_line: 8,
              end_line: 24,
              text: "Rewrite this guidance",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("@Annotation#1")).toBeInTheDocument();
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("L8-24")).toBeInTheDocument();
    expect(screen.getByText("Apply with a concise tone")).toBeInTheDocument();
    expect(screen.queryByText(/Selected lines/i)).not.toBeInTheDocument();
  });

  it("renders @ skill attachments with invocation context", () => {
    render(
      <UserMessage
        message={message("Use @skill:debug-root-cause", {
          context_attachments: [
            {
              type: "skill",
              label: "@skill:debug-root-cause",
              invocation_name: "debug-root-cause",
              slash_name: "/debug-root-cause",
              display_path: ".personagent/skills/debug-root-cause/SKILL.md",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("@skill:debug-root-cause")).toBeInTheDocument();
    expect(screen.getByText("/debug-root-cause")).toBeInTheDocument();
    expect(screen.getByText(".personagent/skills/debug-root-cause/SKILL.md")).toBeInTheDocument();
  });

  it("renders @Browser tab attachments with tab context", () => {
    render(
      <UserMessage
        message={message("Use @Browser:github.com", {
          context_attachments: [
            {
              type: "browser_tab",
              label: "@Browser",
              display_path: "GitHub - PersonAgent",
              page_id: "page_github",
              url: "https://github.com/personagent/personagent",
              active: true,
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("@Browser")).toBeInTheDocument();
    expect(screen.getByText("GitHub - PersonAgent")).toBeInTheDocument();
    expect(screen.getByText("active tab")).toBeInTheDocument();
  });

  it("highlights annotation messages with file and line references", () => {
    render(
      <UserMessage
        message={message(
          [
            "@Annotation#2",
            "File: src/app.ts",
            "Path: /workspace/src/app.ts",
            "Lines: 65-93",
            "",
            "Annotation:",
            "Change the parser behavior.",
            "",
            "Selected lines:",
            "```typescript",
            "65: const parser = createParser();",
            "```",
            "",
            "Request:",
            "Apply this together with the surrounding parser cleanup.",
          ].join("\n"),
        )}
      />,
    );

    expect(screen.getByText("@Annotation#2")).toBeInTheDocument();
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("L65-93")).toBeInTheDocument();
    expect(screen.getByText("Apply this together with the surrounding parser cleanup.")).toBeInTheDocument();
  });

  it("uses the annotation text as the visible request when the composer text is empty", () => {
    render(
      <UserMessage
        message={message(
          [
            "@Annotation#1",
            "File: README.md",
            "Path: /workspace/README.md",
            "Lines: 2-4",
            "",
            "Annotation:",
            "Rewrite this section.",
            "",
            "Selected lines:",
            "```markdown",
            "2: old",
            "```",
            "",
            "Request:",
            "",
          ].join("\n"),
        )}
      />,
    );

    expect(screen.getByText("@Annotation#1")).toBeInTheDocument();
    expect(screen.getByText("Rewrite this section.")).toBeInTheDocument();
  });

  it("renders normal user messages as markdown in the chat feed", () => {
    render(
      <UserMessage
        message={message("## Plan\n\n- **Update** the backend.\n- Add tests.\n")}
      />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "Plan" })).toBeInTheDocument();
    expect(screen.getByText("Update", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Add tests.")).toBeInTheDocument();
  });

  it("keeps long user messages inside a scrollable card", () => {
    render(<UserMessage message={message(["# Plan", "", ...Array.from({ length: 24 }, (_, index) => `- Step ${index + 1}`)].join("\n"))} />);

    const card = screen.getByTestId("user-message-card");
    expect(card).toHaveClass("max-h-[min(58vh,520px)]");
    expect(card).toHaveClass("overflow-y-auto");
    expect(card).toHaveClass("overscroll-contain");
  });

  it("opens the rewind editor and resends edited text through the store action", () => {
    const rewindUserMessage = vi.fn();
    useChatStore.setState({ rewindUserMessage });
    render(
      <UserMessage
        message={message("Original request", {
          context_attachments: [
            {
              type: "file",
              label: "@File",
              display_path: "src/app.ts",
            },
          ],
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /rewind message/i }));

    const editor = screen.getByLabelText("Rewind message content");
    expect(editor).toHaveValue("Original request");
    expect(screen.getAllByText("@File").length).toBeGreaterThan(0);
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();

    fireEvent.change(editor, { target: { value: "Edited request" } });
    fireEvent.click(screen.getByRole("button", { name: /resend/i }));

    expect(rewindUserMessage).toHaveBeenCalledWith("message-1", "Edited request");
  });
});

function message(content: string, metadata?: Record<string, unknown>): ChatMessageUi {
  return {
    id: "message-1",
    role: "user",
    label: "User",
    content,
    reasoning: "",
    reasoningBlocks: [],
    toolBlocks: [],
    teamEvents: [],
    parts: [],
    isStreaming: false,
    isReasoningStreaming: false,
    metadata,
  };
}
