import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AlertCircle } from "lucide-react";
import { QueueState } from "./queue-state";

describe("QueueState", () => {
  it("renders title and icon", () => {
    render(<QueueState icon={<AlertCircle data-testid="alert-icon" />} title="No PRs" detail="" />);

    expect(screen.getByText("No PRs")).toBeInTheDocument();
    expect(screen.getByTestId("alert-icon")).toBeInTheDocument();
  });

  it("renders detail when provided", () => {
    render(<QueueState icon={<span />} title="No PRs" detail="Nothing to review" />);
    expect(screen.getByText("Nothing to review")).toBeInTheDocument();
  });

  it("does not render detail paragraph when detail is empty", () => {
    const { container } = render(<QueueState icon={<span />} title="Loading" detail="" />);
    expect(container.querySelector("p")).not.toBeInTheDocument();
  });
});
