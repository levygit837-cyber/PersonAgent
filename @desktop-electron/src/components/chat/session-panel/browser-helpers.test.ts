/**
 * Unit tests for browser-helpers.ts (Slice 3).
 *
 * Covers the pure helper functions extracted from session-panel.tsx.
 */

import { describe, expect, it } from "vitest";
import type { ToolBlockUi } from "../../../types/chat";
import type { BrowserState, BrowserToolEvent } from "./helpers";
import { createEmptyBrowserState } from "./helpers";
import {
  browserToolEventAppliesToBrowser,
  browserToolEventIsAction,
  browserToolEventIsPassive,
  browserVisualEventsFromBlocks,
  formatNumber,
  formatValue,
  labelize,
  normalizeBrowserUrl,
} from "./browser-helpers";
import { browserTabsFromBlocks } from "./browser-tab-helpers";
import { browserEffectFromToolAction, browserToolEffect } from "./browser-visual-events";
import {
  browserHasMeaningfulPage,
  browserMeaningfulToolUrl,
  browserToolEventUrl,
  browserToolShouldFetchRenderedView,
  browserToolShouldHydrateView,
  browserToolShouldPreserveCurrentView,
  browserToolShouldSyncDisplayedPage,
  browserToolUrlChanged,
  browserViewFromToolEvent,
} from "./browser-view-helpers";
import { selectedElementLabel } from "./browser-normalization-helpers";
import { numericValue, recordArray } from "./helpers";

function makeBlock(name: string, status: "running" | "completed" = "running", data: Record<string, unknown> = {}): ToolBlockUi {
  return { id: `b-${name}`, name, status, title: name, message: "", content: "", data, isCollapsed: true };
}

function makeEvent(overrides: Partial<BrowserToolEvent> = {}): BrowserToolEvent {
  return {
    id: "test-event",
    toolName: "BrowserOpen",
    status: "completed",
    effect: "highlight",
    browserId: "b1",
    pageId: "p1",
    url: "https://example.com",
    elements: [],
    data: {},
    ...overrides,
  };
}

describe("formatNumber", () => {
  it("formats integers with commas", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });
  it("formats zero", () => {
    expect(formatNumber(0)).toBe("0");
  });
});

describe("formatValue", () => {
  it("returns string for primitives", () => {
    expect(formatValue("hello")).toBe("hello");
    expect(formatValue(42)).toBe("42");
    expect(formatValue(true)).toBe("true");
  });
  it("returns JSON for objects", () => {
    expect(formatValue({ a: 1 })).toBe(JSON.stringify({ a: 1 }, null, 2));
  });
});

describe("labelize", () => {
  it("replaces underscores with spaces", () => {
    expect(labelize("hello_world_test")).toBe("hello world test");
  });
});

describe("normalizeBrowserUrl", () => {
  it("returns empty for blank", () => {
    expect(normalizeBrowserUrl("")).toBe("");
    expect(normalizeBrowserUrl("  ")).toBe("");
  });
  it("keeps http/https URLs as-is", () => {
    expect(normalizeBrowserUrl("https://example.com")).toBe("https://example.com");
    expect(normalizeBrowserUrl("http://test.org")).toBe("http://test.org");
  });
  it("prepends https when missing", () => {
    expect(normalizeBrowserUrl("example.com")).toBe("https://example.com");
  });
});

describe("numericValue", () => {
  it("returns number for valid number", () => {
    expect(numericValue(42)).toBe(42);
    expect(numericValue(0)).toBe(0);
  });
  it("parses numeric string", () => {
    expect(numericValue("123")).toBe(123);
  });
  it("returns undefined for invalid", () => {
    expect(numericValue("abc")).toBeUndefined();
    expect(numericValue(undefined)).toBeUndefined();
    expect(numericValue(null)).toBeUndefined();
    expect(numericValue(NaN)).toBeUndefined();
    expect(numericValue(Infinity)).toBeUndefined();
  });
});

describe("recordArray", () => {
  it("filters non-object items", () => {
    expect(recordArray([{ a: 1 }, "hello", null, [1, 2], { b: 2 }])).toEqual([{ a: 1 }, { b: 2 }]);
  });
  it("returns empty for non-array", () => {
    expect(recordArray("hello")).toEqual([]);
    expect(recordArray(undefined)).toEqual([]);
  });
});

describe("selectedElementLabel", () => {
  it("returns nodeId when element is undefined", () => {
    expect(selectedElementLabel(undefined, "n1")).toBe("n1");
  });
  it("returns role with text", () => {
    expect(selectedElementLabel({ node_id: "n1", role: "button", text: "Submit" }, "n1")).toBe("button · Submit");
  });
  it("truncates long text", () => {
    const longText = "x".repeat(200);
    const label = selectedElementLabel({ node_id: "n1", tag: "div", text: longText }, "n1");
    expect(label.length).toBeLessThan(100);
  });
});

describe("browserToolEffect", () => {
  it("returns undefined for non-browser tools", () => {
    expect(browserToolEffect(makeBlock("SearchWeb"))).toBeUndefined();
  });
  it("returns undefined for tab management tools", () => {
    expect(browserToolEffect(makeBlock("BrowserListTabs"))).toBeUndefined();
    expect(browserToolEffect(makeBlock("BrowserCloseTab"))).toBeUndefined();
    expect(browserToolEffect(makeBlock("BrowserWait"))).toBeUndefined();
  });
  it("maps click tools", () => {
    expect(browserToolEffect(makeBlock("BrowserClick"))).toBe("click");
  });
  it("maps type tools", () => {
    expect(browserToolEffect(makeBlock("BrowserType"))).toBe("type");
  });
  it("maps scroll tools", () => {
    expect(browserToolEffect(makeBlock("BrowserScroll"))).toBe("scroll");
    expect(browserToolEffect(makeBlock("BrowserHistory"))).toBe("scroll");
  });
  it("maps screenshot/extract tools", () => {
    expect(browserToolEffect(makeBlock("BrowserScreenshot"))).toBe("extract");
    expect(browserToolEffect(makeBlock("BrowserExtractContent"))).toBe("extract");
  });
  it("maps element map tool", () => {
    expect(browserToolEffect(makeBlock("BrowserGetElementMap"))).toBe("map");
  });
  it("defaults to highlight for other Browser tools", () => {
    expect(browserToolEffect(makeBlock("BrowserOpen"))).toBe("highlight");
  });
  it("maps BrowserAct actions", () => {
    expect(browserToolEffect(makeBlock("BrowserAct", "running", { action: "click_element" }))).toBe("click");
    expect(browserToolEffect(makeBlock("BrowserAct", "running", { action: "type_text" }))).toBe("type");
    expect(browserToolEffect(makeBlock("BrowserAct", "running", { action: "scroll_down" }))).toBe("scroll");
    expect(browserToolEffect(makeBlock("BrowserAct", "running", { action: "take_screenshot" }))).toBe("extract");
  });
});

describe("browserVisualEventsFromBlocks", () => {
  it("returns empty for empty blocks", () => {
    expect(browserVisualEventsFromBlocks([])).toEqual([]);
  });
  it("extracts events from browser blocks", () => {
    const blocks = [makeBlock("BrowserOpen", "completed", { url: "https://x.com", document_html: "<html></html>" })];
    const events = browserVisualEventsFromBlocks(blocks);
    expect(events.length).toBe(1);
    expect(events[0].toolName).toBe("BrowserOpen");
  });
  it("limits to 12 events", () => {
    const blocks = Array.from({ length: 20 }, (_, i) =>
      makeBlock("BrowserClick", "completed", { url: `https://x.com/${i}`, document_html: "<html></html>", node_id: `n${i}` }),
    );
    expect(browserVisualEventsFromBlocks(blocks).length).toBeLessThanOrEqual(12);
  });
});

describe("browserTabsFromBlocks", () => {
  it("returns empty for non-tab blocks", () => {
    expect(browserTabsFromBlocks([makeBlock("BrowserClick")])).toEqual([]);
  });
  it("extracts tabs from BrowserOpen block", () => {
    const block = makeBlock("BrowserOpen", "completed", {
      url: "https://example.com",
      page_id: "p1",
      browser_id: "b1",
      title: "Example",
    });
    const tabs = browserTabsFromBlocks([block]);
    expect(tabs.length).toBe(1);
    expect(tabs[0].title).toBe("Example");
  });
  it("deduplicates tabs by id", () => {
    const block1 = makeBlock("BrowserOpen", "completed", { url: "https://a.com", page_id: "p1", browser_id: "b1" });
    const block2 = makeBlock("BrowserOpen", "completed", { url: "https://a.com", page_id: "p1", browser_id: "b1" });
    const tabs = browserTabsFromBlocks([block1, block2]);
    expect(tabs.length).toBe(1);
  });
});

describe("browserToolEventAppliesToBrowser", () => {
  it("returns false for undefined event", () => {
    expect(browserToolEventAppliesToBrowser(undefined, createEmptyBrowserState("b1"))).toBe(false);
  });
  it("matches by browserId", () => {
    const browser: BrowserState = { ...createEmptyBrowserState("b1") };
    const event = makeEvent({ browserId: "b1" });
    expect(browserToolEventAppliesToBrowser(event, browser)).toBe(true);
  });
  it("matches by URL", () => {
    const browser: BrowserState = { ...createEmptyBrowserState("other"), currentUrl: "https://example.com" };
    const event = makeEvent({ browserId: undefined, pageId: undefined, url: "https://example.com" });
    expect(browserToolEventAppliesToBrowser(event, browser)).toBe(true);
  });
  it("returns true when visual has no IDs", () => {
    const browser: BrowserState = { ...createEmptyBrowserState("b1") };
    const event = makeEvent({ browserId: undefined, pageId: undefined, windowId: undefined, url: undefined });
    expect(browserToolEventAppliesToBrowser(event, browser)).toBe(true);
  });
});

describe("browserToolEventIsPassive", () => {
  it("identifies passive tool events", () => {
    expect(browserToolEventIsPassive(makeEvent({ toolName: "BrowserGetElementMap" }))).toBe(true);
    expect(browserToolEventIsPassive(makeEvent({ toolName: "BrowserExtractContent" }))).toBe(true);
  });
  it("identifies non-passive tool events", () => {
    expect(browserToolEventIsPassive(makeEvent({ toolName: "BrowserOpen" }))).toBe(false);
    expect(browserToolEventIsPassive(makeEvent({ toolName: "BrowserClick" }))).toBe(false);
  });
});

describe("browserToolEventIsAction", () => {
  it("identifies action tools", () => {
    expect(browserToolEventIsAction(makeEvent({ toolName: "BrowserClick" }))).toBe(true);
    expect(browserToolEventIsAction(makeEvent({ toolName: "BrowserType" }))).toBe(true);
    expect(browserToolEventIsAction(makeEvent({ toolName: "BrowserAct" }))).toBe(true);
  });
  it("identifies non-action tools", () => {
    expect(browserToolEventIsAction(makeEvent({ toolName: "BrowserOpen" }))).toBe(false);
    expect(browserToolEventIsAction(makeEvent({ toolName: "BrowserScreenshot" }))).toBe(false);
  });
});

describe("browserHasMeaningfulPage", () => {
  it("returns false for undefined browser", () => {
    expect(browserHasMeaningfulPage(undefined)).toBe(false);
  });
  it("returns false for empty browser", () => {
    expect(browserHasMeaningfulPage(createEmptyBrowserState("b1"))).toBe(false);
  });
  it("returns true for browser with meaningful URL", () => {
    expect(browserHasMeaningfulPage({ ...createEmptyBrowserState("b1"), currentUrl: "https://example.com" })).toBe(true);
  });
});

describe("browserToolShouldHydrateView", () => {
  it("returns true for hydrate-eligible tools", () => {
    expect(browserToolShouldHydrateView(makeEvent({ toolName: "BrowserOpen" }))).toBe(true);
  });
  it("returns false for non-hydrate tools", () => {
    expect(browserToolShouldHydrateView(makeEvent({ toolName: "BrowserListTabs" }))).toBe(false);
  });
});

describe("browserToolShouldPreserveCurrentView", () => {
  it("preserves view for click with target", () => {
    expect(browserToolShouldPreserveCurrentView(makeEvent({ toolName: "BrowserClick", nodeId: "n1" }))).toBe(true);
  });
  it("does not preserve for BrowserOpen", () => {
    expect(browserToolShouldPreserveCurrentView(makeEvent({ toolName: "BrowserOpen" }))).toBe(false);
  });
});

describe("browserToolEventUrl", () => {
  it("prefers final_url over url", () => {
    expect(browserToolEventUrl(makeEvent({ data: { final_url: "https://final.com", url: "https://initial.com" } }))).toBe("https://final.com");
  });
  it("falls back to visual url", () => {
    expect(browserToolEventUrl(makeEvent({ url: "https://fallback.com", data: {} }))).toBe("https://fallback.com");
  });
});

describe("browserMeaningfulToolUrl", () => {
  it("returns empty for non-meaningful URLs", () => {
    expect(browserMeaningfulToolUrl(makeEvent({ url: "about:blank", data: {} }))).toBe("");
  });
  it("returns URL for meaningful ones", () => {
    expect(browserMeaningfulToolUrl(makeEvent({ url: "https://example.com", data: { url: "https://example.com" } }))).toBe("https://example.com");
  });
});

describe("browserToolUrlChanged", () => {
  it("detects URL change", () => {
    const browser = { ...createEmptyBrowserState("b1"), currentUrl: "https://old.com" };
    const event = makeEvent({ data: { url: "https://new.com" } });
    expect(browserToolUrlChanged(event, browser)).toBe(true);
  });
  it("detects same URL", () => {
    const browser = { ...createEmptyBrowserState("b1"), currentUrl: "https://same.com" };
    const event = makeEvent({ data: { url: "https://same.com" } });
    expect(browserToolUrlChanged(event, browser)).toBe(false);
  });
});

describe("browserViewFromToolEvent", () => {
  it("returns undefined when no renderable view", () => {
    expect(browserViewFromToolEvent(makeEvent({ data: {} }))).toBeUndefined();
  });
  it("returns view when data has document_html and url", () => {
    const view = browserViewFromToolEvent(
      makeEvent({ data: { url: "https://example.com", document_html: "<html>test</html>" } }),
    );
    expect(view).toBeDefined();
    expect(view!.url).toBe("https://example.com");
    expect(view!.document_html).toBe("<html>test</html>");
  });
  it("returns view when data has image_data and url", () => {
    const view = browserViewFromToolEvent(
      makeEvent({ data: { url: "https://example.com", image_data: "base64data" } }),
    );
    expect(view).toBeDefined();
    expect(view!.image_data).toBe("base64data");
  });
});

describe("browserToolShouldSyncDisplayedPage", () => {
  it("syncs for navigation tools", () => {
    expect(browserToolShouldSyncDisplayedPage(makeEvent({ toolName: "BrowserOpen" }))).toBe(true);
  });
  it("does not sync for passive tools", () => {
    expect(browserToolShouldSyncDisplayedPage(makeEvent({ toolName: "BrowserScreenshot" }))).toBe(false);
  });
});

describe("browserToolShouldFetchRenderedView", () => {
  it("fetches for navigation tools", () => {
    expect(browserToolShouldFetchRenderedView(makeEvent({ toolName: "BrowserOpen" }))).toBe(true);
  });
  it("does not fetch for passive tools", () => {
    expect(browserToolShouldFetchRenderedView(makeEvent({ toolName: "BrowserScreenshot" }))).toBe(false);
  });
});

describe("browserEffectFromToolAction", () => {
  it("maps tool name to effect", () => {
    expect(browserEffectFromToolAction("BrowserClick", undefined)).toBe("click");
    expect(browserEffectFromToolAction("BrowserType", undefined)).toBe("type");
  });
  it("returns undefined for non-browser tools", () => {
    expect(browserEffectFromToolAction("SearchWeb", undefined)).toBeUndefined();
  });
});
