import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TitleBar } from "./titlebar";

describe("TitleBar", () => {
  beforeEach(() => {
    window.personAgent = {
      window: {
        minimize: vi.fn().mockResolvedValue(undefined),
        maximizeToggle: vi.fn().mockResolvedValue(true),
        close: vi.fn().mockResolvedValue(undefined),
        isMaximized: vi.fn().mockResolvedValue(false),
      },
    } as unknown as Window["personAgent"];
  });

  it("keeps the title area draggable while controls remain clickable", () => {
    const { container } = render(<TitleBar compactTitle="Compact Session" />);

    const header = container.querySelector("header");
    expect(header).toHaveClass("drag-region");
    expect(header).toHaveClass("select-none");
    expect(screen.getByText("Compact Session").parentElement).not.toHaveClass("no-drag");
    expect(screen.getByLabelText("Maximize").parentElement).toHaveClass("no-drag");
    expect(screen.getByLabelText("Maximize")).toHaveClass("no-drag");
  });

  it("routes window controls through the desktop bridge", () => {
    render(<TitleBar compactTitle="Compact Session" />);

    fireEvent.click(screen.getByLabelText("Minimize"));
    fireEvent.click(screen.getByLabelText("Maximize"));
    fireEvent.click(screen.getByLabelText("Close"));

    expect(window.personAgent?.window.minimize).toHaveBeenCalledOnce();
    expect(window.personAgent?.window.maximizeToggle).toHaveBeenCalledOnce();
    expect(window.personAgent?.window.close).toHaveBeenCalledOnce();
  });
});
