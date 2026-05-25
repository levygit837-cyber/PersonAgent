/**
 * Unit tests for session-panel/helpers.ts (Slice 1).
 */

import { describe, expect, it, beforeEach } from "vitest";
import type { SessionBrowserView } from "../../../api/client";
import {
  browserCooperationFromView,
  browserPagePanelTabId,
  browserPanelTabId,
  browserPreferredSyncedView,
  browserRenderCache,
  browserRenderCacheByUrl,
  browserRenderCacheKey,
  browserRenderCacheKeyFromView,
  browserRenderUrlCacheKey,
  browserStringValue,
  browserTabComparableUrl,
  browserTabPageIds,
  browserTabsRepresentSamePage,
  browserViewComparableUrl,
  browserViewIsPlaceholder,
  compactBrowserViewForMemory,
  createEmptyBrowserState,
  incrementComposerAnnotationSequence,
  isBrowserCooperationEvent,
  isBrowserTab,
  isMeaningfulBrowserUrl,
  normalizeComparableUrl,
  readBrowserRenderCache,
  recordValue,
  rememberBrowserRenderView,
  resolveBackendUrlPath,
  type BrowserTab,
} from "./helpers/helpers";

describe("helpers", () => {
  // -----------------------------------------------------------------------
  // Utility helpers
  // -----------------------------------------------------------------------

  describe("isMeaningfulBrowserUrl", () => {
    it("returns false for about:blank", () => {
      expect(isMeaningfulBrowserUrl("about:blank")).toBe(false);
    });
    it("returns false for empty string", () => {
      expect(isMeaningfulBrowserUrl("")).toBe(false);
    });
    it("returns true for a real URL", () => {
      expect(isMeaningfulBrowserUrl("https://example.com")).toBe(true);
    });
    it("returns false for undefined", () => {
      expect(isMeaningfulBrowserUrl(undefined)).toBe(false);
    });
  });

  describe("normalizeComparableUrl", () => {
    it("strips trailing slashes", () => {
      expect(normalizeComparableUrl("https://example.com/")).toBe("https://example.com");
    });
    it("trims whitespace", () => {
      expect(normalizeComparableUrl("  https://example.com  ")).toBe("https://example.com");
    });
  });

  describe("browserStringValue", () => {
    it("returns a non-empty string", () => {
      expect(browserStringValue("hello")).toBe("hello");
    });
    it("returns undefined for empty string", () => {
      expect(browserStringValue("")).toBeUndefined();
    });
    it("converts number to string", () => {
      expect(browserStringValue(42)).toBe("42");
    });
    it("returns undefined for null", () => {
      expect(browserStringValue(null)).toBeUndefined();
    });
  });

  describe("recordValue", () => {
    it("returns the object if valid", () => {
      const obj = { a: 1 };
      expect(recordValue(obj)).toBe(obj);
    });
    it("returns empty object for array", () => {
      expect(recordValue([1, 2])).toEqual({});
    });
    it("returns empty object for null", () => {
      expect(recordValue(null)).toEqual({});
    });
  });

  // -----------------------------------------------------------------------
  // Browser state helpers
  // -----------------------------------------------------------------------

  describe("createEmptyBrowserState", () => {
    it("creates a state with default browserId", () => {
      const state = createEmptyBrowserState();
      expect(state.browserId).toMatch(/^browser:\d+$/);
      expect(state.currentUrl).toBe("");
      expect(state.loading).toBe(false);
    });
    it("accepts a custom browserId", () => {
      const state = createEmptyBrowserState("my-browser");
      expect(state.browserId).toBe("my-browser");
    });
  });

  describe("browserPanelTabId", () => {
    it("prepends browser: if missing", () => {
      expect(browserPanelTabId("abc")).toBe("browser:abc");
    });
    it("keeps browser: prefix", () => {
      expect(browserPanelTabId("browser:abc")).toBe("browser:abc");
    });
  });

  describe("browserPagePanelTabId", () => {
    it("joins browserId and pageId", () => {
      expect(browserPagePanelTabId("b1", "p1")).toBe("browser:b1:p1");
    });
  });

  describe("isBrowserTab", () => {
    it("returns true for tab with browser state", () => {
      const tab: BrowserTab = {
        id: "x",
        title: "x",
        closeable: true,
        browser: createEmptyBrowserState(),
      };
      expect(isBrowserTab(tab)).toBe(true);
    });
    it("returns true for tab with browser: id prefix", () => {
      const tab: BrowserTab = { id: "browser:1", title: "Tab", closeable: true };
      expect(isBrowserTab(tab)).toBe(true);
    });
    it("returns false for summary tab", () => {
      const tab: BrowserTab = { id: "summary", title: "Summary", closeable: false };
      expect(isBrowserTab(tab)).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Tab comparison
  // -----------------------------------------------------------------------

  describe("browserTabsRepresentSamePage", () => {
    it("returns true for same id", () => {
      const tab: BrowserTab = { id: "a", title: "A", closeable: true };
      expect(browserTabsRepresentSamePage(tab, tab)).toBe(true);
    });
    it("returns true for tabs with same URL subtitle", () => {
      const left: BrowserTab = {
        id: "a",
        title: "A",
        subtitle: "https://example.com",
        closeable: true,
      };
      const right: BrowserTab = {
        id: "b",
        title: "B",
        subtitle: "https://example.com",
        closeable: true,
      };
      expect(browserTabsRepresentSamePage(left, right)).toBe(true);
    });
    it("returns false for different URLs", () => {
      const left: BrowserTab = {
        id: "a",
        title: "A",
        subtitle: "https://one.com",
        closeable: true,
      };
      const right: BrowserTab = {
        id: "b",
        title: "B",
        subtitle: "https://two.com",
        closeable: true,
      };
      expect(browserTabsRepresentSamePage(left, right)).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // View helpers
  // -----------------------------------------------------------------------

  describe("browserViewIsPlaceholder", () => {
    it("returns true for undefined", () => {
      expect(browserViewIsPlaceholder(undefined)).toBe(true);
    });
    it("returns true for empty view", () => {
      expect(
        browserViewIsPlaceholder({ can_capture: false } as SessionBrowserView),
      ).toBe(true);
    });
    it("returns false if has image_data", () => {
      expect(
        browserViewIsPlaceholder({ can_capture: false, image_data: "abc" } as SessionBrowserView),
      ).toBe(false);
    });
  });

  describe("browserPreferredSyncedView", () => {
    it("returns synced if existing is undefined", () => {
      const synced = { url: "https://example.com", can_capture: true } as SessionBrowserView;
      expect(browserPreferredSyncedView(undefined, synced)).toBe(synced);
    });
    it("returns existing if synced is undefined", () => {
      const existing = { url: "https://example.com" } as SessionBrowserView;
      expect(browserPreferredSyncedView(existing, undefined)).toBe(existing);
    });
    it("prefers existing over placeholder synced at same URL", () => {
      const existing = { url: "https://example.com", can_capture: true, image_data: "img" } as SessionBrowserView;
      const synced = { url: "https://example.com", can_capture: false } as SessionBrowserView;
      expect(browserPreferredSyncedView(existing, synced)).toBe(existing);
    });
  });

  // -----------------------------------------------------------------------
  // Compact view for memory
  // -----------------------------------------------------------------------

  describe("compactBrowserViewForMemory", () => {
    it("strips html, document_html, and image_data", () => {
      const view = {
        url: "https://example.com",
        html: "<html>full</html>",
        document_html: "<html>doc</html>",
        image_data: "base64...",
      } as SessionBrowserView;
      const compact = compactBrowserViewForMemory(view);
      expect(compact.html).toBe("");
      expect(compact.document_html).toBe("");
      expect(compact.image_data).toBe("");
      expect(compact.url).toBe("https://example.com");
    });
  });

  // -----------------------------------------------------------------------
  // Resolve backend URL path
  // -----------------------------------------------------------------------

  describe("resolveBackendUrlPath", () => {
    it("returns empty for undefined value", () => {
      expect(resolveBackendUrlPath("http://localhost:8000")).toBe("");
    });
    it("returns absolute URLs unchanged", () => {
      expect(resolveBackendUrlPath("http://localhost", "https://cdn.com/img.png")).toBe("https://cdn.com/img.png");
    });
    it("resolves relative path against base", () => {
      expect(resolveBackendUrlPath("http://localhost:8000", "/api/data")).toBe("http://localhost:8000/api/data");
    });
  });

  // -----------------------------------------------------------------------
  // Render cache
  // -----------------------------------------------------------------------

  describe("browserRenderCacheKey", () => {
    it("produces a deterministic key", () => {
      const key = browserRenderCacheKey("b1", "https://example.com", { width: 1024, height: 720 });
      expect(key).toContain("b1");
      expect(key).toContain("https://example.com");
    });
  });

  describe("rememberBrowserRenderView / readBrowserRenderCache", () => {
    beforeEach(() => {
      browserRenderCache.clear();
      browserRenderCacheByUrl.clear();
    });

    it("stores and retrieves a view", () => {
      const view = {
        url: "https://example.com",
        browser_id: "b1",
        viewport_width: 1024,
        viewport_height: 720,
        image_data: "img",
      } as SessionBrowserView;
      rememberBrowserRenderView("b1", view);
      const cached = readBrowserRenderCache("b1", "https://example.com", { width: 1024, height: 720 });
      expect(cached).toBeDefined();
      expect(cached?.render_cache_status).toBe("hit");
    });
  });

  // -----------------------------------------------------------------------
  // Type guard
  // -----------------------------------------------------------------------

  describe("isBrowserCooperationEvent", () => {
    it("returns true for valid event", () => {
      expect(isBrowserCooperationEvent({ kind: "proposal" })).toBe(true);
    });
    it("returns false for null", () => {
      expect(isBrowserCooperationEvent(null)).toBe(false);
    });
    it("returns false for array", () => {
      expect(isBrowserCooperationEvent([{ kind: "x" }])).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // Composer annotation sequence
  // -----------------------------------------------------------------------

  describe("incrementComposerAnnotationSequence", () => {
    it("returns an incrementing number", () => {
      const a = incrementComposerAnnotationSequence();
      const b = incrementComposerAnnotationSequence();
      expect(b).toBe(a + 1);
    });
  });
});
