import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownPreview } from "./markdown-preview";

describe("MarkdownPreview", () => {
  it("renders markdown content in a scrollable container", () => {
    const { container } = render(<MarkdownPreview content="# Hello" />);
    const wrapper = container.querySelector(".h-full.overflow-y-auto");
    expect(wrapper).toBeInTheDocument();
    expect(wrapper).toHaveClass("bg-card/95", "px-5", "py-4");
  });

  it("passes content to MarkdownContent", () => {
    const { container } = render(<MarkdownPreview content="test content" />);
    expect(container.querySelector(".markdown-content")).toBeInTheDocument();
  });
});
