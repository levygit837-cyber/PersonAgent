import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MarkdownContent,
  GeneratedImageContent,
  ChatExecutionStatus,
  compactToolKindFor,
  renderToolBlocks,
} from "./content-blocks";
import type { GeneratedImage, ToolBlockUi } from "../../../types/chat";

describe("MarkdownContent", () => {
  it("renders plain text", () => {
    render(<MarkdownContent content="Hello world" />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders headings", () => {
    const { container } = render(<MarkdownContent content="# Title" />);
    expect(container.querySelector("h1")).toHaveTextContent("Title");
  });

  it("renders unordered lists", () => {
    const { container } = render(<MarkdownContent content={"- Item 1\n- Item 2"} />);
    expect(container.querySelector("ul")).not.toBeNull();
    expect(screen.getByText("Item 1")).toBeInTheDocument();
    expect(screen.getByText("Item 2")).toBeInTheDocument();
  });

  it("renders ordered lists", () => {
    const { container } = render(<MarkdownContent content={"1. First\n2. Second"} />);
    expect(container.querySelector("ol")).not.toBeNull();
    expect(screen.getByText("First")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
  });

  it("renders wide tables inside a constrained horizontal scroller", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "| Tendencia | Evidencia principal | Impactos chave | Principais desafios |",
          "| --- | --- | --- | --- |",
          "| Deflacao da bolha | Forbes e MIT Sloan<br>Stanford AI Index | Pressao para justificar ROI | Risco de under-investment |",
        ].join("\n")}
      />,
    );

    const table = container.querySelector("table");
    const scroller = table?.parentElement;

    expect(table).not.toBeNull();
    expect(scroller).not.toBeNull();
    expect(scroller).toHaveClass("overflow-x-auto");
    expect(scroller).toHaveClass("max-w-full");
    expect(container.querySelector("td br")).not.toBeNull();
  });

  it("renders blockquotes", () => {
    const { container } = render(<MarkdownContent content="> A quote" />);
    expect(container.querySelector("blockquote")).toHaveTextContent("A quote");
  });

  it("renders inline code", () => {
    const { container } = render(<MarkdownContent content="Use `npm install`" />);
    const code = container.querySelector("code");
    expect(code).not.toBeNull();
    expect(code).toHaveTextContent("npm install");
  });

  it("renders links with primary color", () => {
    const { container } = render(<MarkdownContent content="[link](https://example.com)" />);
    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveClass("text-primary");
  });

  it("handles <br> tags in markdown", () => {
    const { container } = render(<MarkdownContent content="Line 1<br>Line 2" />);
    expect(container.innerHTML).toContain("Line 1");
    expect(container.innerHTML).toContain("Line 2");
  });
});

describe("GeneratedImageContent", () => {
  it("renders image from URL", () => {
    const image: GeneratedImage = { url: "https://example.com/img.png", mime_type: "image/png", alt: "Test image" };
    const { container } = render(<GeneratedImageContent image={image} />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "https://example.com/img.png");
    expect(img).toHaveAttribute("alt", "Test image");
  });

  it("renders image from base64 data", () => {
    const image: GeneratedImage = { data: "abc123", mime_type: "image/jpeg", alt: "Base64 image" };
    const { container } = render(<GeneratedImageContent image={image} />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "data:image/jpeg;base64,abc123");
  });

  it("returns null when no src is available", () => {
    const image: GeneratedImage = {};
    const { container } = render(<GeneratedImageContent image={image} />);
    expect(container.firstChild).toBeNull();
  });

  it("uses image/png as default mime type", () => {
    const image: GeneratedImage = { data: "abc123" };
    const { container } = render(<GeneratedImageContent image={image} />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("src", "data:image/png;base64,abc123");
  });
});

describe("ChatExecutionStatus", () => {
  it("renders thinking indicator with spinner and text", () => {
    render(<ChatExecutionStatus />);
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("compactToolKindFor", () => {
  it("returns 'read' for Read tool", () => {
    expect(compactToolKindFor({ name: "Read", id: "1", status: "completed", params: {}, result: "" })).toBe("read");
  });

  it("returns 'write' for Write tool", () => {
    expect(compactToolKindFor({ name: "Write", id: "1", status: "completed", params: {}, result: "" })).toBe("write");
  });

  it("returns 'search' for Glob tool", () => {
    expect(compactToolKindFor({ name: "Glob", id: "1", status: "completed", params: {}, result: "" })).toBe("search");
  });

  it("returns 'shell' for shell tool", () => {
    expect(compactToolKindFor({ name: "shell", id: "1", status: "completed", params: {}, result: "" })).toBe("shell");
  });

  it("returns 'web' for WebFetch tool", () => {
    expect(compactToolKindFor({ name: "WebFetch", id: "1", status: "completed", params: {}, result: "" })).toBe("web");
  });

  it("returns 'lsp' for LSP tool", () => {
    expect(compactToolKindFor({ name: "LSP", id: "1", status: "completed", params: {}, result: "" })).toBe("lsp");
  });

  it("returns 'task' for Task tool", () => {
    expect(compactToolKindFor({ name: "Task", id: "1", status: "completed", params: {}, result: "" })).toBe("task");
  });

  it("returns undefined for empty tool name", () => {
    expect(compactToolKindFor({ name: "", id: "1", status: "completed", params: {}, result: "" })).toBeUndefined();
  });
});

describe("renderToolBlocks", () => {
  it("returns empty array for empty input", () => {
    expect(renderToolBlocks([])).toHaveLength(0);
  });

  it("renders individual tool blocks for non-compactable tools", () => {
    const blocks: ToolBlockUi[] = [
      { name: "WebFetch", id: "1", status: "completed", params: {}, result: "" },
    ];
    const result = renderToolBlocks(blocks);
    expect(result).toHaveLength(1);
  });

  it("groups compactable read tools together", () => {
    const blocks: ToolBlockUi[] = [
      { name: "Read", id: "1", status: "completed", params: {}, result: "" },
      { name: "Read", id: "2", status: "completed", params: {}, result: "" },
    ];
    const result = renderToolBlocks(blocks);
    expect(result).toHaveLength(1);
  });
});
