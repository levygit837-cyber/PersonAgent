import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PullRequestDetailPanel, DetailCard, MetricTile, RiskPill } from "./detail-panel";
import type { PullRequestSummary } from "../../api/client";

function makePr(overrides?: Partial<PullRequestSummary>): PullRequestSummary {
  return {
    id: "pr-1",
    project: "Test",
    projectPath: "/test",
    number: 42,
    title: "Fix the thing",
    author: "dev",
    branch: "fix/thing",
    baseBranch: "main",
    updated: "2h ago",
    updatedAt: "2026-04-28T15:20:00Z",
    url: "https://github.example/pr/42",
    status: "needs_review",
    statusLabel: "Needs review",
    risk: "Low",
    checkSummary: "5 passing",
    description: "A helpful description",
    labels: ["backend"],
    commentsCount: 0,
    comments: [],
    files: [{ id: "f1", path: "src/main.ts", changeType: "modified", additions: 10, deletions: 2, summary: "", lines: [] }],
    isMine: false,
    isFlagged: false,
    reviewDecision: "REVIEW_REQUIRED",
    mergeState: "CLEAN",
    ...overrides,
  };
}

describe("PullRequestDetailPanel", () => {
  it("renders PR title and description", () => {
    render(<PullRequestDetailPanel pullRequest={makePr()} totals={{ additions: 10, deletions: 2 }} open={true} onStartReview={vi.fn()} onCreateComment={vi.fn()} creatingComment={false} />);
    expect(screen.getByText("Fix the thing")).toBeInTheDocument();
    expect(screen.getByText("A helpful description")).toBeInTheDocument();
  });

  it("has pr-detail-panel testid", () => {
    render(<PullRequestDetailPanel pullRequest={makePr()} totals={{ additions: 0, deletions: 0 }} open={true} onStartReview={vi.fn()} onCreateComment={vi.fn()} creatingComment={false} />);
    expect(screen.getByTestId("pr-detail-panel")).toHaveAttribute("data-open", "true");
  });
});

describe("DetailCard", () => {
  it("renders title and children", () => {
    render(<DetailCard icon={<span data-testid="icon" />} title="PR context">Content</DetailCard>);
    expect(screen.getByText("PR context")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
  });
});

describe("MetricTile", () => {
  it("renders label and value", () => {
    render(<MetricTile label="Files" value={5} />);
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });
});

describe("RiskPill", () => {
  it("renders risk text", () => {
    render(<RiskPill risk="High" />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
  });
});
