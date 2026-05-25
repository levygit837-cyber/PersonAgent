import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BrowserTabStrip } from "./components/browser-tab-strip";
import type { BrowserTab } from "./helpers";

function makeTabs(): BrowserTab[] {
  return [
    { id: "summary", title: "Summary", closeable: false },
    { id: "browser-1", title: "Example", closeable: true },
  ];
}

describe("BrowserTabStrip", () => {
  it("renders all tabs", () => {
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="summary" onSelect={vi.fn()} onClose={vi.fn()} onAdd={vi.fn()} />);
    expect(screen.getByRole("tab", { name: "Summary" })).toBeDefined();
    expect(screen.getByRole("tab", { name: "Example" })).toBeDefined();
  });

  it("marks active tab with aria-selected", () => {
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="browser-1" onSelect={vi.fn()} onClose={vi.fn()} onAdd={vi.fn()} />);
    expect(screen.getByRole("tab", { name: "Example" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Summary" }).getAttribute("aria-selected")).toBe("false");
  });

  it("calls onSelect when tab clicked", () => {
    const onSelect = vi.fn();
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="summary" onSelect={onSelect} onClose={vi.fn()} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Example" }));
    expect(onSelect).toHaveBeenCalledWith("browser-1");
  });

  it("shows close button only on closeable tabs", () => {
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="summary" onSelect={vi.fn()} onClose={vi.fn()} onAdd={vi.fn()} />);
    expect(screen.queryByLabelText("Close tab Summary")).toBeNull();
    expect(screen.getByLabelText("Close tab Example")).toBeDefined();
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="summary" onSelect={vi.fn()} onClose={onClose} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Close tab Example"));
    expect(onClose).toHaveBeenCalledWith("browser-1");
  });

  it("renders the new tab button", () => {
    render(<BrowserTabStrip tabs={makeTabs()} activeTabId="summary" onSelect={vi.fn()} onClose={vi.fn()} onAdd={vi.fn()} />);
    expect(screen.getByLabelText("New panel tab")).toBeDefined();
  });
});
