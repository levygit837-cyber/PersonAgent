import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createActionApproval,
  listModels,
  getCodexAuthStatus,
  logoutCodex,
  listChatCommands,
  streamChatCompletion,
  approvePlan,
  continuePlan,
  cancelPlan,
  approveTool,
  streamApproveTool,
  rejectTool,
  listTeams,
  streamTeamChat,
} from "./chat-api";
import { PersonAgentApiError } from "../errors";

vi.mock("../sse", () => ({
  readSseStream: vi.fn(),
}));

afterEach(() => {
  vi.restoreAllMocks();
  delete window.personAgent;
});

describe("createActionApproval", () => {
  it("delegates to the desktop security bridge", async () => {
    const mock = vi.fn().mockResolvedValue({
      approval_id: "a1",
      action_kind: "workspace.git_commit",
      args_hash: "h1",
      expires_at: 123,
      approval_signature: "sig",
    });
    window.personAgent = { security: { createActionApproval: mock } } as unknown as Window["personAgent"];

    const result = await createActionApproval("http://localhost:8000", "workspace.git_commit", { foo: "bar" });

    expect(result.approval_signature).toBe("sig");
    expect(mock).toHaveBeenCalledWith("workspace.git_commit", { foo: "bar" });
  });

  it("throws when the desktop bridge is unavailable", async () => {
    await expect(createActionApproval("http://localhost:8000", "kind", {})).rejects.toThrow(PersonAgentApiError);
  });
});

describe("listModels", () => {
  it("returns normalized models from a flat array", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ id: "m1", name: "Model 1" }]), { status: 200 }),
    );

    const models = await listModels("http://localhost:8000", "openai");

    expect(models).toHaveLength(1);
    expect(models[0]).toMatchObject({ id: "m1", name: "Model 1", provider: "openai" });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/chat/models?"),
      expect.anything(),
    );
  });

  it("unwraps nested data field when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: [{ id: "m2" }] }), { status: 200 }),
    );

    const models = await listModels("http://localhost:8000", "anthropic");

    expect(models[0]?.id).toBe("m2");
  });

  it("filters by capability when provided", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );

    await listModels("http://localhost:8000", "openai", "vision");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("capability=vision"),
      expect.anything(),
    );
  });
});

describe("getCodexAuthStatus", () => {
  it("fetches codex auth status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), { status: 200 }),
    );

    const status = await getCodexAuthStatus("http://localhost:8000");

    expect(status).toEqual({ authenticated: true });
  });
});

describe("logoutCodex", () => {
  it("posts to the logout endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: false }), { status: 200 }),
    );

    await logoutCodex("http://localhost:8000");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/chat/auth/codex/logout"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("listChatCommands", () => {
  it("fetches chat commands without workspace", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([{ name: "/plan" }]), { status: 200 }),
    );

    const cmds = await listChatCommands("http://localhost:8000");

    expect(cmds).toEqual([{ name: "/plan" }]);
  });

  it("appends workspace_root when provided", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );

    await listChatCommands("http://localhost:8000", "/workspace");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("workspace_root=%2Fworkspace"),
      expect.anything(),
    );
  });
});

describe("streamChatCompletion", () => {
  it("posts payload to the streaming endpoint", async () => {
    const { readSseStream } = await import("../sse");
    vi.mocked(readSseStream).mockImplementation(async function* () { yield { content: "hi" }; });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("stream", { status: 200 }),
    );

    const gen = streamChatCompletion("http://localhost:8000", { messages: [] } as unknown as import("../../types/chat").ChatRequestPayload);
    const result = await gen.next();

    expect(result.value).toEqual({ content: "hi" });
  });
});

describe("plan approvals", () => {
  it("approvePlan sends approval payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ decision: "approved" }), { status: 200 }),
    );

    const result = await approvePlan("http://localhost:8000", { conversationId: "c1", approvalId: "a1", feedback: "ok" });

    expect(result).toEqual({ decision: "approved" });
  });

  it("continuePlan sends continue payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ decision: "continued" }), { status: 200 }),
    );

    const result = await continuePlan("http://localhost:8000", { conversationId: "c1", approvalId: "a1" });

    expect(result).toEqual({ decision: "continued" });
  });

  it("cancelPlan sends cancel payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ decision: "cancelled" }), { status: 200 }),
    );

    const result = await cancelPlan("http://localhost:8000", { conversationId: "c1", approvalId: "a1" });

    expect(result).toEqual({ decision: "cancelled" });
  });
});

describe("tool approvals", () => {
  it("approveTool sends args_hash when provided", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    await approveTool("http://localhost:8000", { conversationId: "c1", approvalId: "a1", argsHash: "h1" });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body ?? "{}"));
    expect(body.args_hash).toBe("h1");
  });

  it("rejectTool sends rejection payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ rejected: true }), { status: 200 }),
    );

    const result = await rejectTool("http://localhost:8000", { conversationId: "c1", approvalId: "a1" });

    expect(result).toEqual({ rejected: true });
  });

  it("streamApproveTool yields SSE chunks", async () => {
    const { readSseStream } = await import("../sse");
    vi.mocked(readSseStream).mockImplementation(async function* () { yield { delta: "x" }; });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("stream", { status: 200 }),
    );

    const gen = streamApproveTool("http://localhost:8000", { conversationId: "c1", approvalId: "a1" });
    const result = await gen.next();

    expect(result.value).toEqual({ delta: "x" });
  });
});

describe("listTeams", () => {
  it("returns teams from nested data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: [{ name: "Team A" }] }), { status: 200 }),
    );

    const teams = await listTeams("http://localhost:8000");

    expect(teams).toEqual([{ name: "Team A" }]);
  });

  it("returns empty array when data is missing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    const teams = await listTeams("http://localhost:8000");

    expect(teams).toEqual([]);
  });
});

describe("streamTeamChat", () => {
  it("yields parsed events from the team websocket", async () => {
    const mockSocket = {
      send: vi.fn(),
      close: vi.fn(),
      readyState: WebSocket.CONNECTING,
      onopen: null as ((this: WebSocket, ev: Event) => void) | null,
      onmessage: null as ((this: WebSocket, ev: MessageEvent) => void) | null,
      onerror: null as ((this: WebSocket, ev: Event) => void) | null,
      onclose: null as ((this: WebSocket, ev: CloseEvent) => void) | null,
      OPEN: 1,
      CONNECTING: 0,
      CLOSING: 2,
      CLOSED: 3,
    };
    const OriginalWebSocket = globalThis.WebSocket;
    vi.spyOn(globalThis, "WebSocket").mockImplementation(function () {
      return mockSocket as unknown as WebSocket;
    });

    const payload = { type: "team.run.start", team_id: "t1" } as unknown as ReturnType<typeof import("../../types/chat").buildTeamRunStart>;
    const gen = streamTeamChat("http://localhost:8000", payload);
    const nextPromise = gen.next();

    // Simulate WebSocket opening and receiving a message
    mockSocket.readyState = WebSocket.OPEN;
    mockSocket.onopen?.(new Event("open"));
    mockSocket.onmessage?.({ data: JSON.stringify({ event: "chunk", content: "hello" }) } as MessageEvent);

    const result = await nextPromise;
    expect(result.value).toEqual({ event: "chunk", content: "hello" });

    await gen.return?.(undefined);
    globalThis.WebSocket = OriginalWebSocket;
  });
});
