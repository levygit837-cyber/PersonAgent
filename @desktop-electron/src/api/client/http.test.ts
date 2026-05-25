import { afterEach, describe, expect, it, vi } from "vitest";

import {
  personAgentAuthHeaders,
  resolveBackendUrl,
  requestJson,
  fetchBackendText,
  webSocketBaseUrl,
} from "./http";
import { PersonAgentApiError } from "../errors";

afterEach(() => {
  vi.restoreAllMocks();
  delete window.personAgent;
  delete (import.meta.env as Record<string, unknown>).VITE_PERSONAGENT_LOCAL_AUTH_TOKEN;
});

describe("personAgentAuthHeaders", () => {
  it("returns Electron auth headers when available", async () => {
    window.personAgent = {
      auth: {
        getHeaders: vi.fn().mockResolvedValue({
          Authorization: "Bearer electron-token",
          "X-Custom": "value",
        }),
      },
    } as unknown as Window["personAgent"];

    const headers = await personAgentAuthHeaders();

    expect(headers).toEqual({
      Authorization: "Bearer electron-token",
      "X-Custom": "value",
    });
  });

  it("falls back to VITE_PERSONAGENT_LOCAL_AUTH_TOKEN when Electron auth lacks Authorization", async () => {
    window.personAgent = {
      auth: {
        getHeaders: vi.fn().mockResolvedValue({}),
      },
    } as unknown as Window["personAgent"];
    (import.meta.env as Record<string, unknown>).VITE_PERSONAGENT_LOCAL_AUTH_TOKEN = " local-token ";

    const headers = await personAgentAuthHeaders();

    expect(headers).toEqual({
      Authorization: "Bearer local-token",
      "X-PersonAgent-Client": "desktop-electron",
    });
  });

  it("returns empty object when no auth source is available", async () => {
    const headers = await personAgentAuthHeaders();
    expect(headers).toEqual({});
  });

  it("skips Electron path when the API is missing", async () => {
    (import.meta.env as Record<string, unknown>).VITE_PERSONAGENT_LOCAL_AUTH_TOKEN = "token";

    const headers = await personAgentAuthHeaders();

    expect(headers.Authorization).toBe("Bearer token");
  });
});

describe("resolveBackendUrl", () => {
  it("returns the current URL when it responds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("ok", { status: 200 }),
    );

    const url = await resolveBackendUrl("http://localhost:9000");

    expect(url).toBe("http://localhost:9000");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:9000/health",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("falls back to fallback base URLs when current fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("Connection refused"))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));

    const url = await resolveBackendUrl("http://localhost:9000");

    expect(url).toBe("http://localhost:8000");
  });

  it("throws when no backend answers", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Connection refused"));

    await expect(resolveBackendUrl()).rejects.toThrow("No PersonAgent backend answered on the configured ports.");
  });
});

describe("requestJson", () => {
  it("returns parsed JSON on success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), { status: 200 }),
    );

    const result = await requestJson<{ id: number }>("http://localhost:8000", "/test");

    expect(result).toEqual({ id: 1 });
  });

  it("sends auth headers with every request", async () => {
    window.personAgent = {
      auth: {
        getHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer t" }),
      },
    } as unknown as Window["personAgent"];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await requestJson("http://localhost:8000", "/test");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/test",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer t" }),
      }),
    );
  });

  it("sends Content-Type for POST with JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await requestJson("http://localhost:8000", "/test", {
      method: "POST",
      body: JSON.stringify({ foo: "bar" }),
    });

    expect(vi.mocked(fetch).mock.calls[0]?.[1]?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("does not send Content-Type for GET requests", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await requestJson("http://localhost:8000", "/test");

    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("does not send Content-Type for FormData body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await requestJson("http://localhost:8000", "/test", {
      method: "POST",
      body: new FormData(),
    });

    const headers = vi.mocked(fetch).mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });

  it("throws PersonAgentApiError on non-ok response with JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ message: "Bad request" }), {
        status: 400,
        statusText: "Bad Request",
      }),
    );

    await expect(requestJson("http://localhost:8000", "/test")).rejects.toThrow(PersonAgentApiError);
  });

  it("throws PersonAgentApiError on non-ok response with non-JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Internal Server Error", {
        status: 500,
        statusText: "Internal Server Error",
      }),
    );

    await expect(requestJson("http://localhost:8000", "/test")).rejects.toThrow(PersonAgentApiError);
  });

  it("merges custom headers correctly", async () => {
    window.personAgent = {
      auth: {
        getHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer t" }),
      },
    } as unknown as Window["personAgent"];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await requestJson("http://localhost:8000", "/test", {
      headers: { "X-Custom": "value" },
    });

    expect(vi.mocked(fetch).mock.calls[0]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer t",
      "X-Custom": "value",
    });
  });
});

describe("fetchBackendText", () => {
  it("returns text on success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("hello", { status: 200 }),
    );

    const text = await fetchBackendText("http://localhost:8000/text");

    expect(text).toBe("hello");
  });

  it("throws PersonAgentApiError on non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not found", { status: 404, statusText: "Not Found" }),
    );

    await expect(fetchBackendText("http://localhost:8000/text")).rejects.toThrow(PersonAgentApiError);
  });
});

describe("webSocketBaseUrl", () => {
  it("converts http to ws", () => {
    expect(webSocketBaseUrl("http://localhost:8000")).toBe("ws://localhost:8000");
  });

  it("converts https to wss", () => {
    expect(webSocketBaseUrl("https://localhost:8000")).toBe("wss://localhost:8000");
  });

  it("strips trailing slash", () => {
    expect(webSocketBaseUrl("http://localhost:8000/")).toBe("ws://localhost:8000");
  });
});
