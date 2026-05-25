import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrowserVisualEventList, CommitsBlock, FilesBlock, MetadataBlock, MetricBand, TraceJson, TraceList, TraceRoleBadge } from "./components/browser-tracing";
import type { BrowserVisualEvent } from "./helpers";

describe("TraceRoleBadge", () => {
  it("renders role text", () => {
    render(<TraceRoleBadge role="agent" />);
    expect(screen.getByText("agent")).toBeDefined();
  });

  it("renders user role", () => {
    render(<TraceRoleBadge role="user" />);
    expect(screen.getByText("user")).toBeDefined();
  });
});

describe("TraceJson", () => {
  it("renders JSON string", () => {
    render(<TraceJson value={{ foo: "bar" }} />);
    expect(screen.getByText(/foo/)).toBeDefined();
    expect(screen.getByText(/bar/)).toBeDefined();
  });
});

describe("TraceList", () => {
  it("renders empty message when no items", () => {
    render(<TraceList items={[]} empty="No items" />);
    expect(screen.getByText("No items")).toBeDefined();
  });

  it("renders items", () => {
    const items = [{ semantic_label: "Click button", trace_role: "agent" }];
    render(<TraceList items={items} empty="No items" />);
    expect(screen.getByText("Click button")).toBeDefined();
  });
});

describe("MetadataBlock", () => {
  it("renders nothing for empty metadata", () => {
    const { container } = render(<MetadataBlock metadata={{}} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders key-value pairs", () => {
    render(<MetadataBlock metadata={{ status: "running", count: 42 }} />);
    expect(screen.getByText("status")).toBeDefined();
    expect(screen.getByText("running")).toBeDefined();
  });
});

describe("FilesBlock", () => {
  it("renders file entries", () => {
    render(<FilesBlock files={[{ filename: "test.ts", additions: 5, deletions: 2 }]} />);
    expect(screen.getByText("test.ts")).toBeDefined();
    expect(screen.getByText("+5")).toBeDefined();
    expect(screen.getByText("-2")).toBeDefined();
  });
});

describe("CommitsBlock", () => {
  it("renders commit entries", () => {
    render(<CommitsBlock commits={[{ sha: "abc123", message: "fix: something" }]} />);
    expect(screen.getByText("fix: something")).toBeDefined();
    expect(screen.getByText("abc123")).toBeDefined();
  });
});

describe("MetricBand", () => {
  it("renders metric items", () => {
    render(<MetricBand items={[["Tokens", 1234], ["Calls", 5]]} />);
    expect(screen.getByText("1,234")).toBeDefined();
    expect(screen.getByText("Tokens")).toBeDefined();
    expect(screen.getByText("5")).toBeDefined();
    expect(screen.getByText("Calls")).toBeDefined();
  });
});

describe("BrowserVisualEventList", () => {
  it("renders visual events", () => {
    const events: BrowserVisualEvent[] = [
      { id: "e1", toolName: "BrowserClick", status: "completed", effect: "click", url: "https://example.com", elements: [], data: {} },
    ];
    render(<BrowserVisualEventList events={events} />);
    expect(screen.getByText("BrowserClick")).toBeDefined();
    expect(screen.getByText("click")).toBeDefined();
  });

  it("limits to 8 events", () => {
    const events: BrowserVisualEvent[] = Array.from({ length: 12 }, (_, i) => ({
      id: `e${i}`,
      toolName: `Tool${i}`,
      status: "completed" as const,
      effect: "click" as const,
      elements: [],
      data: {},
    }));
    const { container } = render(<BrowserVisualEventList events={events} />);
    const items = container.querySelectorAll(".rounded-lg.border-primary\\/20");
    expect(items.length).toBe(8);
  });
});
