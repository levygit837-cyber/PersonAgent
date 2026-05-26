export const SCRIPT_EVENTS = `	  const formDataForSubmit = (form, submitter) => {
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
`;
