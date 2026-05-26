import { describe, expect, it } from "vitest";
import {
  isTodoTool,
  isSearchShellCommand,
  isFileMutationTool,
  isSearchTool,
  isRunning,
  isError,
  stringValue,
  numberValue,
  hasNonWhitespace,
  statusTextClass,
  statusDotClass,
} from "./shared";
import type { ToolBlockUi } from "../../../types/chat";

describe("shared utilities", () => {
  describe("isTodoTool", () => {
    it("returns true for todo-prefixed names", () => {
      expect(isTodoTool({ name: "todo" })).toBe(true);
      expect(isTodoTool({ name: "TodoList" })).toBe(true);
      expect(isTodoTool({ name: "TODO" })).toBe(true);
    });

    it("returns false for non-todo names", () => {
      expect(isTodoTool({ name: "shell" })).toBe(false);
      expect(isTodoTool({ name: "Read" })).toBe(false);
    });
  });

  describe("isSearchShellCommand", () => {
    it("returns true for find/grep/rg shell commands", () => {
      expect(isSearchShellCommand({ name: "shell", data: { command: "find . -name '*.ts'" } } as unknown as ToolBlockUi)).toBe(true);
      expect(isSearchShellCommand({ name: "shell", data: { command: "grep -r pattern" } } as unknown as ToolBlockUi)).toBe(true);
      expect(isSearchShellCommand({ name: "shell", data: { command: "rg pattern" } } as unknown as ToolBlockUi)).toBe(true);
    });

    it("returns false for other shell commands", () => {
      expect(isSearchShellCommand({ name: "shell", data: { command: "npm install" } } as unknown as ToolBlockUi)).toBe(false);
    });

    it("returns false for non-shell blocks", () => {
      expect(isSearchShellCommand({ name: "Read" } as unknown as ToolBlockUi)).toBe(false);
    });
  });

  describe("isFileMutationTool", () => {
    it("returns true for Write and Edit", () => {
      expect(isFileMutationTool({ name: "Write" })).toBe(true);
      expect(isFileMutationTool({ name: "Edit" })).toBe(true);
    });

    it("returns false for other tools", () => {
      expect(isFileMutationTool({ name: "Read" })).toBe(false);
    });
  });

  describe("isSearchTool", () => {
    it("returns true for Glob, Grep, search_files", () => {
      expect(isSearchTool({ name: "Glob" } as unknown as ToolBlockUi)).toBe(true);
      expect(isSearchTool({ name: "Grep" } as unknown as ToolBlockUi)).toBe(true);
      expect(isSearchTool({ name: "search_files" } as unknown as ToolBlockUi)).toBe(true);
    });

    it("returns true for search shell commands", () => {
      expect(isSearchTool({ name: "shell", data: { command: "grep pattern" } } as unknown as ToolBlockUi)).toBe(true);
    });
  });

  describe("isRunning", () => {
    it("returns true for running and queued", () => {
      expect(isRunning({ status: "running" } as unknown as ToolBlockUi)).toBe(true);
      expect(isRunning({ status: "queued" } as unknown as ToolBlockUi)).toBe(true);
    });

    it("returns false for completed", () => {
      expect(isRunning({ status: "completed" } as unknown as ToolBlockUi)).toBe(false);
    });
  });

  describe("isError", () => {
    it("returns true for error status", () => {
      expect(isError({ status: "error" } as unknown as ToolBlockUi)).toBe(true);
    });

    it("returns false for other statuses", () => {
      expect(isError({ status: "completed" } as unknown as ToolBlockUi)).toBe(false);
    });
  });

  describe("stringValue", () => {
    it("returns trimmed string for valid input", () => {
      expect(stringValue(" hello ")).toBe("hello");
    });

    it("returns undefined for empty or non-string", () => {
      expect(stringValue("")).toBeUndefined();
      expect(stringValue("   ")).toBeUndefined();
      expect(stringValue(123)).toBeUndefined();
    });
  });

  describe("numberValue", () => {
    it("returns number for valid input", () => {
      expect(numberValue(42)).toBe(42);
    });

    it("returns undefined for invalid input", () => {
      expect(numberValue("42")).toBeUndefined();
      expect(numberValue(NaN)).toBeUndefined();
      expect(numberValue(Infinity)).toBeUndefined();
    });
  });

  describe("hasNonWhitespace", () => {
    it("returns true for non-whitespace strings", () => {
      expect(hasNonWhitespace("hello")).toBe(true);
    });

    it("returns false for whitespace-only strings", () => {
      expect(hasNonWhitespace("   ")).toBe(false);
      expect(hasNonWhitespace("")).toBe(false);
    });
  });

  describe("statusTextClass", () => {
    it("returns correct classes", () => {
      expect(statusTextClass("error")).toBe("text-destructive");
      expect(statusTextClass("permission_required")).toBe("text-warning");
      expect(statusTextClass("completed")).toBe("text-muted-foreground");
    });
  });

  describe("statusDotClass", () => {
    it("returns correct classes", () => {
      expect(statusDotClass("error")).toBe("bg-destructive");
      expect(statusDotClass("permission_required")).toBe("bg-warning");
      expect(statusDotClass("completed")).toBe("bg-success");
    });
  });
});
