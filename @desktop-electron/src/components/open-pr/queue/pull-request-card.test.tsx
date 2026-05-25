import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PullRequestCard } from "./pull-request-card";
import type { PullRequestSummary } from "../../../api/client";

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

describe("PullRequestCard", () => {
  it("renders PR number, title and description", () => {
    render(<PullRequestCard pullRequest={makePr()} active={false} onClick={vi.fn()} />);

    expect(screen.getByText("#42")).toBeInTheDocument();
    expect(screen.getByText("Fix the thing")).toBeInTheDocument();
    expect(screen.getByText("A helpful description")).toBeInTheDocument();
  });

  it("renders author, updated time and file count", () => {
    render(<PullRequestCard pullRequest={makePr()} active={false} onClick={vi.fn()} />);

    expect(screen.getByText("dev")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
    expect(screen.getByText("1 files")).toBeInTheDocument();
  });

  it("renders addition and deletion totals", () => {
    render(<PullRequestCard pullRequest={makePr()} active={false} onClick={vi.fn()} />);

    expect(screen.getByText("+10")).toBeInTheDocument();
    expect(screen.getByText("-2")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<PullRequestCard pullRequest={makePr()} active={false} onClick={onClick} />);

    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("applies active styling when active", () => {
    const { container } = render(<PullRequestCard pullRequest={makePr()} active={true} onClick={vi.fn()} />);
    expect(container.firstChild).toHaveClass("border-primary/30");
  });

  it("applies inactive styling when not active", () => {
    const { container } = render(<PullRequestCard pullRequest={makePr()} active={false} onClick={vi.fn()} />);
    expect(container.firstChild).toHaveClass("border-transparent");
  });
});
