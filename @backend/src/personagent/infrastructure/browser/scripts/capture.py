"""JavaScript injection scripts for console and cooperation event capture.

Extracted from ``scripts.py`` (Slice 3 of scripts decomposition).
Consumed exclusively by ``console.py``.
"""

from __future__ import annotations

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
