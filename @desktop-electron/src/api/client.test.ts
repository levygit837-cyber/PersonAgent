import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

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
