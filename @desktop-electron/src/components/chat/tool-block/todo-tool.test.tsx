import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TodoToolEvent, TodoToolGroupBlock } from "./todo-tool";
import type { ToolBlockUi } from "../../../types/chat";

describe("todo-tool", () => {
  it("renders todo tracker with items", () => {
    const block: ToolBlockUi = {
      id: "t1",
      name: "todo",
      status: "running",
      title: "todo",
      message: "",
      content: JSON.stringify({
        todos: [
          { id: "1", content: "First task", status: "completed" },
          { id: "2", content: "Second task", status: "in_progress" },
        ],
      }),
      isCollapsed: true,
    };
    render(<TodoToolEvent block={block} />);
    expect(screen.getByTestId("todo-tracker")).toBeInTheDocument();
    expect(screen.getByText("Todos")).toBeInTheDocument();
    expect(screen.getByText("First task")).toBeInTheDocument();
    expect(screen.getByText("Second task")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("renders todo group block", () => {
    const blocks: ToolBlockUi[] = [
      {
        id: "t1",
        name: "todo",
        status: "completed",
        title: "todo",
        message: "",
        content: JSON.stringify({
          todos: [{ id: "1", content: "Task 1", status: "completed" }],
        }),
        isCollapsed: true,
      },
    ];
    render(<TodoToolGroupBlock blocks={blocks} />);
    expect(screen.getByTestId("todo-tracker")).toBeInTheDocument();
  });

  it("falls back to generic when no todos", () => {
    const block: ToolBlockUi = {
      id: "t2",
      name: "todo",
      status: "completed",
      title: "todo",
      message: "",
      content: "",
      isCollapsed: true,
    };
    render(<TodoToolEvent block={block} />);
    expect(screen.queryByTestId("todo-tracker")).not.toBeInTheDocument();
  });
});
