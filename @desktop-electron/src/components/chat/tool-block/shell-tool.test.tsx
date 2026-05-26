import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ShellToolEvent } from "./shell-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("shell-tool", () => {
  it("renders shell command", () => {
    const block: ToolBlockUi = {
      id: "sh1",
      name: "shell",
      status: "completed",
      title: "Shell command",
      message: "",
      content: "output here",
      data: { command: "npm test" },
      isCollapsed: true,
    };
    render(<ShellToolEvent block={block} />);
    expect(screen.getByText("npm test")).toBeInTheDocument();
  });

  it("renders running state", () => {
    const block: ToolBlockUi = {
      id: "sh2",
      name: "shell",
      status: "running",
      title: "Shell command",
      message: "",
      content: "",
      data: { command: "sleep 5" },
      isCollapsed: true,
    };
    render(<ShellToolEvent block={block} />);
    expect(screen.getByText("sleep 5 running")).toBeInTheDocument();
  });

  it("renders error state", () => {
    const block: ToolBlockUi = {
      id: "sh3",
      name: "shell",
      status: "error",
      title: "Shell command",
      message: "",
      content: "error output",
      data: { command: "badcmd" },
      isCollapsed: true,
    };
    render(<ShellToolEvent block={block} />);
    expect(screen.getByText("Failed: badcmd")).toBeInTheDocument();
  });

  it("renders permission required state", () => {
    const block: ToolBlockUi = {
      id: "sh4",
      name: "shell",
      status: "permission_required",
      title: "Shell command",
      message: "",
      content: "",
      data: { command: "sudo rm" },
      isCollapsed: true,
    };
    render(<ShellToolEvent block={block} />);
    expect(screen.getByText("Permission required: sudo rm")).toBeInTheDocument();
  });
});
