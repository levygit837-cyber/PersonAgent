import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WriteToolEvent, writeHasOutput, writeOutputRows } from "./write-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("write-tool", () => {
  describe("writeHasOutput", () => {
    it("returns true when diff is present", () => {
      const block = { id: "w0", name: "Write", status: "completed", title: "Write", message: "", content: "", isCollapsed: true, data: { diff: "+line" } } as ToolBlockUi;
      expect(writeHasOutput(block)).toBe(true);
    });

    it("returns true when written_content is present", () => {
      const block = { id: "w0", name: "Write", status: "completed", title: "Write", message: "", content: "", isCollapsed: true, data: { written_content: "hello" } } as ToolBlockUi;
      expect(writeHasOutput(block)).toBe(true);
    });

    it("returns false when no output", () => {
      const block = { data: {}, content: "" } as ToolBlockUi;
      expect(writeHasOutput(block)).toBe(false);
    });
  });

  describe("writeOutputRows", () => {
    it("parses diff into rows", () => {
      const block = { id: "w0", name: "Write", status: "completed", title: "Write", message: "", content: "", isCollapsed: true, data: { diff: "@@ -1,2 +1,2 @@\n-old\n+new" } } as ToolBlockUi;
      const rows = writeOutputRows(block);
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.some((r) => r.kind === "add")).toBe(true);
    });

    it("returns content lines for written_content", () => {
      const block = { id: "w0", name: "Write", status: "completed", title: "Write", message: "", content: "", isCollapsed: true, data: { written_content: "line1\nline2" } } as ToolBlockUi;
      const rows = writeOutputRows(block);
      expect(rows).toHaveLength(2);
      expect(rows[0].kind).toBe("add");
    });
  });

  describe("WriteToolEvent", () => {
    it("renders write event", () => {
      const block: ToolBlockUi = {
        id: "w1",
        name: "Write",
        status: "completed",
        title: "Write",
        message: "",
        content: "",
        path: "test.ts",
        data: { written_content: "const x = 1;" },
        isCollapsed: true,
      };
      render(<WriteToolEvent block={block} />);
      expect(screen.getByText("Write - test.ts")).toBeInTheDocument();
    });

    it("renders edit event", () => {
      const block: ToolBlockUi = {
        id: "w2",
        name: "Edit",
        status: "completed",
        title: "Edit",
        message: "",
        content: "",
        path: "test.ts",
        data: { diff: "@@ -1 +1 @@\n-old\n+new" },
        isCollapsed: true,
      };
      render(<WriteToolEvent block={block} />);
      expect(screen.getByText("Edit - test.ts")).toBeInTheDocument();
    });
  });
});
