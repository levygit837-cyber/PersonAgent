import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GenericToolEvent, compactGenericToolLabel } from "./generic-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("generic-tool", () => {
  describe("compactGenericToolLabel", () => {
    it("replaces underscores and hyphens with spaces", () => {
      expect(compactGenericToolLabel("my_tool-name")).toBe("my tool name");
    });
  });

  describe("GenericToolEvent", () => {
    it("renders block title", () => {
      const block: ToolBlockUi = {
        id: "g1",
        name: "CustomTool",
        status: "completed",
        title: "Did something",
        message: "",
        content: "result",
        isCollapsed: true,
      };
      render(<GenericToolEvent block={block} />);
      expect(screen.getByText("Did something - Show")).toBeInTheDocument();
    });

    it("renders LSP tool with operation", () => {
      const block: ToolBlockUi = {
        id: "g2",
        name: "LSP",
        status: "completed",
        title: "LSP",
        message: "",
        content: "",
        data: { operation: "hover" },
        isCollapsed: true,
      };
      render(<GenericToolEvent block={block} />);
      expect(screen.getByText("LSP hover")).toBeInTheDocument();
    });

    it("renders Task tool with title", () => {
      const block: ToolBlockUi = {
        id: "g3",
        name: "Task",
        status: "completed",
        title: "Task",
        message: "",
        content: "",
        data: { task: { title: "Fix bug" } },
        isCollapsed: true,
      };
      render(<GenericToolEvent block={block} />);
      expect(screen.getByText("Task Fix bug")).toBeInTheDocument();
    });
  });
});
