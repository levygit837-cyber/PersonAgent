import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusPill } from "./status-pill";

describe("StatusPill", () => {
  it("renders children text", () => {
    render(<StatusPill status="needs_review">Needs review</StatusPill>);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });

  it("applies warning styles for needs_review", () => {
    const { container } = render(<StatusPill status="needs_review">Needs review</StatusPill>);
    expect(container.firstChild).toHaveClass("border-warning/30", "bg-warning/10", "text-warning");
  });

  it("applies success styles for approved", () => {
    const { container } = render(<StatusPill status="approved">Approved</StatusPill>);
    expect(container.firstChild).toHaveClass("border-success/30", "bg-success/10", "text-success");
  });

  it("applies success styles for merged", () => {
    const { container } = render(<StatusPill status="merged">Merged</StatusPill>);
    expect(container.firstChild).toHaveClass("border-success/30", "bg-success/10", "text-success");
  });

  it("applies destructive styles for refused", () => {
    const { container } = render(<StatusPill status="refused">Refused</StatusPill>);
    expect(container.firstChild).toHaveClass("border-destructive/30", "bg-destructive/10", "text-destructive");
  });
});
