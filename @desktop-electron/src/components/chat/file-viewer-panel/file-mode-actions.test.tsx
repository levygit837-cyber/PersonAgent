import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "../../ui/tooltip";
import { FileModeActions } from "./file-mode-actions";

function renderWithTooltip(element: React.ReactElement) {
  return render(<TooltipProvider>{element}</TooltipProvider>);
}

describe("FileModeActions", () => {
  it("renders nothing for a plain text file", () => {
    const { container } = renderWithTooltip(
      <FileModeActions fileName="notes.txt" mode="code" onModeChange={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders HTML preview and code buttons for an HTML file", () => {
    renderWithTooltip(<FileModeActions fileName="index.html" mode="code" onModeChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Preview HTML" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View code" })).toBeInTheDocument();
  });

  it("renders markdown preview button for a markdown file", () => {
    renderWithTooltip(<FileModeActions fileName="README.md" mode="code" onModeChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Markdown preview" })).toBeInTheDocument();
  });

  it("calls onModeChange when a button is clicked", () => {
    const onModeChange = vi.fn();
    renderWithTooltip(<FileModeActions fileName="index.html" mode="code" onModeChange={onModeChange} />);
    screen.getByRole("button", { name: "Preview HTML" }).click();
    expect(onModeChange).toHaveBeenCalledWith("html");
  });
});
