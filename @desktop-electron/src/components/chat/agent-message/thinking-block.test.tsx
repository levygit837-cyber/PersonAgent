import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AgentMessageThinking } from "./thinking-block";
import type { ChatMessageUi } from "../../../types/chat";

const setReasoningBlockExpandedMock = vi.fn();

vi.mock("../../../stores/chat-store", () => ({
  useChatStore: (selector: (state: unknown) => unknown) =>
    selector({ setReasoningBlockExpanded: setReasoningBlockExpandedMock }),
}));

function baseMessage(): ChatMessageUi {
  return {
    id: "msg-1",
    role: "agent",
    label: "PersonAgent",
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

describe("AgentMessageThinking", () => {
  beforeEach(() => {
    setReasoningBlockExpandedMock.mockClear();
  });

  it("renders nothing when there is no reasoning content", () => {
    render(
      <AgentMessageThinking
        message={baseMessage()}
        hasVisibleAnswerContent={true}
      />,
    );

    expect(document.body.textContent).toBe("");
  });

  it("renders legacy thinking when parts is empty and reasoning exists", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      reasoning: "Legacy thought process",
      isReasoningStreaming: true,
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={true}
      />,
    );

    expect(screen.getByText("Legacy thought process")).toBeInTheDocument();
  });

  it("renders orphan reasoning blocks not referenced by parts", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      parts: [{ kind: "content", id: "p1", content: "Answer" }],
      reasoningBlocks: [
        {
          id: "rb-1",
          content: "Orphan reasoning",
          isStreaming: false,
          userExpanded: true,
        },
      ],
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={false}
      />,
    );

    expect(screen.getByText("Orphan reasoning")).toBeInTheDocument();
  });

  it("does not render reasoning blocks already referenced by parts", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      parts: [
        {
          kind: "reasoning",
          id: "p1",
          reasoningBlockId: "rb-1",
        },
      ],
      reasoningBlocks: [
        {
          id: "rb-1",
          content: "Already shown",
          isStreaming: false,
          userExpanded: false,
        },
      ],
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={true}
      />,
    );

    expect(screen.queryByText("Already shown")).not.toBeInTheDocument();
  });

  it("renders orphan reasoning fallback when no blocks and reasoning string exists", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      parts: [{ kind: "content", id: "p1", content: "Answer" }],
      reasoning: "Fallback reasoning string",
      isReasoningStreaming: false,
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={false}
      />,
    );

    expect(
      screen.getByText("Fallback reasoning string"),
    ).toBeInTheDocument();
  });

  it("does not render fallback when parts already contain a reasoning part", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      parts: [
        { kind: "reasoning", id: "p1", reasoningBlockId: "rb-1" },
        { kind: "content", id: "p2", content: "Answer" },
      ],
      reasoning: "Should not appear",
      reasoningBlocks: [
        {
          id: "rb-1",
          content: "Block content",
          isStreaming: false,
          userExpanded: false,
        },
      ],
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={true}
      />,
    );

    expect(screen.queryByText("Should not appear")).not.toBeInTheDocument();
  });

  it("calls setReasoningBlockExpanded when orphan block toggle is clicked", () => {
    const message: ChatMessageUi = {
      ...baseMessage(),
      parts: [{ kind: "content", id: "p1", content: "Answer" }],
      reasoningBlocks: [
        {
          id: "rb-1",
          content: "Toggle me",
          isStreaming: false,
          userExpanded: false,
        },
      ],
    };

    render(
      <AgentMessageThinking
        message={message}
        hasVisibleAnswerContent={true}
      />,
    );

    const toggle = screen.getByRole("button");
    fireEvent.click(toggle);

    expect(setReasoningBlockExpandedMock).toHaveBeenCalledTimes(1);
    expect(setReasoningBlockExpandedMock).toHaveBeenCalledWith(
      "msg-1",
      "rb-1",
      true,
    );
  });
});
