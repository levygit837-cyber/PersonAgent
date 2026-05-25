import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FolderOpen } from "lucide-react";
import { FilterSelect } from "./filter-select";

describe("FilterSelect", () => {
  it("renders selected label", () => {
    render(
      <FilterSelect
        label="Project"
        icon={<FolderOpen data-testid="folder-icon" />}
        value="/a"
        options={[{ value: "/a", label: "Project A" }, { value: "/b", label: "Project B" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Project A")).toBeInTheDocument();
    expect(screen.getByTestId("folder-icon")).toBeInTheDocument();
  });

  it("has correct aria-label", () => {
    render(
      <FilterSelect
        label="Project"
        icon={<FolderOpen />}
        value="/a"
        options={[{ value: "/a", label: "Project A" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button")).toHaveAttribute("aria-label", "Project: Project A");
  });

  it("accepts options prop", () => {
    const { rerender } = render(
      <FilterSelect
        label="Project"
        icon={<FolderOpen />}
        value="/a"
        options={[{ value: "/a", label: "Project A" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Project A")).toBeInTheDocument();

    rerender(
      <FilterSelect
        label="Project"
        icon={<FolderOpen />}
        value="/b"
        options={[{ value: "/a", label: "Project A" }, { value: "/b", label: "Project B" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Project B")).toBeInTheDocument();
  });

  it("falls back to first option label when value is not found", () => {
    render(
      <FilterSelect
        label="Branch"
        icon={<FolderOpen />}
        value="unknown"
        options={[{ value: "all", label: "All branches" }]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("All branches")).toBeInTheDocument();
  });
});
