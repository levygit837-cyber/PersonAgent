import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReadToolEvent, readRunningLabel, readCollapsedLabel } from "./read-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("read-tool", () => {
  describe("labels", () => {
    it("readRunningLabel formats correctly", () => {
      expect(readRunningLabel(1)).toBe("Reading 1 File...");
      expect(readRunningLabel(3)).toBe("Reading 3 Files...");
    });

    it("readCollapsedLabel formats correctly", () => {
      expect(readCollapsedLabel(1)).toBe("Read 1 File >");
      expect(readCollapsedLabel(2)).toBe("Read 2 Files >");
    });
  });

  describe("ReadToolEvent", () => {
    it("renders read event text", () => {
      const block: ToolBlockUi = {
        id: "r1",
        name: "Read",
        status: "completed",
        title: "Read README.md",
        message: "",
        content: "",
        path: "README.md",
        isCollapsed: true,
      };
      render(<ReadToolEvent block={block} />);
      expect(screen.getByText("Read README.md")).toBeInTheDocument();
    });

    it("renders running label", () => {
      const block: ToolBlockUi = {
        id: "r2",
        name: "Read",
        status: "running",
        title: "Reading file",
        message: "",
        content: "",
        isCollapsed: true,
      };
      render(<ReadToolEvent block={block} />);
      expect(screen.getByText("Reading 1 File...")).toBeInTheDocument();
    });

    it("renders error state", () => {
      const block: ToolBlockUi = {
        id: "r3",
        name: "Read",
        status: "error",
        title: "Read missing.txt",
        message: "",
        content: "",
        path: "missing.txt",
        isCollapsed: true,
      };
      render(<ReadToolEvent block={block} />);
      expect(screen.getByText("Failed Read missing.txt")).toBeInTheDocument();
    });

    it("renders permission required state", () => {
      const block: ToolBlockUi = {
        id: "r4",
        name: "Read",
        status: "permission_required",
        title: "Read secret.txt",
        message: "",
        content: "",
        path: "secret.txt",
        isCollapsed: true,
      };
      render(<ReadToolEvent block={block} />);
      expect(screen.getByText("Permission required for Read secret.txt")).toBeInTheDocument();
    });
  });
});
