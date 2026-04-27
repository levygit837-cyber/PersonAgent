import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChatStore } from "../../stores/chat-store";
import type { ChatMessageUi } from "../../types/chat";
import { emptySessionUsage } from "../../types/chat";
import { MessageFeed } from "./message-feed";

describe("MessageFeed scroll behavior", () => {
  let rafCallbacks: Array<FrameRequestCallback | undefined>;

  beforeEach(() => {
    rafCallbacks = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      rafCallbacks.push(callback);
      return rafCallbacks.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation((handle) => {
      rafCallbacks[handle - 1] = undefined;
    });
    useChatStore.setState({
      messages: [],
      conversationId: "conversation-1",
      conversationTitle: "Scroll session",
      isStreaming: false,
      isFinalizing: false,
      error: undefined,
      pendingPlanApproval: undefined,
      pendingToolApproval: undefined,
      nextStepSuggestion: undefined,
      liveSessionUsage: emptySessionUsage(),
      liveSubAgentIds: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not force the feed to latest while the reader has scrolled up", () => {
    const userMessage = buildMessage({ id: "user-1", role: "user", label: "You", content: "Read this" });
    const agentMessage = buildMessage({
      id: "agent-1",
      role: "agent",
      label: "PersonAgent",
      content: "First token",
      isStreaming: true,
    });

    useChatStore.setState({ messages: [userMessage, agentMessage], isStreaming: true });
    render(<MessageFeed />);

    const scroller = screen.getByTestId("message-feed-scroller") as HTMLDivElement;
    const geometry = attachScrollGeometry(scroller, {
      clientHeight: 500,
      scrollHeight: 2000,
      scrollTop: 1500,
    });
    flushRaf();

    geometry.scrollTop = 700;
    fireEvent.scroll(scroller);

    act(() => {
      useChatStore.setState({
        messages: [userMessage, { ...agentMessage, content: "First token\nSecond token" }],
      });
    });
    flushRaf();

    expect(geometry.scrollTop).toBe(700);
  });

  it("resumes following once the reader scrolls back to recent messages", () => {
    const userMessage = buildMessage({ id: "user-1", role: "user", label: "You", content: "Follow this" });
    const agentMessage = buildMessage({
      id: "agent-1",
      role: "agent",
      label: "PersonAgent",
      content: "First token",
      isStreaming: true,
    });

    useChatStore.setState({ messages: [userMessage, agentMessage], isStreaming: true });
    render(<MessageFeed />);

    const scroller = screen.getByTestId("message-feed-scroller") as HTMLDivElement;
    const geometry = attachScrollGeometry(scroller, {
      clientHeight: 500,
      scrollHeight: 2000,
      scrollTop: 1500,
    });
    flushRaf();

    geometry.scrollTop = 700;
    fireEvent.scroll(scroller);
    geometry.scrollTop = 1390;
    fireEvent.scroll(scroller);

    act(() => {
      useChatStore.setState({
        messages: [userMessage, { ...agentMessage, content: "First token\nSecond token" }],
      });
    });
    flushRaf();

    expect(geometry.scrollTop).toBe(2000);
  });

  function flushRaf() {
    const pending = rafCallbacks;
    rafCallbacks = [];
    act(() => {
      pending.forEach((callback) => callback?.(performance.now()));
    });
  }
});

function attachScrollGeometry(
  element: HTMLDivElement,
  geometry: { clientHeight: number; scrollHeight: number; scrollTop: number },
) {
  Object.defineProperty(element, "clientHeight", {
    configurable: true,
    get: () => geometry.clientHeight,
  });
  Object.defineProperty(element, "scrollHeight", {
    configurable: true,
    get: () => geometry.scrollHeight,
  });
  Object.defineProperty(element, "scrollTop", {
    configurable: true,
    get: () => geometry.scrollTop,
    set: (value) => {
      geometry.scrollTop = Number(value);
    },
  });
  return geometry;
}

function buildMessage(overrides: Partial<ChatMessageUi>): ChatMessageUi {
  return {
    id: "message",
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
