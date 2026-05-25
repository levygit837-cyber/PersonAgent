import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueueFilterButton } from "./queue-filter-button";

describe("QueueFilterButton", () => {
  it("renders children", () => {
    render(<QueueFilterButton active={false} onClick={vi.fn()}>Mine</QueueFilterButton>);
    expect(screen.getByText("Mine")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<QueueFilterButton active={false} onClick={onClick}>All</QueueFilterButton>);

    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("applies active class when active", () => {
    const { container } = render(<QueueFilterButton active={true} onClick={vi.fn()}>All</QueueFilterButton>);
    expect(container.firstChild).toHaveClass("bg-primary/10", "text-foreground");
  });

  it("applies bordered class when bordered", () => {
    const { container } = render(<QueueFilterButton active={false} bordered onClick={vi.fn()}>Mine</QueueFilterButton>);
    expect(container.firstChild).toHaveClass("border-l", "border-glass-border/25");
  });
});
