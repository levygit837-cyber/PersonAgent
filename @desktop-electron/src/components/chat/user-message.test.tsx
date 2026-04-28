import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatMessageUi } from "../../types/chat";
import { UserMessage } from "./user-message";

describe("UserMessage", () => {
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
