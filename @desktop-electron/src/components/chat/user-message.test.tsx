import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatMessageUi } from "../../types/chat";
import { UserMessage } from "./user-message";

describe("UserMessage", () => {
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

function message(content: string): ChatMessageUi {
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
  };
}
