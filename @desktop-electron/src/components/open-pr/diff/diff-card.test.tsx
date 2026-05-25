import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DiffCard, diffLineClass, linePrefix } from "./diff-card";
import type { PullRequestSummary } from "../../../api/client";

function makeFile(overrides?: Partial<PullRequestSummary["files"][number]>): PullRequestSummary["files"][number] {
  return {
    id: "file-1",
    path: "src/components/button.tsx",
    changeType: "modified",
    additions: 10,
    deletions: 2,
    summary: "Updated button styles",
    lines: [
      { number: "1", kind: "context", content: "import React from 'react';" },
      { number: "2", kind: "add", content: "import { cn } from './utils';" },
      { number: "3", kind: "delete", content: "const Button = () => {};" },
    ],
    ...overrides,
  };
}

describe("DiffCard", () => {
  it("renders file path and change metadata", () => {
    render(<DiffCard file={makeFile()} active={false} canClose={true} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText("src/components/button.tsx")).toBeInTheDocument();
    expect(screen.getByText("modified / +10 -2")).toBeInTheDocument();
  });

  it("renders diff lines in a table", () => {
    render(<DiffCard file={makeFile()} active={false} canClose={true} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText((content) => content.includes("import React from 'react';"))).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("import { cn } from './utils';"))).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes("const Button = () => {};"))).toBeInTheDocument();
  });

  it("renders line numbers", () => {
    render(<DiffCard file={makeFile()} active={false} canClose={true} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows empty state when no diff lines are available", () => {
    render(<DiffCard file={makeFile({ lines: [] })} active={false} canClose={true} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText(/Diff lines are not available/i)).toBeInTheDocument();
  });

  it("calls onFocus when the header is clicked", () => {
    const onFocus = vi.fn();
    render(<DiffCard file={makeFile()} active={false} canClose={true} onFocus={onFocus} onClose={vi.fn()} />);

    fireEvent.click(screen.getByText("src/components/button.tsx"));
    expect(onFocus).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<DiffCard file={makeFile()} active={false} canClose={true} onFocus={vi.fn()} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /Close diff/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("disables close button when canClose is false", () => {
    render(<DiffCard file={makeFile()} active={false} canClose={false} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: /Close diff/i })).toBeDisabled();
  });

  it("sets active data-testid with file id", () => {
    render(<DiffCard file={makeFile({ id: "my-file" })} active={false} canClose={true} onFocus={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByTestId("open-diff-card-my-file")).toBeInTheDocument();
  });
});

describe("diffLineClass", () => {
  it("returns success class for add lines", () => {
    expect(diffLineClass("add")).toContain("bg-success/10");
    expect(diffLineClass("add")).toContain("text-success");
  });

  it("returns destructive class for delete lines", () => {
    expect(diffLineClass("delete")).toContain("bg-destructive/10");
    expect(diffLineClass("delete")).toContain("text-destructive");
    expect(diffLineClass("delete")).toContain("line-through");
  });

  it("returns empty string for context lines", () => {
    expect(diffLineClass("context")).toBe("");
  });
});

describe("linePrefix", () => {
  it("returns + for add lines", () => {
    expect(linePrefix("add")).toBe("+");
  });

  it("returns - for delete lines", () => {
    expect(linePrefix("delete")).toBe("-");
  });

  it("returns space for context lines", () => {
    expect(linePrefix("context")).toBe(" ");
  });
});
