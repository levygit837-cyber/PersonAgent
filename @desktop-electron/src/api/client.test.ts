import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchBackendText } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  delete window.personAgent;
});

describe("Electron CSP", () => {
  it("allows Team Mode websocket connections to the local backend", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const csp = html.match(/Content-Security-Policy"[\s\S]*?content="([^"]+)"/)?.[1] ?? "";

    expect(csp).toContain("connect-src");
    expect(csp).toContain("ws://localhost:*");
    expect(csp).toContain("ws://127.0.0.1:*");
    expect(csp).toContain("wss://localhost:*");
    expect(csp).toContain("wss://127.0.0.1:*");
    expect(csp).toContain("frame-src");
    expect(csp).toContain("blob:");
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toContain("script-src 'self' 'unsafe-inline'");
    expect(csp).toContain("img-src 'self' data: blob: http: https:");
    expect(csp).toContain("style-src 'self' 'unsafe-inline' data: blob: http: https:");
  });
});

describe("fetchBackendText", () => {
  it("sends local auth headers when loading backend artifact text", async () => {
    window.personAgent = {
      auth: {
        getHeaders: vi.fn().mockResolvedValue({
          Authorization: "Bearer local-token",
          "X-PersonAgent-Client": "desktop-electron",
        }),
      },
    } as unknown as Window["personAgent"];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html><body>Mirror</body></html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );

    const html = await fetchBackendText("http://localhost:8000/artifacts/conversation/browser-documents/page.html");

    expect(html).toContain("Mirror");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/artifacts/conversation/browser-documents/page.html",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer local-token",
          "X-PersonAgent-Client": "desktop-electron",
        }),
      }),
    );
  });
});
