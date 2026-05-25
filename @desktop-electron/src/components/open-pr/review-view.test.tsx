import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PullRequestReviewView } from "./review-view";
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
    labels: [],
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

describe("PullRequestReviewView", () => {
  it("renders PR title and file count", () => {
    render(
      <PullRequestReviewView
        pullRequest={makePr()}
        totals={{ additions: 10, deletions: 2 }}
        activeFileId="f1"
        openFiles={[]}
        onBack={vi.fn()}
        onSelectFile={vi.fn()}
        onAddFile={vi.fn()}
        onFocusFile={vi.fn()}
        onCloseFile={vi.fn()}
      />,
    );

    expect(screen.getByText("Fix the thing")).toBeInTheDocument();
    expect(screen.getByText("Files changed")).toBeInTheDocument();
  });

  it("renders diff dropzone", () => {
    render(
      <PullRequestReviewView
        pullRequest={makePr()}
        totals={{ additions: 10, deletions: 2 }}
        activeFileId="f1"
        openFiles={[]}
        onBack={vi.fn()}
        onSelectFile={vi.fn()}
        onAddFile={vi.fn()}
        onFocusFile={vi.fn()}
        onCloseFile={vi.fn()}
      />,
    );

    expect(screen.getByTestId("pr-diff-dropzone")).toBeInTheDocument();
  });
});
