export const SCRIPT_UI = `	  const createTooltip = () => {
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
`;
