import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReviewAgentWindow } from "./review-agent-window";
import type { PullRequestSummary } from "../../api/client";

describe("ReviewAgentWindow", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 1280 });
    Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: 800 });
  });

  it("renders review agent window", () => {
    render(<ReviewAgentWindow pullRequest={{ number: 42, title: "Test PR" } as PullRequestSummary} />);
    expect(screen.getByTestId("review-agent-window")).toBeInTheDocument();
    expect(screen.getByText("Review Agent")).toBeInTheDocument();
  });

  it("expands when toggle is clicked", () => {
    render(<ReviewAgentWindow pullRequest={{ number: 42, title: "Test PR" } as PullRequestSummary} />);

    fireEvent.click(screen.getByRole("button", { name: /Expand Review Agent/i }));

    expect(screen.getByPlaceholderText("Ask the PR agent...")).toBeInTheDocument();
  });

  it("shows suggestion chips when expanded", () => {
    render(<ReviewAgentWindow pullRequest={{ number: 42, title: "Test PR" } as PullRequestSummary} />);

    fireEvent.click(screen.getByRole("button", { name: /Expand Review Agent/i }));

    expect(screen.getByRole("button", { name: "Selected file" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regressions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find usages" })).toBeInTheDocument();
  });
});
