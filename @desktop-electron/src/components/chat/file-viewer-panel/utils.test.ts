import { describe, expect, it } from "vitest";
import {
  compactWorkspacePath,
  defaultViewMode,
  filterRecord,
  formatLineRange,
  isHtmlFile,
  isMarkdownFile,
  lineInRange,
  normalizeLineRange,
  rangesOverlap,
  selectedLinesExcerpt,
  splitLines,
} from "./utils";

describe("isHtmlFile", () => {
  it("returns true for .html and .htm files", () => {
    expect(isHtmlFile("index.html")).toBe(true);
    expect(isHtmlFile("page.htm")).toBe(true);
    expect(isHtmlFile("styles.css")).toBe(false);
  });
});

describe("isMarkdownFile", () => {
  it("returns true for .md, .mdx, and readme files", () => {
    expect(isMarkdownFile("README.md")).toBe(true);
    expect(isMarkdownFile("notes.mdx")).toBe(true);
    expect(isMarkdownFile("readme")).toBe(true);
    expect(isMarkdownFile("script.js")).toBe(false);
  });
});

describe("defaultViewMode", () => {
  it("returns html for HTML files", () => {
    expect(defaultViewMode("index.html")).toBe("html");
  });

  it("returns code for other files", () => {
    expect(defaultViewMode("script.js")).toBe("code");
    expect(defaultViewMode("README.md")).toBe("code");
  });
});

describe("splitLines", () => {
  it("splits content by newlines", () => {
    expect(splitLines("a\nb\nc")).toEqual(["a", "b", "c"]);
  });

  it("handles empty content", () => {
    expect(splitLines("")).toEqual([""]);
  });

  it("normalizes CRLF to LF", () => {
    expect(splitLines("a\r\nb")).toEqual(["a", "b"]);
  });
});

describe("normalizeLineRange", () => {
  it("orders start and end correctly", () => {
    expect(normalizeLineRange(5, 2)).toEqual({ start: 2, end: 5 });
    expect(normalizeLineRange(2, 5)).toEqual({ start: 2, end: 5 });
  });
});

describe("lineInRange", () => {
  it("checks if a line is within a range", () => {
    expect(lineInRange(3, 1, 5)).toBe(true);
    expect(lineInRange(0, 1, 5)).toBe(false);
    expect(lineInRange(6, 1, 5)).toBe(false);
  });
});

describe("rangesOverlap", () => {
  it("detects overlapping ranges", () => {
    expect(rangesOverlap({ start: 1, end: 3 }, { start: 2, end: 4 })).toBe(true);
    expect(rangesOverlap({ start: 1, end: 2 }, { start: 3, end: 4 })).toBe(false);
    expect(rangesOverlap({ start: 1, end: 5 }, { start: 2, end: 3 })).toBe(true);
  });
});

describe("formatLineRange", () => {
  it("formats single line as number", () => {
    expect(formatLineRange(5, 5)).toBe("5");
  });

  it("formats range with dash", () => {
    expect(formatLineRange(2, 5)).toBe("2-5");
  });
});

describe("selectedLinesExcerpt", () => {
  it("extracts lines with line numbers", () => {
    const content = "one\ntwo\nthree\nfour\nfive";
    expect(selectedLinesExcerpt(content, 2, 4)).toBe("2: two\n3: three\n4: four");
  });
});

describe("compactWorkspacePath", () => {
  it("compacts path relative to workspace root", () => {
    expect(compactWorkspacePath("/workspaces/Eval/src/main.ts", "/workspaces/Eval")).toBe("src/main.ts");
    expect(compactWorkspacePath("/workspaces/Eval", "/workspaces/Eval")).toBe(".");
  });

  it("returns original path when no workspace root", () => {
    expect(compactWorkspacePath("/some/path", undefined)).toBe("/some/path");
  });
});

describe("filterRecord", () => {
  it("keeps only allowed keys", () => {
    const result = filterRecord({ a: 1, b: 2, c: 3 }, new Set(["a", "c"]));
    expect(result).toEqual({ a: 1, c: 3 });
  });
});
