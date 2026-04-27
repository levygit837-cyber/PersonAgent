import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownContent } from "./agent-message";

describe("MarkdownContent", () => {
  it("renders wide tables inside a constrained horizontal scroller", () => {
    const { container } = render(
      <MarkdownContent
        content={[
          "| Tendencia | Evidencia principal | Impactos chave | Principais desafios |",
          "| --- | --- | --- | --- |",
          "| Deflacao da bolha | Forbes e MIT Sloan<br>Stanford AI Index | Pressao para justificar ROI | Risco de under-investment |",
        ].join("\n")}
      />,
    );

    const table = container.querySelector("table");
    const scroller = table?.parentElement;

    expect(table).not.toBeNull();
    expect(scroller).not.toBeNull();
    expect(scroller).toHaveClass("overflow-x-auto");
    expect(scroller).toHaveClass("max-w-full");
    expect(container.querySelector("td br")).not.toBeNull();
  });
});
