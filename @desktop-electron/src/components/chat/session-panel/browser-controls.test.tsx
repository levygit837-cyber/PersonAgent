import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BrowserModeButton, BrowserNavButton } from "./browser-controls";

describe("BrowserNavButton", () => {
  it("renders children and label", () => {
    render(<BrowserNavButton label="Go back" disabled={false} onClick={vi.fn()}><span>Back</span></BrowserNavButton>);
    expect(screen.getByLabelText("Go back")).toBeDefined();
    expect(screen.getByText("Back")).toBeDefined();
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<BrowserNavButton label="Go back" disabled={false} onClick={onClick}><span>Back</span></BrowserNavButton>);
    fireEvent.click(screen.getByLabelText("Go back"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("is disabled when disabled prop is true", () => {
    render(<BrowserNavButton label="Go back" disabled={true} onClick={vi.fn()}><span>Back</span></BrowserNavButton>);
    expect(screen.getByLabelText("Go back").hasAttribute("disabled")).toBe(true);
  });
});

describe("BrowserModeButton", () => {
  it("renders with aria-pressed when active", () => {
    render(<BrowserModeButton label="Select" active={true} disabled={false} onClick={vi.fn()}><span>S</span></BrowserModeButton>);
    expect(screen.getByLabelText("Select").getAttribute("aria-pressed")).toBe("true");
  });

  it("renders with aria-pressed false when inactive", () => {
    render(<BrowserModeButton label="Select" active={false} disabled={false} onClick={vi.fn()}><span>S</span></BrowserModeButton>);
    expect(screen.getByLabelText("Select").getAttribute("aria-pressed")).toBe("false");
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<BrowserModeButton label="Select" active={false} disabled={false} onClick={onClick}><span>S</span></BrowserModeButton>);
    fireEvent.click(screen.getByLabelText("Select"));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
