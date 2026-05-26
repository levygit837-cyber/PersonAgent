import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SearchToolEvent, searchRunningLabel, searchCollapsedLabel } from "./search-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("search-tool", () => {
  describe("labels", () => {
    it("searchRunningLabel returns correct text", () => {
      expect(searchRunningLabel()).toBe("Searching...");
    });

    it("searchCollapsedLabel formats correctly", () => {
      expect(searchCollapsedLabel(1)).toBe("Search 1 time >");
      expect(searchCollapsedLabel(3)).toBe("Search 3 times >");
    });
  });

  describe("SearchToolEvent", () => {
    it("renders grep label with pattern", () => {
      const block: ToolBlockUi = {
        id: "s1",
        name: "Grep",
        status: "completed",
        title: "Grep",
        message: "",
        content: "",
        data: { pattern: "console.log" },
        isCollapsed: true,
      };
      render(<SearchToolEvent block={block} />);
      expect(screen.getByText("Grep - console.log")).toBeInTheDocument();
    });

    it("renders running label", () => {
      const block: ToolBlockUi = {
        id: "s2",
        name: "Grep",
        status: "running",
        title: "Grep",
        message: "",
        content: "",
        data: { pattern: "foo" },
        isCollapsed: true,
      };
      render(<SearchToolEvent block={block} />);
      expect(screen.getByText("Searching...")).toBeInTheDocument();
    });

    it("renders glob label with pattern", () => {
      const block: ToolBlockUi = {
        id: "s3",
        name: "Glob",
        status: "completed",
        title: "Glob",
        message: "",
        content: "",
        data: { pattern: "*.ts" },
        isCollapsed: true,
      };
      render(<SearchToolEvent block={block} />);
      expect(screen.getByText("Glob - *.ts")).toBeInTheDocument();
    });
  });
});
