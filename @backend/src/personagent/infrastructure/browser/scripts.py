"""JavaScript injection scripts used by the LightPanda browser infrastructure.

Extracted from lightpanda.py as part of Slice 8 to keep the facade module lean.
"""

from __future__ import annotations

_BROWSER_ACT_SCRIPT = r"""
async ({ nodeId, selector, shadowPath, action, value, key, targetSelector, targetShadowPath, timeoutMs, text, x, y, targetText, targetHref, targetRole, targetTag }) => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  if (action === 'wait') {
    await sleep(Math.min(Math.max(Number(timeoutMs || value || 1000), 1), 120000));
    return { ok: true, node_id: nodeId, action, url: window.location.href };
  }
  if (action === 'screenshot') {
    return { ok: true, node_id: nodeId, action, url: window.location.href };
  }
  const resolveRoot = (path) => {
    let root = document;
    for (const hostSelector of Array.isArray(path) ? path : []) {
      if (!hostSelector || typeof root.querySelector !== 'function') return null;
      const host = root.querySelector(hostSelector);
      if (!host || !host.shadowRoot) return null;
      root = host.shadowRoot;
    }
    return root;
  };
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const interactiveSelector = [
    'a[href]',
    'button',
    'input',
    'textarea',
    'select',
    'form',
    '[role="button"]',
    '[role="link"]',
    '[role="menuitem"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="tab"]',
    'summary',
    'label'
  ].join(',');
  const roleFor = (candidate) => normalize(candidate.getAttribute('role')).toLowerCase() || (
    candidate.tagName.toLowerCase() === 'a' ? 'link' :
    candidate.tagName.toLowerCase() === 'button' ? 'button' :
    candidate.tagName.toLowerCase()
  );
  const nameFor = (candidate) => normalize([
    candidate.getAttribute('aria-label'),
    candidate.getAttribute('alt'),
    candidate.getAttribute('title'),
    candidate.getAttribute('placeholder'),
    candidate.getAttribute('value'),
    candidate.innerText,
    candidate.textContent
  ].filter(Boolean).join(' '));
  const resolveElement = (nextNodeId, nextSelector, nextShadowPath, metadata = {}) => {
    const root = resolveRoot(nextShadowPath) || document;
    let found = Array.from(root.querySelectorAll('[data-pa-node-id]'))
      .find((candidate) => candidate.getAttribute('data-pa-node-id') === nextNodeId);
    if (!found && nextSelector) {
      try {
        found = root.querySelector(nextSelector);
      } catch (_error) {}
    }
    if (!found && (metadata.text || metadata.href || metadata.role || metadata.tag)) {
      const wantedText = normalize(metadata.text).toLowerCase();
      const wantedHref = normalize(metadata.href);
      const wantedRole = normalize(metadata.role).toLowerCase();
      const wantedTag = normalize(metadata.tag).toLowerCase();
      const candidates = Array.from(root.querySelectorAll(interactiveSelector));
      found = candidates.find((candidate) => {
        if (wantedTag && candidate.tagName.toLowerCase() !== wantedTag) return false;
        if (wantedRole && roleFor(candidate) !== wantedRole) return false;
        if (wantedHref && candidate.href && candidate.href !== wantedHref) return false;
        if (wantedText) {
          const label = nameFor(candidate).toLowerCase();
          if (!label || (label !== wantedText && !label.includes(wantedText) && !wantedText.includes(label))) return false;
        }
        return true;
      });
    }
    return found || null;
  };
  let el = resolveElement(nodeId, selector, shadowPath, { text: targetText, href: targetHref, role: targetRole, tag: targetTag });
  if (!el && selector) {
    try {
      el = document.querySelector(selector);
    } catch (_error) {}
  }
  if (!el) return { ok: false, reason: 'node_not_found' };
  const dispatch = (target, type) => target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }));
  const mouse = (target, type, options = {}) => target.dispatchEvent(new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX: options.clientX ?? Math.round(target.getBoundingClientRect().left + target.getBoundingClientRect().width / 2),
    clientY: options.clientY ?? Math.round(target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2),
    button: 0,
  }));
  const focus = () => {
    if (typeof el.focus === 'function') {
      try { el.focus({ preventScroll: false }); } catch (_error) { el.focus(); }
    }
  };
  focus();
  if (action === 'click') {
    el.scrollIntoView({ block: 'center', inline: 'center' });
    await sleep(80);
    mouse(el, 'mouseover');
    mouse(el, 'mousemove');
    mouse(el, 'mousedown');
    mouse(el, 'mouseup');
    mouse(el, 'click');
    if (typeof el.click === 'function') {
      try { el.click(); } catch (_error) {}
    }
  } else if (action === 'fill') {
    if (!('value' in el)) return { ok: false, reason: 'not_fillable' };
    el.value = String(value ?? '');
    dispatch(el, 'input');
    dispatch(el, 'change');
  } else if (action === 'select') {
    if (!('value' in el)) return { ok: false, reason: 'not_selectable' };
    el.value = String(value ?? '');
    dispatch(el, 'input');
    dispatch(el, 'change');
  } else if (action === 'submit') {
    const form = el.tagName.toLowerCase() === 'form' ? el : el.closest('form');
    if (!form) return { ok: false, reason: 'form_not_found' };
    if (typeof form.requestSubmit === 'function') form.requestSubmit();
    else form.submit();
  } else if (action === 'press') {
    const nextKey = String(key || value || 'Enter');
    el.dispatchEvent(new KeyboardEvent('keydown', { key: nextKey, bubbles: true, cancelable: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { key: nextKey, bubbles: true, cancelable: true }));
  } else if (action === 'hover') {
    el.scrollIntoView({ block: 'center', inline: 'center' });
    await sleep(80);
    mouse(el, 'mouseover');
    mouse(el, 'mousemove');
  } else if (action === 'scroll_to') {
    el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
  } else if (action === 'select_text') {
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    if (!selection) return { ok: false, reason: 'selection_unavailable' };
    selection.removeAllRanges();
    selection.addRange(range);
  } else if (action === 'drag' || action === 'drop') {
    const target = targetSelector ? resolveElement('', targetSelector, targetShadowPath) : null;
    if (action === 'drop' && !target) return { ok: false, reason: 'drop_target_not_found' };
    el.scrollIntoView({ block: 'center', inline: 'center' });
    await sleep(80);
    const start = el.getBoundingClientRect();
    const end = target ? target.getBoundingClientRect() : {
      left: Number(x || start.left + start.width / 2),
      top: Number(y || start.top + start.height / 2),
      width: 1,
      height: 1,
    };
    const dataTransfer = new DataTransfer();
    mouse(el, 'mousedown', { clientX: start.left + start.width / 2, clientY: start.top + start.height / 2 });
    el.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer }));
    if (target) {
      target.dispatchEvent(new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer }));
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer }));
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
    }
    el.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer }));
    mouse(el, 'mouseup', { clientX: end.left + end.width / 2, clientY: end.top + end.height / 2 });
  } else if (action === 'upload') {
    if (!(el instanceof HTMLInputElement) || el.type !== 'file') return { ok: false, reason: 'not_file_input' };
    return { ok: false, reason: 'upload_requires_playwright_file_set' };
  } else {
    return { ok: false, reason: 'unsupported_action' };
  }
  await sleep(350);
  const rect = el.getBoundingClientRect();
  return {
    ok: true,
    node_id: nodeId,
    action,
    url: window.location.href,
    selector: selector || '',
    tag: el.tagName || '',
    bounds: {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    }
  };
}
"""

_STYLE_READY_SNAPSHOT_SCRIPT = r"""
async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(true)));
  const links = Array.from(document.querySelectorAll('link[rel~="stylesheet"], link[as="style"], link[href$=".css"]'));
  const settleLink = (link) => new Promise((resolve) => {
    try {
      if (link.sheet || link.getAttribute('data-personagent-embedded-css') === 'true') {
        resolve(true);
        return;
      }
    } catch {
      resolve(false);
      return;
    }
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    link.addEventListener('load', () => finish(true), { once: true });
    link.addEventListener('error', () => finish(false), { once: true });
    setTimeout(() => {
      try {
        finish(Boolean(link.sheet));
      } catch {
        finish(false);
      }
    }, 2600);
  });
  const fontsReady = document.fonts && document.fonts.ready
    ? Promise.race([document.fonts.ready.then(() => true).catch(() => false), wait(2600).then(() => false)])
    : Promise.resolve(true);
  const results = await Promise.allSettled([...links.map(settleLink), fontsReady]);
  await frame();
  await frame();
  const loaded = results.slice(0, links.length).filter((result) => result.status === 'fulfilled' && result.value !== false).length;
  const fontReadyResult = results[links.length];
  const fontsReadyValue = !fontReadyResult || (fontReadyResult.status === 'fulfilled' && fontReadyResult.value !== false);
  return {
    personagentStyleReadyProbe: true,
    style_ready: (links.length === 0 || loaded >= links.length) && fontsReadyValue,
    stylesheet_count: links.length,
    stylesheet_loaded_count: loaded,
    fonts_ready: fontsReadyValue
  };
}
"""

_CONSOLE_CAPTURE_SCRIPT = r"""
() => {
  if (window.__personagentConsoleCaptureInstalled) return true;
  const entries = [];
  let sequence = 0;
  const format = (value) => {
    try {
      if (typeof value === 'string') return value;
      if (value instanceof Error) return value.stack || value.message || String(value);
      return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
  };
  Object.defineProperty(window, '__personagentConsoleEntries', {
    value: entries,
    configurable: true,
  });
  Object.defineProperty(window, '__personagentConsoleCaptureInstalled', {
    value: true,
    configurable: true,
  });
  const push = (level, parts, source = 'console') => {
    try {
      entries.push({
        sequence: ++sequence,
        level,
        text: Array.from(parts || []).map(format).join(' '),
        source,
        url: window.location.href,
        timestamp: Date.now() / 1000,
      });
      if (entries.length > 500) entries.splice(0, entries.length - 500);
    } catch (_error) {}
  };
  for (const level of ['debug', 'error', 'info', 'log', 'warn']) {
    const original = console[level];
    console[level] = function personagentConsoleProxy(...args) {
      push(level, args);
      if (typeof original === 'function') return original.apply(this, args);
    };
  }
  window.addEventListener('error', (event) => {
    push('error', [event.message || event.error || 'Page error'], 'pageerror');
  });
  window.addEventListener('unhandledrejection', (event) => {
    push('error', [event.reason || 'Unhandled rejection'], 'unhandledrejection');
  });
  return true;
}
"""

_CONSOLE_DRAIN_SCRIPT = r"""
() => {
  const entries = Array.isArray(window.__personagentConsoleEntries)
    ? window.__personagentConsoleEntries.splice(0)
    : [];
  return entries;
}
"""

_COOPERATION_CAPTURE_SCRIPT = r"""
(config) => {
  if (window.__personagentBrowserCooperationInstalled) return true;
  const browserId = String(config && config.browserId || '');
  const pageId = String(config && config.pageId || browserId);
  const entries = [];
  let sequence = 0;
  const eventId = () => 'cdp_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
  const text = (value, max = 120) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const hash = (value) => {
    let h = 0;
    const input = String(value || '');
    for (let i = 0; i < input.length; i += 1) h = ((h << 5) - h + input.charCodeAt(i)) | 0;
    return Math.abs(h).toString(16);
  };
  const isSensitive = (element) => {
    if (!element || !element.getAttribute) return false;
    const meta = [
      element.getAttribute('type'),
      element.getAttribute('autocomplete'),
      element.getAttribute('name'),
      element.getAttribute('id'),
      element.getAttribute('aria-label'),
      element.getAttribute('placeholder')
    ].join(' ');
    return /(password|passcode|token|secret|api[_-]?key|credit|card|cc-|cc_|cvv|cvc|expiry|email)/i.test(meta);
  };
  const bounds = (element) => {
    if (!element || !element.getBoundingClientRect) return undefined;
    const rect = element.getBoundingClientRect();
    return {
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    };
  };
  const target = (element) => {
    if (!element || !element.getAttribute) return {};
    const label = text(
      element.getAttribute('aria-label') ||
      element.getAttribute('placeholder') ||
      element.getAttribute('name') ||
      element.getAttribute('id') ||
      element.textContent ||
      ''
    );
    return {
      tag: String(element.tagName || '').toLowerCase(),
      role: element.getAttribute('role') || undefined,
      text: isSensitive(element) ? '[REDACTED]' : label,
      label: isSensitive(element) ? '[REDACTED]' : label,
      selector: element.id ? '#' + element.id : undefined,
      input_type: element.getAttribute('type') || undefined,
      autocomplete: element.getAttribute('autocomplete') || undefined,
      bounds: bounds(element)
    };
  };
  const pageState = () => ({
    modal_open: Boolean(document.querySelector('[role="dialog"],dialog,[aria-modal="true"]')),
    focused_field: document.activeElement && document.activeElement !== document.body
      ? text(document.activeElement.getAttribute('aria-label') || document.activeElement.getAttribute('placeholder') || document.activeElement.getAttribute('name') || '')
      : null,
    route: window.location.pathname || '/',
    scroll: {
      x: Math.round(window.scrollX || document.documentElement.scrollLeft || 0),
      y: Math.round(window.scrollY || document.documentElement.scrollTop || 0)
    }
  });
  const valuePayload = (element) => {
    if (!element || !('value' in element)) return {};
    const value = String(element.value || '');
    if (isSensitive(element)) {
      return { value: '[REDACTED]', value_redacted: true, value_char_count: value.length };
    }
    return { value: { preview: text(value), char_count: value.length, hash: hash(value) } };
  };
  const push = (kind, options = {}) => {
    try {
      const event = {
        event_id: eventId(),
        kind,
        raw_kind: kind,
        source: 'user',
        channel: 'event',
        trace_role: 'user',
        visibility: options.visibility || (['click', 'input', 'change', 'submit', 'navigation', 'route_change', 'mutation'].includes(kind) ? 'useful' : 'raw'),
        timestamp: new Date().toISOString(),
        browser_id: browserId,
        page_id: pageId,
        tab_id: pageId,
        url: window.location.href || document.baseURI || '',
        target: options.target || {},
        payload: { ...(options.payload || {}), page_state: pageState() },
        coordinates: options.coordinates || {},
        trace_effect: options.trace_effect || (kind === 'scroll' ? 'scroll' : ['input', 'change', 'keydown'].includes(kind) ? 'type' : kind === 'click' ? 'click' : 'highlight'),
        correlation_id: options.correlation_id || '',
        importance: options.importance || (['click', 'input', 'change', 'submit', 'navigation', 'route_change', 'mutation'].includes(kind) ? 'high' : 'low'),
        semantic_label: options.semantic_label || ''
      };
      entries.push(event);
      if (entries.length > 500) entries.splice(0, entries.length - 500);
      if (typeof window.__personagentBrowserEvent === 'function') {
        Promise.resolve(window.__personagentBrowserEvent(event)).catch(() => {});
      }
    } catch (_error) {}
  };
  Object.defineProperty(window, '__personagentBrowserCooperationEvents', {
    value: entries,
    configurable: true,
  });
  Object.defineProperty(window, '__personagentBrowserCooperationInstalled', {
    value: true,
    configurable: true,
  });
  document.addEventListener('click', (event) => {
    const element = event.target && event.target.closest ? event.target.closest('a,button,input,textarea,select,[role],form') || event.target : event.target;
    const metadata = target(element);
    push('click', {
      target: metadata,
      payload: { button: event.button === 1 ? 'middle' : event.button === 2 ? 'right' : 'left', x: Math.round(event.clientX), y: Math.round(event.clientY) },
      coordinates: { x: Math.round(event.clientX), y: Math.round(event.clientY), bounds: metadata.bounds },
      trace_effect: 'click'
    });
  }, true);
  document.addEventListener('input', (event) => {
    const element = event.target;
    push('input', { target: target(element), payload: valuePayload(element), trace_effect: 'type' });
  }, true);
  document.addEventListener('change', (event) => {
    const element = event.target;
    push('change', { target: target(element), payload: valuePayload(element), trace_effect: 'type' });
  }, true);
  document.addEventListener('keydown', (event) => {
    const element = event.target;
    push('keydown', { target: target(element), payload: { key: event.key && event.key.length === 1 ? '[character]' : event.key }, trace_effect: 'type', importance: 'low' });
  }, true);
  document.addEventListener('submit', (event) => {
    push('submit', { target: target(event.target), trace_effect: 'click', importance: 'high' });
  }, true);
  let scrollTimer = 0;
  window.addEventListener('scroll', () => {
    if (scrollTimer) return;
    scrollTimer = window.setTimeout(() => {
      scrollTimer = 0;
      push('scroll', { payload: pageState().scroll, trace_effect: 'scroll', importance: 'low' });
    }, 250);
  }, true);
  let mutationTimer = 0;
  if (window.MutationObserver) {
    new MutationObserver(() => {
      if (mutationTimer) return;
      mutationTimer = window.setTimeout(() => {
        mutationTimer = 0;
        push('mutation', { semantic_label: 'page content changed', importance: 'high' });
      }, 700);
    }).observe(document.documentElement, { childList: true, subtree: true, attributes: true });
  }
  const route = () => push('route_change', { payload: { url: window.location.href }, trace_effect: 'highlight', importance: 'high' });
  window.addEventListener('popstate', route);
  window.addEventListener('hashchange', route);
  return true;
}
"""

_COOPERATION_DRAIN_SCRIPT = r"""
() => {
  const entries = Array.isArray(window.__personagentBrowserCooperationEvents)
    ? window.__personagentBrowserCooperationEvents.splice(0)
    : [];
  return entries;
}
"""
