export const SCRIPT_CORE = `	  const interactiveSelector = "a[href],button,input,textarea,select,label,summary,[role='button'],[role='link'],[role='menuitem'],[role='tab'],[role='checkbox'],[role='radio'],[contenteditable='true']";
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
`;
