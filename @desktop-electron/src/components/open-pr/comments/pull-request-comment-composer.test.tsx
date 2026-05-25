import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PullRequestCommentComposer } from "./pull-request-comment-composer";
import type { PullRequestSummary } from "../../../api/client";

describe("PullRequestCommentComposer", () => {
  it("renders comment option buttons", () => {
    render(<PullRequestCommentComposer pullRequest={{ number: 42 } as PullRequestSummary} onCreateComment={vi.fn()} disabled={false} />);

    expect(screen.getByRole("button", { name: "Human analysis" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI analysis" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Needs review" })).toBeInTheDocument();
  });

  it("submits comment with selected kind", async () => {
    const onCreateComment = vi.fn().mockResolvedValue({ success: true });
    render(<PullRequestCommentComposer pullRequest={{ number: 42 } as PullRequestSummary} onCreateComment={onCreateComment} disabled={false} />);

    fireEvent.click(screen.getByRole("button", { name: "AI analysis" }));
    fireEvent.change(screen.getByPlaceholderText("Write a PR comment..."), {
      target: { value: "The DTO boundary needs one more regression test." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send comment/i }));

    await waitFor(() => {
      expect(onCreateComment).toHaveBeenCalledWith({
        number: 42,
        body: "The DTO boundary needs one more regression test.",
        kind: "ai_review",
        status: null,
      });
    });
  });

  it("disables send when body is empty", () => {
    render(<PullRequestCommentComposer pullRequest={{ number: 1 } as PullRequestSummary} onCreateComment={vi.fn()} disabled={false} />);

    expect(screen.getByRole("button", { name: /Send comment/i })).toBeDisabled();
  });

  it("shows feedback after successful submit", async () => {
    const onCreateComment = vi.fn().mockResolvedValue({ success: true });
    render(<PullRequestCommentComposer pullRequest={{ number: 1 } as PullRequestSummary} onCreateComment={onCreateComment} disabled={false} />);

    fireEvent.change(screen.getByPlaceholderText("Write a PR comment..."), {
      target: { value: "LGTM" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send comment/i }));

    await waitFor(() => {
      expect(screen.getByText("Comment sent")).toBeInTheDocument();
    });
  });
});
