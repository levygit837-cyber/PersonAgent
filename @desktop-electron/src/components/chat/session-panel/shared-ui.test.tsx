import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyList, EmptyPanel, PanelSkeleton, SectionTitle } from "./shared-ui";

describe("SectionTitle", () => {
  it("renders icon and title", () => {
    render(<SectionTitle icon={<span data-testid="icon">I</span>} title="Test Section" />);
    expect(screen.getByTestId("icon")).toBeDefined();
    expect(screen.getByText("Test Section")).toBeDefined();
  });
});

describe("EmptyPanel", () => {
  it("renders text", () => {
    render(<EmptyPanel text="No data available" />);
    expect(screen.getByText("No data available")).toBeDefined();
  });
});

describe("EmptyList", () => {
  it("renders text", () => {
    render(<EmptyList text="Empty list" />);
    expect(screen.getByText("Empty list")).toBeDefined();
  });
});

describe("PanelSkeleton", () => {
  it("renders without error", () => {
    const { container } = render(<PanelSkeleton />);
    expect(container.querySelector(".animate-pulse")).toBeDefined();
  });
});
