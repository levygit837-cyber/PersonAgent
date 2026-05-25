import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CommentKindPill } from "./comment-kind-pill";
import type { PullRequestComment } from "../../../api/client";

function makeComment(overrides?: Partial<PullRequestComment>): PullRequestComment {
  return {
    id: "c1",
    kind: "human_review",
    source: "human",
    author: "reviewer",
    body: "Looks good",
    createdAt: "2026-04-28T15:21:00Z",
    ...overrides,
  };
}

describe("CommentKindPill", () => {
  it("renders Human analysis for human_review", () => {
    render(<CommentKindPill comment={makeComment({ kind: "human_review" })} />);
    expect(screen.getByText("Human analysis")).toBeInTheDocument();
  });

  it("renders AI analysis for ai_review", () => {
    render(<CommentKindPill comment={makeComment({ kind: "ai_review" })} />);
    expect(screen.getByText("AI analysis")).toBeInTheDocument();
  });

  it("renders status label for status comments", () => {
    render(<CommentKindPill comment={makeComment({ kind: "status", status: "approved" })} />);
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });
});
