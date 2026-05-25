import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PullRequestComments } from "./pull-request-comments";
import type { PullRequestComment } from "../../../api/client";

describe("PullRequestComments", () => {
  it("shows empty state when no comments", () => {
    render(<PullRequestComments comments={[]} />);
    expect(screen.getByText("No PR comments yet.")).toBeInTheDocument();
  });

  it("renders comments with author and body", () => {
    const comments: PullRequestComment[] = [
      { id: "c1", kind: "human_review", source: "human", author: "reviewer", body: "Please fix tests.", createdAt: "2026-04-28T15:21:00Z" },
      { id: "c2", kind: "ai_review", source: "ai", author: "personagent", body: "AI analysis complete.", createdAt: "2026-04-28T15:22:00Z" },
    ];

    render(<PullRequestComments comments={comments} />);

    expect(screen.getByText("reviewer")).toBeInTheDocument();
    expect(screen.getByText("Please fix tests.")).toBeInTheDocument();
    expect(screen.getByText("personagent")).toBeInTheDocument();
    expect(screen.getByText("AI analysis complete.")).toBeInTheDocument();
  });

  it("limits to 5 comments", () => {
    const comments: PullRequestComment[] = Array.from({ length: 7 }, (_, i) => ({
      id: `c${i}`,
      kind: "human_review",
      source: "human",
      author: `user${i}`,
      body: `comment ${i}`,
      createdAt: "2026-04-28T15:21:00Z",
    }));

    render(<PullRequestComments comments={comments} />);
    expect(screen.getByText("comment 0")).toBeInTheDocument();
    expect(screen.getByText("comment 4")).toBeInTheDocument();
    expect(screen.queryByText("comment 5")).not.toBeInTheDocument();
  });
});
