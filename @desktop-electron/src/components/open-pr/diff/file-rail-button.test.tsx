import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FileRailButton, DND_FILE_MIME } from "./file-rail-button";
import type { PullRequestSummary } from "../../../api/client";

function makeFile(overrides?: Partial<PullRequestSummary["files"][number]>): PullRequestSummary["files"][number] {
  return {
    id: "file-1",
    path: "src/components/button.tsx",
    changeType: "modified",
    additions: 10,
    deletions: 2,
    summary: "Updated button styles",
    lines: [],
    ...overrides,
  };
}

describe("FileRailButton", () => {
  it("renders file path and metadata", () => {
    render(<FileRailButton file={makeFile()} active={false} onOpen={vi.fn()} />);

    expect(screen.getByText("src/components/button.tsx")).toBeInTheDocument();
    expect(screen.getByText("modified")).toBeInTheDocument();
    expect(screen.getByText("+10")).toBeInTheDocument();
    expect(screen.getByText("-2")).toBeInTheDocument();
    expect(screen.getByText("Updated button styles")).toBeInTheDocument();
  });

  it("calls onOpen when clicked", () => {
    const onOpen = vi.fn();
    render(<FileRailButton file={makeFile()} active={false} onOpen={onOpen} />);

    fireEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("sets drag data with file id on drag start", () => {
    render(<FileRailButton file={makeFile({ id: "my-drag-file" })} active={false} onOpen={vi.fn()} />);

    const button = screen.getByRole("button");
    const dataTransfer = {
      effectAllowed: "",
      setData: vi.fn(),
    } as unknown as DataTransfer;

    fireEvent.dragStart(button, { dataTransfer });

    expect(dataTransfer.setData).toHaveBeenCalledWith(DND_FILE_MIME, "my-drag-file");
    expect(dataTransfer.setData).toHaveBeenCalledWith("text/plain", "my-drag-file");
    expect(dataTransfer.effectAllowed).toBe("copy");
  });

  it("has correct aria-label", () => {
    render(<FileRailButton file={makeFile({ path: "app.tsx" })} active={false} onOpen={vi.fn()} />);

    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Open diff for app.tsx");
  });

  it("is draggable", () => {
    render(<FileRailButton file={makeFile()} active={false} onOpen={vi.fn()} />);

    expect(screen.getByRole("button")).toHaveAttribute("draggable", "true");
  });
});
