import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HtmlPreview } from "./html-preview";

describe("HtmlPreview", () => {
  it("renders an iframe with the content", () => {
    render(<HtmlPreview content="<h1>Hello</h1>" fileName="test.html" />);
    const iframe = screen.getByTitle("Preview test.html");
    expect(iframe).toBeInTheDocument();
    expect(iframe.tagName).toBe("IFRAME");
    expect(iframe).toHaveAttribute("srcDoc", "<h1>Hello</h1>");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
  });
});
