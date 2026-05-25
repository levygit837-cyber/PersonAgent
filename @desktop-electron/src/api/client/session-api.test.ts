import { afterEach, describe, expect, it, vi } from "vitest";

import {
  listConversations,
  getConversation,
  forkConversation,
  deleteConversation,
  getSessionPanel,
  getSessionProjectDetail,
  getSessionBrowserView,
  navigateSessionBrowser,
  moveSessionBrowserHistory,
  reloadSessionBrowser,
  clickSessionBrowser,
  keySessionBrowser,
  scrollSessionBrowser,
  actSessionBrowser,
  setSessionBrowserCooperation,
  ingestSessionBrowserEvents,
  connectSessionBrowserCooperation,
  createSessionBrowserAnnotation,
  deleteSessionBrowserAnnotation,
} from "./session-api";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetchJson(data: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(data), { status }),
  );
}

describe("listConversations", () => {
  it("fetches conversation summaries", async () => {
    mockFetchJson([{ id: "c1", title: "Chat" }]);

    const result = await listConversations("http://localhost:8000");

    expect(result).toHaveLength(1);
    expect(result[0]?.id).toBe("c1");
  });
});

describe("getConversation", () => {
  it("fetches a single conversation", async () => {
    mockFetchJson({ id: "c1", title: "Chat", messages: [] });

    const result = await getConversation("http://localhost:8000", "c1");

    expect(result.id).toBe("c1");
  });
});

describe("forkConversation", () => {
  it("posts fork with messages", async () => {
    mockFetchJson({ id: "c2", title: "Fork", messages: [] });

    const result = await forkConversation("http://localhost:8000", "c1", {
      title: "Fork",
      messages: [{ role: "user", content: "hello" }],
    });

    expect(result.id).toBe("c2");
  });
});

describe("deleteConversation", () => {
  it("deletes a conversation", async () => {
    mockFetchJson({ deleted: true });

    const result = await deleteConversation("http://localhost:8000", "c1");

    expect(result.deleted).toBe(true);
  });
});

describe("getSessionPanel", () => {
  it("fetches session panel snapshot", async () => {
    mockFetchJson({ conversation_id: "c1", title: "Panel", updated_at: "2024-01-01", changed_files: [], sources: [], usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 }, project: { id: "p1", name: "Project", files: [] } });

    const result = await getSessionPanel("http://localhost:8000", "c1");

    expect(result.conversation_id).toBe("c1");
  });

  it("appends workspace_root when provided", async () => {
    const fetchMock = mockFetchJson({ conversation_id: "c1", title: "Panel", updated_at: "2024-01-01", changed_files: [], sources: [], usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 }, project: { id: "p1", name: "Project", files: [] } });

    await getSessionPanel("http://localhost:8000", "c1", "/workspace");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("workspace_root=%2Fworkspace"),
      expect.anything(),
    );
  });
});

describe("getSessionProjectDetail", () => {
  it("fetches project detail", async () => {
    mockFetchJson({ id: "p1", name: "Project" });

    const result = await getSessionProjectDetail("http://localhost:8000", "c1", { type: "repo", id: "p1" });

    expect(result.id).toBe("p1");
  });
});

describe("getSessionBrowserView", () => {
  it("fetches browser view with viewport params", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await getSessionBrowserView("http://localhost:8000", "b1", { width: 1024, height: 768 });

    expect(result.browser_id).toBe("b1");
  });
});

describe("navigateSessionBrowser", () => {
  it("posts navigate with url", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await navigateSessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768, url: "http://example.com" });

    expect(result.url).toBe("http://example.com");
  });
});

describe("moveSessionBrowserHistory", () => {
  it("posts history movement", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await moveSessionBrowserHistory("http://localhost:8000", "b1", { width: 1024, height: 768, direction: -1 });

    expect(result.browser_id).toBe("b1");
  });
});

describe("reloadSessionBrowser", () => {
  it("posts reload", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await reloadSessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768 });

    expect(result.browser_id).toBe("b1");
  });
});

describe("clickSessionBrowser", () => {
  it("posts click coordinates", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await clickSessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768, x: 100, y: 200 });

    expect(result.browser_id).toBe("b1");
  });
});

describe("keySessionBrowser", () => {
  it("posts key input", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await keySessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768, key: "Enter" });

    expect(result.browser_id).toBe("b1");
  });
});

describe("scrollSessionBrowser", () => {
  it("posts scroll delta", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await scrollSessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768, delta_x: 0, delta_y: 100 });

    expect(result.browser_id).toBe("b1");
  });
});

describe("actSessionBrowser", () => {
  it("posts element action", async () => {
    mockFetchJson({ type: "browser_view", browser_id: "b1", url: "http://example.com", title: "Example", screenshot_method: "screenshot", viewport_width: 1024, viewport_height: 768, can_capture: true });

    const result = await actSessionBrowser("http://localhost:8000", "b1", { width: 1024, height: 768, node_id: "n1", action: "click" });

    expect(result.browser_id).toBe("b1");
  });
});

describe("setSessionBrowserCooperation", () => {
  it("posts cooperation settings", async () => {
    mockFetchJson({ cooperation: { enabled: true, mode: "agent_control" }, state_patch: {}, agent_context: {} });

    const result = await setSessionBrowserCooperation("http://localhost:8000", "c1", "b1", { enabled: true, mode: "agent_control" });

    expect(result.cooperation.enabled).toBe(true);
  });
});

describe("ingestSessionBrowserEvents", () => {
  it("posts event batch", async () => {
    mockFetchJson({ accepted_count: 2, dropped_count: 0, state_patch: {}, notifications: [] });

    const result = await ingestSessionBrowserEvents("http://localhost:8000", "c1", "b1", [
      { kind: "click", source: "user" },
    ]);

    expect(result.accepted_count).toBe(2);
  });
});

describe("connectSessionBrowserCooperation", () => {
  it("opens a websocket and yields events", async () => {
    const mockSocket: Record<string, unknown> = {
      send: vi.fn(),
      close: vi.fn(),
      readyState: WebSocket.CONNECTING,
      onopen: null,
      onmessage: null,
      onerror: null,
      onclose: null,
      OPEN: 1,
      CONNECTING: 0,
      CLOSING: 2,
      CLOSED: 3,
    };
    const OriginalWebSocket = globalThis.WebSocket;
    vi.spyOn(globalThis, "WebSocket").mockImplementation(function () {
      return mockSocket as unknown as WebSocket;
    });

    const onMessage = vi.fn();
    const socket = connectSessionBrowserCooperation("http://localhost:8000", "c1", "b1", { onMessage });

    mockSocket.readyState = WebSocket.OPEN;
    (mockSocket.onopen as (ev: Event) => void)?.(new Event("open"));
    (mockSocket.onmessage as (ev: MessageEvent) => void)?.({ data: JSON.stringify({ type: "snapshot", cooperation: { enabled: true } }) } as MessageEvent);

    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "snapshot" }));
    expect(socket).toBe(mockSocket);

    globalThis.WebSocket = OriginalWebSocket;
  });
});

describe("createSessionBrowserAnnotation", () => {
  it("posts annotation creation", async () => {
    mockFetchJson({ annotation: { id: "a1", browser_id: "b1", node_id: "n1", body: "note", created_at: "2024-01-01" }, annotations: [], timeline_events: [] });

    const result = await createSessionBrowserAnnotation("http://localhost:8000", "c1", "b1", { node_id: "n1", body: "note" });

    expect(result.annotation.body).toBe("note");
  });
});

describe("deleteSessionBrowserAnnotation", () => {
  it("deletes an annotation", async () => {
    mockFetchJson({ annotations: [], timeline_events: [] });

    const result = await deleteSessionBrowserAnnotation("http://localhost:8000", "c1", "b1", "a1");

    expect(result.annotations).toEqual([]);
  });
});
