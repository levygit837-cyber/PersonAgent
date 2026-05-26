import { describe, expect, it } from "vitest";
import {
  escapeHtml,
  highlightContent,
  languageFromFilename,
  shouldSkipHighlight,
  splitHighlightedLines,
} from "./highlight-utils";

describe("escapeHtml", () => {
  it("escapes HTML special characters", () => {
    expect(escapeHtml("<div>Hello & goodbye</div>")).toBe("&lt;div&gt;Hello &amp; goodbye&lt;/div&gt;");
  });
});

describe("shouldSkipHighlight", () => {
  it("skips plaintext", () => {
    expect(shouldSkipHighlight("any content", "plaintext")).toBe(true);
  });

  it("skips very large content", () => {
    expect(shouldSkipHighlight("x".repeat(100_000), "javascript")).toBe(true);
  });

  it("highlights normal content", () => {
    expect(shouldSkipHighlight("const x = 1;", "javascript")).toBe(false);
  });
});

describe("highlightContent", () => {
  it("returns escaped HTML for plaintext", () => {
    expect(highlightContent("<test>", "plaintext")).toBe("&lt;test&gt;");
  });

  it("highlights known languages", () => {
    const result = highlightContent("const x = 1;", "javascript");
    expect(result).toContain("const");
    expect(result).not.toBe("const x = 1;");
  });
});

describe("splitHighlightedLines", () => {
  it("splits highlighted HTML by lines", () => {
    const html = "<span>line1</span>\n<span>line2</span>";
    const result = splitHighlightedLines(html);
    expect(result).toHaveLength(2);
    expect(result[0]).toContain("line1");
    expect(result[1]).toContain("line2");
  });

  it("handles unclosed spans across lines", () => {
    const html = '<span class="keyword">const\nx = 1;</span>';
    const result = splitHighlightedLines(html);
    expect(result).toHaveLength(2);
    expect(result[0]).toContain('<span class="keyword">');
    expect(result[1]).toContain("</span>");
  });
});

describe("languageFromFilename", () => {
  it("detects language from extension", () => {
    expect(languageFromFilename("script.js")).toBe("javascript");
    expect(languageFromFilename("style.css")).toBe("css");
    expect(languageFromFilename("app.tsx")).toBe("typescript");
  });

  it("detects language from known filenames", () => {
    expect(languageFromFilename("package.json")).toBe("json");
    expect(languageFromFilename("tsconfig.json")).toBe("json");
  });

  it("falls back to plaintext for unknown files", () => {
    expect(languageFromFilename("data.xyz")).toBe("plaintext");
  });
});
