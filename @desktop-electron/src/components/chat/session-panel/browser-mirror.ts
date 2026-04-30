import type { SessionBrowserElement } from "../../../api/client";

export function browserMirrorSrcDoc(
  html: string,
  currentUrl: string,
  browserId: string,
  elementMap: SessionBrowserElement[],
  cooperationEnabled = false,
) {
  const sanitizedHtml = sanitizeBrowserMirrorHtml(html);
  const scriptNonce = createCspNonce();
  const base = `<base href="${escapeHtmlAttribute(currentUrl)}">`;
  const csp = [
    "default-src 'none'",
    "img-src http: https: data: blob:",
    "style-src http: https: data: blob: 'unsafe-inline'",
    `script-src 'nonce-${scriptNonce}'`,
    "font-src http: https: data:",
    "frame-src 'none'",
    "object-src 'none'",
    "form-action 'none'",
    "base-uri http: https:",
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">`;
  const overlayStyle = `<style>
	html[data-pa-browser-mode="annotate"],
	html[data-pa-browser-mode="annotate"] body,
	html[data-pa-browser-mode="annotate"] * {
	  cursor: crosshair !important;
	}
	.pa-browser-inspect-target {
	  scroll-margin: 6px !important;
	}
	.pa-inspector-fill {
	  position: fixed !important;
	  z-index: 2147483646 !important;
	  box-sizing: border-box !important;
	  border: 2px solid #2296ff !important;
	  border-radius: var(--pa-inspector-radius, 3px) !important;
	  background: rgba(34, 150, 255, 0.18) !important;
	  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14), 0 0 0 1px rgba(34, 150, 255, 0.28) !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: left 110ms ease, top 110ms ease, width 110ms ease, height 110ms ease, border-radius 110ms ease, opacity 100ms ease !important;
	}
		.pa-inspector-fill.is-hidden {
		  opacity: 0 !important;
		}
		.pa-inspector-tooltip {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  left: 0;
	  top: 0;
	  min-width: 176px !important;
	  max-width: min(240px, calc(100vw - 16px)) !important;
	  border: 1px solid rgba(96, 165, 250, 0.32) !important;
	  border-radius: 10px !important;
	  background: rgba(9, 17, 31, 0.96) !important;
	  color: #e5eefb !important;
	  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
	  font: 500 11px/1.25 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  letter-spacing: 0 !important;
	  padding: 8px !important;
	  pointer-events: none !important;
	  opacity: 1 !important;
	  transform: translate3d(0, 0, 0) !important;
	  transition: opacity 100ms ease, transform 130ms ease !important;
	}
	.pa-inspector-tooltip.is-hidden {
	  opacity: 0 !important;
	}
	.pa-inspector-title,
	.pa-inspector-row {
	  display: grid !important;
	  grid-template-columns: 52px minmax(0, 1fr) !important;
	  gap: 8px !important;
	  align-items: center !important;
	}
	.pa-inspector-title {
	  margin-bottom: 5px !important;
	}
	.pa-inspector-tag {
	  display: inline-flex !important;
	  min-width: 0 !important;
	  justify-content: center !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.13) !important;
	  color: #f8fafc !important;
	  font-weight: 700 !important;
	  padding: 2px 6px !important;
	  text-transform: lowercase !important;
	}
	.pa-inspector-value {
	  min-width: 0 !important;
	  overflow: hidden !important;
	  text-overflow: ellipsis !important;
	  white-space: nowrap !important;
	}
	.pa-inspector-label {
	  color: #8ea1b8 !important;
	  font-weight: 600 !important;
	}
	.pa-selection-toolbar {
	  position: fixed !important;
	  z-index: 2147483647 !important;
	  display: flex !important;
	  align-items: center !important;
	  gap: 6px !important;
	  border: 1px solid rgba(96, 165, 250, 0.28) !important;
	  border-radius: 999px !important;
	  background: rgba(10, 18, 32, 0.96) !important;
	  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.28) !important;
	  padding: 4px !important;
	  pointer-events: auto !important;
	}
	.pa-selection-toolbar.is-hidden {
	  display: none !important;
	}
	.pa-selection-toolbar button {
	  border: 0 !important;
	  border-radius: 999px !important;
	  background: rgba(34, 150, 255, 0.16) !important;
	  color: #dbeafe !important;
	  cursor: pointer !important;
	  font: 600 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  padding: 7px 10px !important;
	}
	[data-pa-comment-count] {
	  outline: 1px solid rgba(249, 115, 22, 0.58) !important;
	  outline-offset: 2px !important;
	  box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.12) !important;
	}
	.pa-comment-anchor {
	  position: relative !important;
	}
	.pa-comment-marker {
	  position: absolute !important;
	  z-index: 2147483647 !important;
	  top: -9px !important;
	  right: -9px !important;
	  display: inline-grid !important;
	  min-width: 18px !important;
	  height: 18px !important;
	  place-items: center !important;
	  border: 1px solid rgba(255, 255, 255, 0.72) !important;
	  border-radius: 999px !important;
	  background: #f97316 !important;
	  color: #111827 !important;
	  font: 700 11px/1 Inter, ui-sans-serif, system-ui, sans-serif !important;
	  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.22) !important;
	  pointer-events: none !important;
	}
	</style>`;
 const script = `<script nonce="${escapeHtmlAttribute(scriptNonce)}">
	(() => {
	  const browserId = ${JSON.stringify(browserId)};
	  const knownElements = ${scriptJson(
      elementMap
        .filter((element) => element.node_id && element.selector)
        .slice(0, 500)
        .map((element) => ({
          node_id: element.node_id,
          role: element.role || "",
          selector: element.selector || "",
          frame_id: element.frame_id || "main",
          shadow_path: element.shadow_path || [],
        })),
    )};
	  let mode = "browse";
	  let cooperationEnabled = ${JSON.stringify(cooperationEnabled)};
	  let annotationCounts = {};
	  let selectedNodeId = "";
	  const interactiveSelector = "a[href],button,input,textarea,select,label,summary,[role='button'],[role='link'],[role='menuitem'],[role='tab'],[role='checkbox'],[role='radio'],[contenteditable='true']";
	  const inspectableSelector = [
	    interactiveSelector,
	    "form,[role],h1,h2,h3,h4,h5,h6,p,li,article,section,main,nav,header,footer,div,span,img,svg,canvas"
	  ].join(",");
	  const ignoredTags = new Set(["HTML", "BODY", "HEAD", "SCRIPT", "STYLE", "META", "LINK", "BASE", "TITLE", "NOSCRIPT", "TEMPLATE"]);
	  const voidTags = new Set(["AREA", "BASE", "BR", "COL", "EMBED", "HR", "IMG", "INPUT", "LINK", "META", "PARAM", "SOURCE", "TRACK", "WBR"]);
	  let activeTarget = null;
		  let highlightOverlay = null;
		  let tooltip = null;
	  let selectionToolbar = null;
	  let lastSelectionMetadata = null;
	  let pendingMouse = null;
	  let hoverFrame = 0;
	  let eventBuffer = [];
	  let eventFlushTimer = 0;
	  let mutationTimer = 0;
	  let resizeTimer = 0;
	  let scrollTimer = 0;
	  let selectionTimer = 0;
	  let intersectionTimer = 0;

	  const eventId = () => "bev_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
	  const sendEventBatch = () => {
	    if (!eventBuffer.length) return;
	    const events = eventBuffer.splice(0, 40);
	    window.parent.postMessage({ type: "personagent-session-browser:event-batch", browserId, events }, "*");
	  };
	  const scheduleEventFlush = () => {
	    if (eventFlushTimer) return;
	    eventFlushTimer = window.setTimeout(() => {
	      eventFlushTimer = 0;
	      sendEventBatch();
	    }, 350);
	  };
	  const isSensitiveElement = (element) => {
	    if (!element || !element.getAttribute) return false;
	    const text = [
	      element.getAttribute("type"),
	      element.getAttribute("autocomplete"),
	      element.getAttribute("name"),
	      element.getAttribute("id"),
	      element.getAttribute("aria-label"),
	      element.getAttribute("placeholder")
	    ].join(" ");
	    return /(password|passcode|token|secret|api[_-]?key|credit|card|cc-|cc_|cvv|cvc|expiry|email)/i.test(text);
	  };
	  const compactTarget = (element) => {
	    if (!element || !element.getAttribute) return {};
	    const metadata = elementMetadata(element);
	    const fieldLabel = trimText(
	      element.getAttribute("aria-label") ||
	        element.getAttribute("placeholder") ||
	        element.getAttribute("name") ||
	        element.getAttribute("id") ||
	        "",
	      120,
	    );
	    const isField = ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName);
	    return {
	      node_id: metadata.node_id,
	      role: metadata.role,
	      tag: metadata.tag,
	      text: isSensitiveElement(element) ? "[REDACTED]" : isField ? fieldLabel : trimText(metadata.text, 120),
	      label: fieldLabel || undefined,
	      selector: metadata.selector,
	      href: metadata.href,
	      name: metadata.name,
	      input_type: metadata.input_type,
	      form_method: metadata.form_method,
	      form_action: metadata.form_action,
	      bounds: metadata.bounds,
	      autocomplete: element.getAttribute("autocomplete") || undefined,
	      placeholder: element.getAttribute("placeholder") || undefined,
	      aria_label: element.getAttribute("aria-label") || undefined,
	    };
	  };
	  const visiblePrimaryButtons = () => Array.from(document.querySelectorAll("button,input[type='submit'],a[href],[role='button']"))
	    .filter((element) => {
	      const rect = element.getBoundingClientRect();
	      if (rect.width < 8 || rect.height < 8 || rect.bottom < 0 || rect.right < 0 || rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
	      return /submit|save|apply|continue|finish|finalizar|checkout|buy|pay|next|voltar|back|cancel|confirm/i.test(elementText(element));
	    })
	    .slice(0, 16)
	    .map((element) => trimText(elementText(element), 80))
	    .filter(Boolean);
	  const focusedFieldLabel = () => {
	    if (!document.activeElement || document.activeElement === document.body) return null;
	    const target = compactTarget(document.activeElement);
	    return target.label || target.placeholder || target.name || target.role || null;
	  };
	  const pageState = () => ({
	    modal_open: Boolean(document.querySelector("[role='dialog'],dialog,[aria-modal='true']")),
	    focused_field: focusedFieldLabel(),
	    visible_primary_buttons: visiblePrimaryButtons(),
	    route: window.location.pathname || "/",
	    scroll: {
	      x: Math.round(window.scrollX || document.documentElement.scrollLeft || 0),
	      y: Math.round(window.scrollY || document.documentElement.scrollTop || 0),
	    },
	  });
	  const valuePayload = (element) => {
	    if (!element || !("value" in element)) return {};
	    if (isSensitiveElement(element)) {
	      return {
	        value: "[REDACTED]",
	        value_redacted: true,
	        value_char_count: String(element.value || "").length,
	        page_state: pageState(),
	      };
	    }
	    const value = String(element.value || "");
	    return {
	      value: {
	        preview: trimText(value, 120),
	        char_count: value.length,
	        hash: stableHash(value),
	      },
	      page_state: pageState(),
	    };
	  };
	  const trackEvent = (kind, options = {}) => {
	    if (!cooperationEnabled) return;
	    const target = options.targetElement ? compactTarget(options.targetElement) : (options.target || {});
	    eventBuffer.push({
	      event_id: eventId(),
	      kind,
	      raw_kind: kind,
	      source: "user",
	      channel: "event",
	      trace_role: "user",
	      visibility: options.visibility || (["click", "input", "change", "submit", "route_change", "mutation"].includes(kind) ? "useful" : "raw"),
	      timestamp: new Date().toISOString(),
	      url: window.location.href || document.baseURI || "",
	      target,
	      payload: options.payload || {},
	      coordinates: options.coordinates || (target && target.bounds ? { bounds: target.bounds } : {}),
	      trace_effect: options.traceEffect || (kind === "scroll" ? "scroll" : ["input", "change", "keydown"].includes(kind) ? "type" : kind === "click" ? "click" : "highlight"),
	      correlation_id: options.correlationId || "",
	      importance: options.importance || (["click", "input", "change", "submit", "route_change", "mutation"].includes(kind) ? "high" : "low"),
	      semantic_label: options.semanticLabel || "",
	    });
	    if (eventBuffer.length >= 20) sendEventBatch();
	    else scheduleEventFlush();
	  };
	  const coalescedMutationEvent = () => {
	    if (mutationTimer || !cooperationEnabled) return;
	    mutationTimer = window.setTimeout(() => {
	      mutationTimer = 0;
	      trackEvent("mutation", { payload: { page_state: pageState() }, importance: "high", semanticLabel: "page content changed" });
	    }, 600);
	  };
	  const coalescedResizeEvent = () => {
	    if (resizeTimer || !cooperationEnabled) return;
	    resizeTimer = window.setTimeout(() => {
	      resizeTimer = 0;
	      trackEvent("resize", { payload: { width: window.innerWidth, height: window.innerHeight, page_state: pageState() }, importance: "low" });
	    }, 700);
	  };
	  const coalescedScrollEvent = () => {
	    if (scrollTimer || !cooperationEnabled) return;
	    scrollTimer = window.setTimeout(() => {
	      scrollTimer = 0;
	      trackEvent("scroll", {
	        payload: {
	          scroll_x: Math.round(window.scrollX || document.documentElement.scrollLeft || 0),
	          scroll_y: Math.round(window.scrollY || document.documentElement.scrollTop || 0),
	          page_state: pageState(),
	        },
	        importance: "low",
	        semanticLabel: "scrolled the page",
	      });
	    }, 250);
	  };
	  const coalescedSelectionEvent = () => {
	    if (selectionTimer || !cooperationEnabled) return;
	    selectionTimer = window.setTimeout(() => {
	      selectionTimer = 0;
	      const metadata = selectionMetadata();
	      trackEvent("selectionchange", {
	        target: metadata
	          ? {
	              node_id: metadata.node_id,
	              selector: metadata.selector,
	              role: metadata.role,
	              tag: metadata.tag,
	              bounds: metadata.bounds,
	            }
	          : {},
	        payload: metadata
	          ? {
	              selected_text: {
	                char_count: String(metadata.text || "").length,
	                hash: stableHash(metadata.text || ""),
	              },
	              page_state: pageState(),
	            }
	          : { selected_text: null, page_state: pageState() },
	        importance: "low",
	      });
	    }, 500);
	  };
	  const coalescedIntersectionEvent = (entries) => {
	    if (intersectionTimer || !cooperationEnabled) return;
	    intersectionTimer = window.setTimeout(() => {
	      intersectionTimer = 0;
	      const visibleCount = Array.from(entries || []).filter((entry) => entry.isIntersecting).length;
	      trackEvent("intersection", {
	        payload: { visible_count: visibleCount, page_state: pageState() },
	        importance: "low",
	      });
	    }, 800);
	  };

	  const applyMode = (nextMode) => {
	    mode = nextMode === "annotate" ? nextMode : "browse";
	    document.documentElement.setAttribute("data-pa-browser-mode", mode);
	    if (mode === "browse") clearHover();
	  };

	  const send = (url) => {
	    if (!url) return;
	    trackEvent("route_change", {
	      payload: { url, from_url: window.location.href || document.baseURI || "", page_state: pageState() },
	      importance: "high",
	      semanticLabel: "navigated to " + url,
	    });
	    window.parent.postMessage({ type: "personagent-session-browser:navigate", browserId, url }, "*");
	  };
	  const sendElement = (element) => {
	    if (!element) return;
	    const metadata = elementMetadata(element);
	    if (!metadata.node_id) return;
	    window.parent.postMessage({
	      type: "personagent-session-browser:element",
	      browserId,
	      nodeId: metadata.node_id,
	      element: metadata,
	    }, "*");
	  };
	  const sendElementAction = (nodeId, action) => {
	    if (!nodeId) return;
	    window.parent.postMessage({ type: "personagent-session-browser:element-action", browserId, nodeId, action }, "*");
	  };
	  const sendTextSelection = (selection) => {
	    if (!selection || !selection.text) return;
	    window.parent.postMessage({
	      type: "personagent-session-browser:text-selection",
	      browserId,
	      selection,
	    }, "*");
	  };
	  const cssEscape = (value) => {
	    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
	    return String(value).replace(/["\\\\]/g, "\\\\$&");
	  };
	  const selectedTarget = () => {
	    if (!selectedNodeId) return null;
	    return document.querySelector('[data-pa-node-id="' + cssEscape(selectedNodeId) + '"]');
	  };
	  const trimText = (value, limit) => String(value || "").replace(/\\s+/g, " ").trim().slice(0, limit);
	  const elementText = (element) => {
	    if (!element || !element.getAttribute) return "";
	    const aria = element.getAttribute("aria-label") || element.getAttribute("alt") || element.getAttribute("title");
	    if (aria) return trimText(aria, 180);
	    const tag = element.tagName;
	    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
	      return trimText(element.value || element.getAttribute("placeholder") || element.getAttribute("name") || "", 180);
	    }
	    return trimText(element.innerText || element.textContent || "", 180);
	  };
	  const roleFor = (element) => {
	    if (!element || !element.getAttribute) return "element";
	    const explicitRole = element.getAttribute("role");
	    if (explicitRole) return explicitRole;
	    const tag = element.tagName.toLowerCase();
	    if (tag === "a") return "link";
	    if (tag === "button") return "button";
	    if (["input", "textarea", "select"].includes(tag)) return "field";
	    if (/^h[1-6]$/.test(tag)) return "heading";
	    return tag;
	  };
	  const stableHash = (value) => {
	    let hash = 2166136261;
	    const text = String(value || "");
	    for (let index = 0; index < text.length; index += 1) {
	      hash ^= text.charCodeAt(index);
	      hash = Math.imul(hash, 16777619);
	    }
	    return (hash >>> 0).toString(36);
	  };
	  const cssPath = (element) => {
	    if (!element || !element.tagName) return "";
	    if (element.id) return "#" + cssEscape(element.id);
	    const parts = [];
	    let node = element;
	    while (node && node.nodeType === 1 && node !== document.documentElement) {
	      const tag = node.tagName.toLowerCase();
	      if (node.id) {
	        parts.unshift(tag + "#" + cssEscape(node.id));
	        break;
	      }
	      let nth = 1;
	      let sibling = node;
	      while ((sibling = sibling.previousElementSibling)) {
	        if (sibling.tagName === node.tagName) nth += 1;
	      }
	      parts.unshift(tag + ":nth-of-type(" + nth + ")");
	      if (node.parentElement === document.body) break;
	      node = node.parentElement;
	    }
	    return parts.join(" > ");
	  };
	  const ensureNodeId = (element) => {
	    if (!element || !element.setAttribute) return "";
	    const existing = element.getAttribute("data-pa-node-id");
	    if (existing) return existing;
	    const signature = [cssPath(element), roleFor(element), elementText(element).slice(0, 90)].join("|");
	    const nodeId = "pa_dom_" + stableHash(signature);
	    element.setAttribute("data-pa-node-id", nodeId);
	    return nodeId;
	  };
	  const applyKnownNodeIds = () => {
	    for (const item of knownElements) {
	      if (!item || !item.node_id || !item.selector) continue;
	      if (item.frame_id && item.frame_id !== "main") continue;
	      if (Array.isArray(item.shadow_path) && item.shadow_path.length) continue;
	      try {
	        const element = document.querySelector(item.selector);
	        if (!element) continue;
	        element.setAttribute("data-pa-node-id", item.node_id);
	        if (item.role) element.setAttribute("data-pa-role", item.role);
	      } catch {
	        // Selector fidelity is best-effort for static browser mirrors.
	      }
	    }
	  };
	  const canContainMarker = (element) => {
	    if (!element || !element.tagName) return false;
	    return !voidTags.has(element.tagName);
	  };
	  const boundsFor = (element) => {
	    const rect = element.getBoundingClientRect();
	    return {
	      x: Math.round(rect.left),
	      y: Math.round(rect.top),
	      width: Math.round(rect.width),
	      height: Math.round(rect.height),
	    };
	  };
	  const elementMetadata = (element) => {
	    const tag = element.tagName.toLowerCase();
	    const style = window.getComputedStyle(element);
	    const form = tag === "form" ? element : element.closest("form");
	    const href = tag === "a" && element.getAttribute("href")
	      ? new URL(element.getAttribute("href"), document.baseURI).href
	      : undefined;
	    const formAction = form && form.getAttribute("action")
	      ? new URL(form.getAttribute("action"), document.baseURI).href
	      : undefined;
	    return {
	      node_id: ensureNodeId(element),
	      role: roleFor(element),
	      tag,
	      text: elementText(element),
	      selector: cssPath(element),
	      href,
	      name: element.getAttribute("name") || element.getAttribute("aria-label") || undefined,
	      input_type: tag === "input" ? String(element.getAttribute("type") || "text").toLowerCase() : undefined,
	      form_method: form ? String(form.getAttribute("method") || "get").toLowerCase() : undefined,
	      form_action: formAction,
	      bounds: boundsFor(element),
	      visible: true,
	      color: style.color,
	      background: style.backgroundColor,
	      display: style.display,
	      position: style.position,
	      padding: trimText(style.padding, 80),
	      margin: trimText(style.margin, 80),
	      radius: trimText(style.borderRadius, 80),
	      font: trimText(style.fontSize + " " + style.fontFamily, 96),
	    };
	  };
	  const isVisibleCandidate = (element) => {
	    if (!element || !element.tagName || ignoredTags.has(element.tagName)) return false;
	    if (element.closest && element.closest(".pa-inspector-tooltip, .pa-inspector-fill, .pa-selection-toolbar, .pa-comment-marker")) return false;
	    const rect = element.getBoundingClientRect();
	    if (rect.width < 4 || rect.height < 4) return false;
	    const style = window.getComputedStyle(element);
	    if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity || "1") === 0) return false;
	    return true;
	  };
	  const containsPoint = (element, x, y) => {
	    const rect = element.getBoundingClientRect();
	    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
	  };
	  const normalizeCandidate = (element, x, y) => {
	    if (!isVisibleCandidate(element)) return null;
	    if (["PATH", "USE", "G"].includes(element.tagName)) {
	      const svg = element.closest ? element.closest("svg") : null;
	      if (svg && isVisibleCandidate(svg) && containsPoint(svg, x, y)) return svg;
	    }
	    return element;
	  };
	  const candidateScore = (element, x, y) => {
	    const rect = element.getBoundingClientRect();
	    const area = rect.width * rect.height;
	    const viewportArea = Math.max(1, window.innerWidth * window.innerHeight);
	    const centerDistance = Math.hypot(x - (rect.left + rect.width / 2), y - (rect.top + rect.height / 2));
	    const interactive = element.matches && element.matches(interactiveSelector);
	    const semantic = element.matches && element.matches("form,[role],h1,h2,h3,h4,h5,h6,p,li,article,section,main,nav,header,footer");
	    const text = elementText(element);
	    let depth = 0;
	    let parent = element.parentElement;
	    while (parent && parent !== document.body && depth < 24) {
	      depth += 1;
	      parent = parent.parentElement;
	    }
	    let score = Math.log(area + 1) * 12 + Math.min(centerDistance / 4, 100) - Math.min(depth * 2, 48);
	    if (interactive) score -= 12;
	    if (semantic) score -= 6;
	    if (text) score -= 14;
	    if (area > viewportArea * 0.65 && !interactive) score += 160;
	    if (area < 24) score += 30;
	    if (mode === "annotate" && area > viewportArea * 0.18 && !interactive) score += 70;
	    return score;
	  };
	  const targetFromPoint = (x, y) => {
	    const elements = typeof document.elementsFromPoint === "function"
	      ? document.elementsFromPoint(x, y)
	      : [document.elementFromPoint(x, y)].filter(Boolean);
	    const seen = new Set();
	    const candidates = [];
	    for (const raw of elements) {
	      const candidate = normalizeCandidate(raw, x, y);
	      if (!candidate || seen.has(candidate)) continue;
	      seen.add(candidate);
	      candidates.push(candidate);
	    }
	    if (!candidates.length) return null;
	    candidates.sort((left, right) => candidateScore(left, x, y) - candidateScore(right, x, y));
	    return candidates[0];
	  };
	  const createTooltip = () => {
	    if (tooltip) return tooltip;
	    tooltip = document.createElement("div");
	    tooltip.className = "pa-inspector-tooltip is-hidden";
	    (document.body || document.documentElement).appendChild(tooltip);
	    return tooltip;
	  };
		  const createHighlightOverlay = () => {
		    if (highlightOverlay) return highlightOverlay;
		    highlightOverlay = document.createElement("div");
		    highlightOverlay.className = "pa-inspector-fill is-hidden";
		    (document.body || document.documentElement).appendChild(highlightOverlay);
		    return highlightOverlay;
		  };
		  const positionHighlightOverlay = (element) => {
	    const overlay = createHighlightOverlay();
	    if (!element) {
	      overlay.classList.add("is-hidden");
	      return;
	    }
	    const rect = element.getBoundingClientRect();
	    const style = window.getComputedStyle(element);
	    overlay.style.left = Math.round(rect.left) + "px";
	    overlay.style.top = Math.round(rect.top) + "px";
	    overlay.style.width = Math.round(rect.width) + "px";
	    overlay.style.height = Math.round(rect.height) + "px";
	    overlay.style.setProperty("--pa-inspector-radius", style.borderRadius && style.borderRadius !== "0px" ? style.borderRadius : "2px");
	    overlay.classList.remove("is-hidden");
	  };
	  const appendTooltipRow = (root, label, value, title) => {
	    if (!value) return;
	    const row = document.createElement("div");
	    row.className = title ? "pa-inspector-title" : "pa-inspector-row";
	    const labelNode = document.createElement("span");
	    labelNode.className = title ? "pa-inspector-tag" : "pa-inspector-label";
	    labelNode.textContent = label;
	    const valueNode = document.createElement("span");
	    valueNode.className = "pa-inspector-value";
	    valueNode.textContent = value;
	    row.appendChild(labelNode);
	    row.appendChild(valueNode);
	    root.appendChild(row);
	  };
	  const isTransparentColor = (value) => {
	    const normalized = String(value || "").replace(/\\s+/g, "").toLowerCase();
	    return !normalized || normalized === "transparent" || normalized === "rgba(0,0,0,0)";
	  };
	  const compactColor = (value) => String(value || "").replace(/\\s+/g, "");
	  const compactCss = (metadata) => {
	    const values = [
	      metadata.display,
	      metadata.position && metadata.position !== "static" ? metadata.position : "",
	      metadata.radius && metadata.radius !== "0px" ? "r " + metadata.radius : "",
	    ].filter(Boolean);
	    return values.join(" · ");
	  };
	  const compactColors = (metadata) => {
	    const values = [compactColor(metadata.color)];
	    if (!isTransparentColor(metadata.background)) values.push(compactColor(metadata.background));
	    return values.filter(Boolean).join(" / ");
	  };
		  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
		  const tooltipPositionFor = (element, width, height) => {
	    const rect = element.getBoundingClientRect();
	    const margin = 8;
	    const gap = 8;
	    const viewportWidth = window.innerWidth;
	    const viewportHeight = window.innerHeight;
	    const centerTop = clamp(rect.top + rect.height / 2 - height / 2, margin, Math.max(margin, viewportHeight - height - margin));
	    const centerLeft = clamp(rect.left + rect.width / 2 - width / 2, margin, Math.max(margin, viewportWidth - width - margin));
	    const candidates = [];
	    if (viewportWidth - rect.right >= width + gap + margin) candidates.push({ left: rect.right + gap, top: centerTop });
	    if (rect.left >= width + gap + margin) candidates.push({ left: rect.left - width - gap, top: centerTop });
	    if (viewportHeight - rect.bottom >= height + gap + margin) candidates.push({ left: centerLeft, top: rect.bottom + gap });
	    if (rect.top >= height + gap + margin) candidates.push({ left: centerLeft, top: rect.top - height - gap });
	    if (candidates.length) return candidates[0];
	    return {
	      left: clamp(rect.right + gap, margin, Math.max(margin, viewportWidth - width - margin)),
	      top: clamp(rect.bottom + gap, margin, Math.max(margin, viewportHeight - height - margin)),
	    };
	  };
	  const showTooltip = (element, x, y) => {
	    const root = createTooltip();
	    const metadata = elementMetadata(element);
	    root.replaceChildren();
	    appendTooltipRow(
	      root,
	      metadata.tag || "node",
	      metadata.role + " · " + metadata.bounds.width + "x" + metadata.bounds.height,
	      true
	    );
	    appendTooltipRow(root, "CSS", compactCss(metadata));
	    appendTooltipRow(root, "Color", compactColors(metadata));
	    const width = Math.min(root.offsetWidth || 192, window.innerWidth - 16);
	    const height = Math.min(root.offsetHeight || 72, window.innerHeight - 16);
	    const position = tooltipPositionFor(element, width, height);
	    root.style.setProperty("left", Math.round(position.left) + "px", "important");
	    root.style.setProperty("top", Math.round(position.top) + "px", "important");
	    root.style.setProperty("transform", "translate3d(0, 0, 0)", "important");
	    root.classList.remove("is-hidden");
	  };
	  const hideTooltip = () => {
	    if (tooltip) tooltip.classList.add("is-hidden");
	  };
	  const setActiveTarget = (element, x, y) => {
	    if (activeTarget === element) {
	      if (element) positionHighlightOverlay(element);
	      if (element) showTooltip(element, x, y);
	      return;
	    }
	    if (activeTarget) activeTarget.classList.remove("pa-browser-inspect-target");
	    activeTarget = element;
	    if (activeTarget) {
	      ensureNodeId(activeTarget);
	      activeTarget.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(activeTarget);
	      showTooltip(activeTarget, x, y);
	    } else {
	      positionHighlightOverlay(null);
	      hideTooltip();
	    }
	  };
	  const scheduleHover = (event) => {
	    if (mode !== "annotate") return;
	    pendingMouse = { x: event.clientX, y: event.clientY };
	    if (hoverFrame) return;
	    hoverFrame = window.requestAnimationFrame(() => {
	      hoverFrame = 0;
	      if (!pendingMouse) return;
	      const target = targetFromPoint(pendingMouse.x, pendingMouse.y);
	      setActiveTarget(target, pendingMouse.x, pendingMouse.y);
	    });
	  };
	  const clearHover = () => {
	    pendingMouse = null;
	    if (activeTarget) activeTarget.classList.remove("pa-browser-inspect-target");
	    activeTarget = null;
	    const selected = mode === "annotate" ? selectedTarget() : null;
	    if (selected) {
	      selected.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(selected);
	    } else {
	      positionHighlightOverlay(null);
	    }
	    hideTooltip();
	  };
	  const indexAnnotatableElements = () => {
	    let indexed = 0;
	    for (const element of document.querySelectorAll(inspectableSelector)) {
	      if (indexed >= 1600) break;
	      if (!isVisibleCandidate(element)) continue;
	      ensureNodeId(element);
	      indexed += 1;
	    }
	  };
	  const applyAnnotationMarkers = () => {
	    indexAnnotatableElements();
	    for (const marker of document.querySelectorAll(".pa-comment-marker")) marker.remove();
	    for (const marked of document.querySelectorAll("[data-pa-comment-count]")) {
	      marked.removeAttribute("data-pa-comment-count");
	      marked.classList.remove("pa-comment-anchor");
	    }
	    for (const nodeId of Object.keys(annotationCounts)) {
	      const element = document.querySelector('[data-pa-node-id="' + cssEscape(nodeId) + '"]');
	      if (!element) continue;
	      const count = String(annotationCounts[nodeId]);
	      element.setAttribute("data-pa-comment-count", count);
	      if (!canContainMarker(element) || element.querySelector(":scope > .pa-comment-marker")) continue;
	      element.classList.add("pa-comment-anchor");
	      const marker = document.createElement("span");
	      marker.className = "pa-comment-marker";
	      marker.textContent = count;
	      element.appendChild(marker);
	    }
	    const selected = mode === "annotate" ? selectedTarget() : null;
	    if (!activeTarget && selected) {
	      selected.classList.add("pa-browser-inspect-target");
	      positionHighlightOverlay(selected);
	    }
	  };
	  const selectionElement = (selection) => {
	    if (!selection || selection.rangeCount === 0) return null;
	    const range = selection.getRangeAt(0);
	    let node = range.commonAncestorContainer;
	    if (node && node.nodeType !== 1) node = node.parentElement;
	    return node && node.nodeType === 1 ? node : null;
	  };
	  const selectionOffsets = (element, range, selectedText) => {
	    if (!element || !range) return {};
	    try {
	      const prefixRange = document.createRange();
	      prefixRange.selectNodeContents(element);
	      prefixRange.setEnd(range.startContainer, range.startOffset);
	      const start = prefixRange.toString().length;
	      return { start_offset: start, end_offset: start + selectedText.length };
	    } catch {
	      return {};
	    }
	  };
	  const selectionMetadata = () => {
	    const selection = window.getSelection();
	    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
	    const text = trimText(selection.toString(), 2000);
	    if (!text) return null;
	    const range = selection.getRangeAt(0);
	    const rect = range.getBoundingClientRect();
	    if (!rect || rect.width < 2 || rect.height < 2) return null;
	    const element = selectionElement(selection);
	    const metadata = element ? elementMetadata(element) : null;
	    return {
	      text,
	      node_id: metadata ? metadata.node_id : undefined,
	      selector: metadata ? metadata.selector : undefined,
	      role: metadata ? metadata.role : undefined,
	      tag: metadata ? metadata.tag : undefined,
	      ...selectionOffsets(element, range, text),
	      bounds: {
	        x: Math.round(rect.left),
	        y: Math.round(rect.top),
	        width: Math.round(rect.width),
	        height: Math.round(rect.height),
	      },
	    };
	  };
	  const createSelectionToolbar = () => {
	    if (selectionToolbar) return selectionToolbar;
	    selectionToolbar = document.createElement("div");
	    selectionToolbar.className = "pa-selection-toolbar is-hidden";
	    const button = document.createElement("button");
	    button.type = "button";
	    button.textContent = "Send to Agent";
	    button.addEventListener("click", (event) => {
	      event.preventDefault();
	      event.stopPropagation();
	      if (lastSelectionMetadata) sendTextSelection(lastSelectionMetadata);
	      hideSelectionToolbar();
	      const selection = window.getSelection();
	      if (selection) selection.removeAllRanges();
	    });
	    selectionToolbar.appendChild(button);
	    (document.body || document.documentElement).appendChild(selectionToolbar);
	    return selectionToolbar;
	  };
	  const hideSelectionToolbar = () => {
	    if (selectionToolbar) selectionToolbar.classList.add("is-hidden");
	  };
	  const showSelectionToolbar = () => {
	    const metadata = selectionMetadata();
	    if (!metadata) {
	      lastSelectionMetadata = null;
	      hideSelectionToolbar();
	      return;
	    }
	    lastSelectionMetadata = metadata;
	    const toolbar = createSelectionToolbar();
	    const margin = 10;
	    const width = toolbar.offsetWidth || 120;
	    const height = toolbar.offsetHeight || 34;
	    const left = Math.min(Math.max(metadata.bounds.x, margin), Math.max(margin, window.innerWidth - width - margin));
	    const top = Math.min(Math.max(metadata.bounds.y - height - 8, margin), Math.max(margin, window.innerHeight - height - margin));
	    toolbar.style.left = Math.round(left) + "px";
	    toolbar.style.top = Math.round(top) + "px";
	    toolbar.classList.remove("is-hidden");
	  };
	  const formDataForSubmit = (form, submitter) => {
	    try {
	      return submitter ? new FormData(form, submitter) : new FormData(form);
	    } catch {
	      return new FormData(form);
	    }
	  };
	  const submitForm = (form, submitter) => {
	    if (!form || !form.getAttribute) return false;
	    const method = String(form.getAttribute("method") || "get").toLowerCase();
	    const actionUrl = new URL(form.getAttribute("action") || document.baseURI, document.baseURI).href;
	    trackEvent("submit", {
	      targetElement: form,
	      payload: {
	        method,
	        action: actionUrl,
	        submitter: submitter ? trimText(elementText(submitter), 120) : undefined,
	        page_state: pageState(),
	      },
	      importance: "high",
	    });
	    if (method !== "get") {
	      const mappedForm = form.closest("[data-pa-node-id]");
	      if (mappedForm) sendElementAction(mappedForm.getAttribute("data-pa-node-id"), "submit");
	      return true;
	    }
	    const url = new URL(actionUrl);
	    const data = formDataForSubmit(form, submitter);
	    for (const [key, value] of data.entries()) {
	      if (key) url.searchParams.append(key, String(value));
	    }
	    send(url.href);
	    return true;
	  };
	  if (document.readyState === "loading") {
	    document.addEventListener("DOMContentLoaded", () => {
	      applyKnownNodeIds();
	      applyAnnotationMarkers();
	    }, { once: true });
	  } else {
	    applyKnownNodeIds();
	    applyAnnotationMarkers();
	  }
	  document.addEventListener("mousemove", scheduleHover, true);
	  document.addEventListener("mouseleave", clearHover, true);
	  document.addEventListener("selectionchange", () => {
	    coalescedSelectionEvent();
	    window.setTimeout(showSelectionToolbar, 0);
	  });
	  document.addEventListener("mouseup", () => window.setTimeout(showSelectionToolbar, 0), true);
	  document.addEventListener("input", (event) => {
	    const target = event.target && event.target.closest
	      ? event.target.closest(interactiveSelector) || event.target
	      : event.target;
	    if (!target || !target.getAttribute) return;
	    trackEvent("input", {
	      targetElement: target,
	      payload: valuePayload(target),
	      importance: "medium",
	    });
	  }, true);
	  document.addEventListener("change", (event) => {
	    const target = event.target && event.target.closest
	      ? event.target.closest(interactiveSelector) || event.target
	      : event.target;
	    if (!target || !target.getAttribute) return;
	    trackEvent("change", {
	      targetElement: target,
	      payload: valuePayload(target),
	      importance: "medium",
	    });
	  }, true);
	  document.addEventListener("focusin", (event) => {
	    const target = event.target && event.target.closest
	      ? event.target.closest(interactiveSelector) || event.target
	      : event.target;
	    if (!target || !target.getAttribute) return;
	    trackEvent("focus", {
	      targetElement: target,
	      payload: { page_state: pageState() },
	      importance: "medium",
	    });
	  }, true);
	  document.addEventListener("focusout", (event) => {
	    const target = event.target && event.target.closest
	      ? event.target.closest(interactiveSelector) || event.target
	      : event.target;
	    if (!target || !target.getAttribute) return;
	    trackEvent("blur", {
	      targetElement: target,
	      payload: { page_state: pageState() },
	      importance: "low",
	    });
	  }, true);
	  window.addEventListener("blur", () => {
	    clearHover();
	    hideSelectionToolbar();
	  });
	  window.addEventListener("scroll", () => {
	    if (activeTarget) positionHighlightOverlay(activeTarget);
	    showSelectionToolbar();
	    coalescedScrollEvent();
	  }, true);
	  window.addEventListener("resize", coalescedResizeEvent);
	  window.addEventListener("beforeunload", sendEventBatch);
	  document.addEventListener("visibilitychange", () => {
	    if (document.visibilityState === "hidden") sendEventBatch();
	  });
	  try {
	    const mutationObserver = new MutationObserver((mutations) => {
	      if (!mutations.some((mutation) => {
	        const target = mutation.target;
	        if (target && target.closest && target.closest(".pa-inspector-tooltip, .pa-inspector-fill, .pa-selection-toolbar, .pa-comment-marker")) return false;
	        return mutation.attributeName !== "data-pa-node-id" && mutation.attributeName !== "data-pa-comment-count";
	      })) return;
	      coalescedMutationEvent();
	    });
	    mutationObserver.observe(document.documentElement, {
	      subtree: true,
	      childList: true,
	      attributes: true,
	      characterData: true,
	    });
	  } catch {
	    // Observer support is optional for the mirror event channel.
	  }
	  try {
	    if (typeof ResizeObserver === "function") {
	      const resizeObserver = new ResizeObserver(coalescedResizeEvent);
	      resizeObserver.observe(document.documentElement);
	      if (document.body) resizeObserver.observe(document.body);
	    }
	  } catch {
	    // Resize observation is best-effort.
	  }
	  try {
	    if (typeof IntersectionObserver === "function") {
	      const intersectionObserver = new IntersectionObserver(coalescedIntersectionEvent, { threshold: [0, 0.5, 1] });
	      Array.from(document.querySelectorAll(interactiveSelector)).slice(0, 80).forEach((element) => {
	        try {
	          intersectionObserver.observe(element);
	        } catch {
	          // Ignore nodes that cannot be observed.
	        }
	      });
	    }
	  } catch {
	    // Intersection observation is best-effort.
	  }
		  window.addEventListener("message", (event) => {
		    const data = event.data || {};
		    if (!data || data.browserId !== browserId) return;
		    if (data.type !== "personagent-session-browser:state") return;
		    applyMode(data.mode);
	    cooperationEnabled = Boolean(data.cooperationEnabled);
	    if (!cooperationEnabled) {
	      eventBuffer = [];
	      if (eventFlushTimer) {
	        window.clearTimeout(eventFlushTimer);
	        eventFlushTimer = 0;
	      }
	    }
	    annotationCounts = data.annotationCounts && typeof data.annotationCounts === "object" ? data.annotationCounts : {};
	    selectedNodeId = typeof data.selectedNodeId === "string" ? data.selectedNodeId : "";
	    applyAnnotationMarkers();
	    if (!activeTarget && !selectedNodeId) positionHighlightOverlay(null);
	  });
	  const waitForStylesReady = () => new Promise((resolve) => {
	    const startedAt = Date.now();
	    const timeoutMs = 4200;
	    const styleLinks = Array.from(document.querySelectorAll('link[rel~="stylesheet"], link[as="style"], link[href$=".css"]'));
	    const settleLink = (link) => new Promise((linkResolve) => {
	      try {
	        if (link.sheet || link.getAttribute("data-personagent-embedded-css") === "true") {
	          linkResolve(true);
	          return;
	        }
	      } catch {
	        linkResolve(false);
	        return;
	      }
	      let finished = false;
	      const finish = (value) => {
	        if (finished) return;
	        finished = true;
	        linkResolve(value);
	      };
	      link.addEventListener("load", () => finish(true), { once: true });
	      link.addEventListener("error", () => finish(false), { once: true });
	      window.setTimeout(() => finish(Boolean(link.sheet)), timeoutMs);
	    });
	    const fontsReady = document.fonts && document.fonts.ready
	      ? Promise.race([
	          document.fonts.ready.then(() => true).catch(() => false),
	          new Promise((fontResolve) => window.setTimeout(() => fontResolve(false), timeoutMs)),
	        ])
	      : Promise.resolve(true);
	    Promise.allSettled([...styleLinks.map(settleLink), fontsReady])
	      .then((results) => {
	        const loadedCount = results.slice(0, styleLinks.length).filter((result) => result.status === "fulfilled" && result.value !== false).length;
	        const waitFrame = () => new Promise((frameResolve) => window.requestAnimationFrame(() => frameResolve(true)));
	        return waitFrame().then(waitFrame).then(() => ({
	          stylesheetCount: styleLinks.length,
	          stylesheetLoadedCount: loadedCount,
	          styleReady: styleLinks.length === 0 || loadedCount >= styleLinks.length,
	          elapsedMs: Date.now() - startedAt,
	        }));
	      })
	      .then(resolve)
	      .catch(() => resolve({
	        stylesheetCount: styleLinks.length,
	        stylesheetLoadedCount: 0,
	        styleReady: false,
	        elapsedMs: Date.now() - startedAt,
	      }));
	  });
	  waitForStylesReady().then((readyState) => {
	    window.parent.postMessage({
	      type: "personagent-session-browser:ready",
	      browserId,
	      ...readyState,
	    }, "*");
	  });
	  document.addEventListener("click", (event) => {
	    if (event.target && event.target.closest && event.target.closest(".pa-selection-toolbar")) {
	      return;
	    }
	    const clickedTarget = event.target && event.target.closest
	      ? event.target.closest(inspectableSelector) || event.target
	      : event.target;
	    if (clickedTarget && clickedTarget.getAttribute) {
	      trackEvent("click", {
	        targetElement: clickedTarget,
	        payload: {
	          button: event.button === 1 ? "middle" : event.button === 2 ? "right" : "left",
	          x: Math.round(event.clientX),
	          y: Math.round(event.clientY),
	          page_state: pageState(),
	        },
	        importance: "high",
	      });
	    }
	    if (mode === "annotate") {
	      const target = activeTarget && containsPoint(activeTarget, event.clientX, event.clientY)
	        ? activeTarget
	        : targetFromPoint(event.clientX, event.clientY);
	      if (target) {
	        event.preventDefault();
	        event.stopPropagation();
	        sendElement(target);
	        return;
	      }
	    }
	    const submitter = event.target && event.target.closest
	      ? event.target.closest("button, input[type='submit'], input[type='image']")
	      : null;
	    const submitterType = submitter ? String(submitter.getAttribute("type") || "submit").toLowerCase() : "";
	    const form = submitter && (submitter.form || submitter.closest("form"));
	    if (form && (!submitterType || submitterType === "submit" || submitterType === "image")) {
	      event.preventDefault();
	      event.stopPropagation();
	      submitForm(form, submitter);
	      return;
	    }
	    const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
	    if (anchor) {
	      event.preventDefault();
	      send(new URL(anchor.getAttribute("href"), document.baseURI).href);
	      return;
	    }
	    const actionTarget = event.target && event.target.closest
	      ? event.target.closest("button,input[type='button'],input[type='checkbox'],input[type='radio'],summary,[role='button'],[role='tab'],[role='checkbox'],[role='radio'],[role='menuitem']")
	      : null;
	    if (!actionTarget) return;
	    event.preventDefault();
	    event.stopPropagation();
	    sendElementAction(ensureNodeId(actionTarget), "click");
	  }, true);
	  document.addEventListener("keydown", (event) => {
	    const target = event.target && event.target.closest
	      ? event.target.closest(interactiveSelector) || event.target
	      : event.target;
	    if (target && target.getAttribute) {
	      trackEvent("keydown", {
	        targetElement: target,
	        payload: {
	          key: event.key && event.key.length === 1 ? "[character]" : event.key,
	          ctrl_key: Boolean(event.ctrlKey),
	          meta_key: Boolean(event.metaKey),
	          alt_key: Boolean(event.altKey),
	          shift_key: Boolean(event.shiftKey),
	          page_state: pageState(),
	        },
	        importance: event.key === "Enter" ? "medium" : "low",
	      });
	    }
	    if (event.defaultPrevented || event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
	    const submitTarget = event.target;
	    if (!submitTarget || !submitTarget.form || submitTarget.tagName === "TEXTAREA") return;
	    event.preventDefault();
	    event.stopPropagation();
	    submitForm(submitTarget.form, null);
	  }, true);
	  document.addEventListener("submit", (event) => {
	    const form = event.target;
	    if (!form || !form.getAttribute) return;
	    event.preventDefault();
	    submitForm(form, null);
	  }, true);
	})();
	</script>`;
  if (/<head(\s[^>]*)?>/i.test(sanitizedHtml)) {
    return sanitizedHtml.replace(/<head(\s[^>]*)?>/i, (match) => `${match}${meta}${base}${overlayStyle}${script}`);
  }
  return `${meta}${base}${overlayStyle}${script}${sanitizedHtml}`;
}

export function sanitizeBrowserMirrorHtml(html: string) {
  const parser = new DOMParser();
  const document = parser.parseFromString(html || "<!doctype html><html><body></body></html>", "text/html");
  for (const element of Array.from(
    document.querySelectorAll(
      [
        "script",
        "iframe",
        "object",
        "embed",
        "base",
        "meta[http-equiv]",
      ].join(","),
    ),
  )) {
    element.remove();
  }
  for (const link of Array.from(document.querySelectorAll("link"))) {
    const rel = link.getAttribute("rel")?.toLowerCase() ?? "";
    const as = link.getAttribute("as")?.toLowerCase() ?? "";
    if (rel === "modulepreload" || (rel === "preload" && (as === "script" || as === "worker"))) {
      link.remove();
    }
  }
  for (const element of Array.from(document.querySelectorAll("*"))) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || name === "srcdoc" || isUnsafeMirrorUrlAttribute(element, name, attribute.value)) {
        element.removeAttribute(attribute.name);
      }
    }
  }
  return `<!doctype html>\n${document.documentElement.outerHTML}`;
}

function isUnsafeMirrorUrlAttribute(element: Element, name: string, value: string) {
  if (!["href", "src", "action", "formaction", "xlink:href"].includes(name)) return false;
  const normalized = value.trim().replace(/[\u0000-\u001f\u007f\s]+/g, "").toLowerCase();
  if (normalized.startsWith("javascript:") || normalized.startsWith("vbscript:")) return true;
  if (!normalized.startsWith("data:")) return false;
  const tagName = element.tagName.toLowerCase();
  return !(name === "src" && tagName === "img" && /^data:image\/(?:png|jpe?g|gif|webp);/i.test(normalized));
}

function escapeHtmlAttribute(value: string) {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function scriptJson(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

function createCspNonce() {
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
