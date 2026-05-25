import { describe, expect, it } from "vitest";
import { clampValue, formatDateTime, prTotals, shortPath, statusText, uniqueBranches, uniqueProjects } from "./pr-utils";
import type { GitBranchInfo, PullRequestSummary, WorkspaceProject } from "../../../api/client";

describe("prTotals", () => {
  it("sums additions and deletions across files", () => {
    const pr = {
      files: [
        { additions: 10, deletions: 2 },
        { additions: 5, deletions: 8 },
      ],
    } as PullRequestSummary;

    expect(prTotals(pr)).toEqual({ additions: 15, deletions: 10 });
  });

  it("returns zero for empty files", () => {
    const pr = { files: [] } as unknown as PullRequestSummary;
    expect(prTotals(pr)).toEqual({ additions: 0, deletions: 0 });
  });
});

describe("shortPath", () => {
  it("returns last two segments of a path", () => {
    expect(shortPath("src/components/open-pr/workspace.tsx")).toBe("open-pr/workspace.tsx");
  });

  it("returns the whole path for short paths", () => {
    expect(shortPath("file.tsx")).toBe("file.tsx");
  });
});

describe("statusText", () => {
  it("returns correct labels for each status", () => {
    expect(statusText("approved")).toBe("Approved");
    expect(statusText("merged")).toBe("Merged");
    expect(statusText("refused")).toBe("Refused");
    expect(statusText("needs_review")).toBe("Needs review");
  });
});

describe("formatDateTime", () => {
  it("formats ISO dates", () => {
    const result = formatDateTime("2026-04-28T15:21:00Z");
    expect(result).toContain("28");
    expect(result).not.toBe("2026-04-28T15:21:00Z");
  });

  it("returns original value for invalid dates", () => {
    expect(formatDateTime("invalid")).toBe("invalid");
  });
});

describe("clampValue", () => {
  it("clamps to min when below", () => {
    expect(clampValue(5, 10, 20)).toBe(10);
  });

  it("clamps to max when above", () => {
    expect(clampValue(25, 10, 20)).toBe(20);
  });

  it("returns value when in range", () => {
    expect(clampValue(15, 10, 20)).toBe(15);
  });
});

describe("uniqueProjects", () => {
  it("deduplicates projects by path", () => {
    const projects = uniqueProjects(
      [{ projectPath: "/a", project: "A" }, { projectPath: "/b", project: "B" }] as PullRequestSummary[],
      "Fallback",
      "/fallback",
    );
    expect(projects).toHaveLength(3);
    expect(projects.map((p) => p.path)).toContain("/a");
    expect(projects.map((p) => p.path)).toContain("/b");
    expect(projects.map((p) => p.path)).toContain("/fallback");
  });

  it("prefers backend project names", () => {
    const projects = uniqueProjects(
      [{ projectPath: "/a", project: "From PR" }] as PullRequestSummary[],
      undefined,
      undefined,
      [],
      [{ path: "/a", name: "From Backend", is_repo: true }],
    );
    expect(projects.find((p) => p.path === "/a")?.name).toBe("From Backend");
  });
});

describe("uniqueBranches", () => {
  it("combines git branches and PR branches", () => {
    const branches = uniqueBranches(
      [{ projectPath: "/a", branch: "feature/x" }] as PullRequestSummary[],
      "/a",
      [{ name: "main", kind: "local", current: true }] as GitBranchInfo[],
    );
    expect(branches).toContain("main");
    expect(branches).toContain("feature/x");
  });

  it("excludes HEAD refs", () => {
    const branches = uniqueBranches(
      [] as PullRequestSummary[],
      "/a",
      [{ name: "origin/HEAD", kind: "remote", current: false }] as GitBranchInfo[],
    );
    expect(branches).not.toContain("origin/HEAD");
  });
});
