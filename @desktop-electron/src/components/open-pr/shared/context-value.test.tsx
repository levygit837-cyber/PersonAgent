import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContextValue } from "./context-value";

describe("ContextValue", () => {
  it("renders label and value", () => {
    render(<ContextValue label="Author" value="levy" />);

    expect(screen.getByText("Author")).toBeInTheDocument();
    expect(screen.getByText("levy")).toBeInTheDocument();
  });
});
