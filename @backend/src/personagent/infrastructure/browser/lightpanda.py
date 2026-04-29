"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
import structlog

from personagent.infrastructure.browser.content_cleanup import (
    MARKDOWN_LINK_PATTERN as _MARKDOWN_LINK_PATTERN,
)
from personagent.infrastructure.browser.content_cleanup import (
    clean_extracted_content as _clean_extracted_content,
)
from personagent.infrastructure.browser.content_cleanup import (
    should_prefer_readable_dom as _should_prefer_readable_dom,
)
from personagent.infrastructure.browser.models import (
    BrowserBlockedError,
    BrowserConsoleEntry,
    BrowserError,
    BrowserOpenedPage,
    BrowserSearchResult,
    BrowserSearchSnapshot,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.models import (
    BrowserSession as _BrowserSession,
)
from personagent.infrastructure.browser.url_utils import (
    browser_empty_fallback_html as _browser_empty_fallback_html,
)
from personagent.infrastructure.browser.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    infer_search_provider as _infer_search_provider,
)
from personagent.infrastructure.browser.url_utils import (
    is_local_lightpanda_endpoint as _is_local_lightpanda_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    is_retryable_raw_cdp_error as _is_retryable_raw_cdp_error,
)
from personagent.infrastructure.browser.url_utils import (
    is_target_already_loaded_error as _is_target_already_loaded_error,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_lightpanda_cdp_endpoint,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_navigation_url as _normalize_navigation_url,
)
from personagent.infrastructure.browser.url_utils import (
    urls_equivalent as _urls_equivalent,
)

logger = structlog.get_logger(__name__)

Connector = Callable[[str], Awaitable[Any]]

_DEFAULT_SEARCH_BASE_URL = "https://search.yahoo.com/search"
_MAX_CACHED_SEARCHES_PER_CONVERSATION = 8
_MAX_OPENED_PAGES_PER_CONVERSATION = 32
_STYLESHEET_LINK_PATTERN = re.compile(
    r"<link\b(?=[^>]*\brel\s*=\s*['\"][^'\"]*stylesheet[^'\"]*['\"])(?=[^>]*\bhref\s*=\s*['\"](?P<href>[^'\"]+)['\"])[^>]*>",
    re.IGNORECASE,
)
_LINK_TAG_PATTERN = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HTML_ATTR_PATTERN = re.compile(
    r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'>`]+)"
)
_CSS_URL_PATTERN = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"\s][^)'\"]*)(?P=quote)\)")
_STYLESHEET_CACHE_TTL_SECONDS = 600.0
_MAX_STYLESHEET_CACHE_ENTRIES = 256
_RAW_CDP_RETRY_DELAYS = (0.0, 0.5, 1.5, 3.0, 5.0)
_MAX_CONSOLE_ENTRIES_PER_PAGE = 200
_MAX_BROWSER_SCRIPT_CHARS = 10_000
_MAX_BROWSER_SCRIPT_RESULT_CHARS = 12_000
_BROWSER_SCRIPT_CDP_ALLOWLIST = {
    "Runtime.evaluate",
    "Performance.getMetrics",
    "DOM.getDocument",
    "DOM.querySelector",
    "DOM.getOuterHTML",
    "Page.captureScreenshot",
    "Log.enable",
    "Log.clear",
}
_READABLE_DOM_SCRIPT = r"""
(() => {
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const body = document.body ? document.body.cloneNode(true) : document.documentElement.cloneNode(true);
  const removeSelectors = [
    'script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe',
    'nav', 'header', 'footer', 'aside',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    'form', 'button'
  ];
  body.querySelectorAll(removeSelectors.join(',')).forEach((el) => el.remove());
  const noisyMeta = /(cookie|newsletter|subscribe|advert|promo|share|social|related|recommend|most-popular|trending|nav|menu|footer|header|sidebar)/i;
  Array.from(body.querySelectorAll('*')).forEach((el) => {
    const meta = `${el.id || ''} ${typeof el.className === 'string' ? el.className : ''} ${el.getAttribute('aria-label') || ''}`;
    if (!noisyMeta.test(meta)) return;
    const textLength = normalize(el.textContent).length;
    const linkCount = el.querySelectorAll('a[href]').length;
    if (textLength < 1400 || linkCount >= 8) el.remove();
  });
  const selectors = [
    'article',
    'main',
    '[role="main"]',
    '[itemprop="articleBody"]',
    '.article-body',
    '.articleBody',
    '.story-body',
    '.entry-content',
    '.post-content',
    '.post__content',
    '.content-body',
    '.body-content',
    '.article-content'
  ];
  const candidates = Array.from(body.querySelectorAll(selectors.join(',')));
  if (!candidates.includes(body)) candidates.push(body);
  const textFor = (node) => {
    const pieces = [];
    const seen = new Set();
    node.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,figcaption,td,th').forEach((el) => {
      const text = normalize(el.textContent);
      if (text.length < 2 || seen.has(text)) return;
      seen.add(text);
      pieces.push(text);
    });
    const structured = pieces.join('\n\n');
    if (structured.length >= 300) return structured;
    return normalize(node.textContent);
  };
  const scoreFor = (node) => {
    const text = textFor(node);
    const linkCount = node.querySelectorAll('a[href]').length;
    const paragraphCount = node.querySelectorAll('p').length;
    const headingCount = node.querySelectorAll('h1,h2,h3').length;
    return text.length + paragraphCount * 180 + headingCount * 100 - linkCount * 90;
  };
  let best = candidates[0] || body;
  let bestScore = -Infinity;
  for (const candidate of candidates) {
    const score = scoreFor(candidate);
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  const content = textFor(best);
  const links = Array.from(best.querySelectorAll('a[href]')).map((a) => ({
    url: a.href || a.getAttribute('href') || '',
    text: normalize(a.textContent)
  })).filter((item) => /^https?:\/\//i.test(item.url)).slice(0, 80);
  return {
    title: normalize(document.title),
    content,
    link_count: links.length,
    selected_tag: best.tagName ? best.tagName.toLowerCase() : 'body',
    score: bestScore
  };
})()
"""

_POPUP_DISMISS_SCRIPT = r"""
(() => {
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || 1) === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width >= 8 && rect.height >= 8 && rect.bottom >= 0 && rect.right >= 0 &&
      rect.top <= window.innerHeight && rect.left <= window.innerWidth;
  };
  const fixedAncestor = (el) => {
    let node = el;
    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
      const style = window.getComputedStyle(node);
      if (style.position === 'fixed' || style.position === 'sticky') return true;
      const z = Number.parseInt(style.zIndex || '0', 10);
      if (Number.isFinite(z) && z >= 1000) return true;
    }
    return false;
  };
  const dismissPattern = /\b(accept all|accept|agree|i agree|allow all|got it|ok|continue|close|dismiss|reject all|reject|decline|no thanks|not now|skip|fechar|aceitar|concordo|entendi|continuar|rejeitar|agora nao|agora n\u00e3o|nao obrigado|n\u00e3o obrigado)\b/i;
  const closePattern = /\b(close|dismiss|fechar|x)\b/i;
  const unsafePattern = /\b(subscribe|sign in|login|log in|register|buy|purchase|checkout|download)\b/i;
  const selector = [
    'button',
    '[role="button"]',
    'a[href]',
    'input[type="button"]',
    'input[type="submit"]',
    '[aria-label]',
    '[title]'
  ].join(',');
  const candidates = [];
  for (const el of Array.from(document.querySelectorAll(selector))) {
    if (!isVisible(el)) continue;
    const rect = el.getBoundingClientRect();
    const label = normalize([
      el.innerText,
      el.textContent,
      el.getAttribute('aria-label'),
      el.getAttribute('title'),
      el.getAttribute('value'),
      el.id,
      typeof el.className === 'string' ? el.className : ''
    ].join(' '));
    if (!label || !dismissPattern.test(label)) continue;
    const isClose = closePattern.test(label) || normalize(el.textContent).toLowerCase() === '\u00d7';
    if (!isClose && unsafePattern.test(label)) continue;
    const overlayish = fixedAncestor(el) || rect.top < 140 || rect.bottom > window.innerHeight - 180;
    if (!overlayish && !isClose) continue;
    candidates.push({
      el,
      label: label.slice(0, 80),
      priority: (isClose ? 0 : 10) + (fixedAncestor(el) ? 0 : 5) + rect.width * rect.height / 100000
    });
  }
  candidates.sort((a, b) => a.priority - b.priority);
  const clicked = [];
  for (const candidate of candidates.slice(0, 3)) {
    try {
      candidate.el.click();
      clicked.push(candidate.label);
    } catch (_error) {}
  }
  return { clicked_count: clicked.length, clicked_labels: clicked };
})()
"""

_INCREMENTAL_SCROLL_SCRIPT = r"""
async ({ maxSteps, delayMs, stepRatio }) => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const root = document.scrollingElement || document.documentElement || document.body;
  const metrics = () => {
    const scrollY = window.scrollY || root.scrollTop || 0;
    const viewportHeight = window.innerHeight || root.clientHeight || 0;
    const scrollHeight = Math.max(
      root.scrollHeight || 0,
      document.body ? document.body.scrollHeight || 0 : 0,
      document.documentElement ? document.documentElement.scrollHeight || 0 : 0
    );
    return {
      scroll_y: Math.round(scrollY),
      viewport_height: Math.round(viewportHeight),
      scroll_height: Math.round(scrollHeight),
      at_bottom: scrollY + viewportHeight >= scrollHeight - 8
    };
  };
  let previous = metrics();
  let stableBottomCount = 0;
  let steps = 0;
  for (; steps < maxSteps; steps += 1) {
    const step = Math.max(260, Math.floor((previous.viewport_height || 800) * stepRatio));
    window.scrollBy({ top: step, left: 0, behavior: 'instant' });
    await sleep(delayMs);
    const current = metrics();
    if (
      current.at_bottom &&
      current.scroll_height === previous.scroll_height &&
      Math.abs(current.scroll_y - previous.scroll_y) < 4
    ) {
      stableBottomCount += 1;
    } else {
      stableBottomCount = 0;
    }
    previous = current;
    if (current.at_bottom && stableBottomCount >= 2) break;
  }
  await sleep(delayMs);
  return { ...metrics(), steps };
}
"""

_BROWSER_ELEMENT_MAP_SCRIPT = r"""
(options = {}) => {
  const frameId = String(options.frameId || 'main');
  const frameUrl = String(options.frameUrl || window.location.href || '');
  const offsetX = Number(options.offsetX || 0);
  const offsetY = Number(options.offsetY || 0);
  const selectors = [
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
    'label',
    'iframe',
    'h1',
    'h2',
    'h3',
    'article',
    'main',
    'section'
  ].join(',');
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const hash = (value) => {
    let h = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      h ^= value.charCodeAt(index);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(36);
  };
  const cssEscape = (value) => window.CSS && CSS.escape
    ? CSS.escape(value)
    : String(value).replace(/["\\#.:>[\]\s]/g, '\\$&');
  const cssPath = (el) => {
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === Node.ELEMENT_NODE && depth < 8) {
      const tag = node.tagName.toLowerCase();
      const id = node.id ? `#${cssEscape(node.id)}` : '';
      if (id) {
        parts.unshift(`${tag}${id}`);
        break;
      }
      let index = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === node.tagName) index += 1;
        sibling = sibling.previousElementSibling;
      }
      parts.unshift(`${tag}:nth-of-type(${index})`);
      node = node.parentElement;
      depth += 1;
    }
    return parts.join(' > ');
  };
  const inferredRole = (el) => {
    const explicit = normalize(el.getAttribute('role')).toLowerCase();
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'input') return normalize(el.getAttribute('type')).toLowerCase() || 'input';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'select';
    if (tag === 'form') return 'form';
    if (/^h[1-3]$/.test(tag)) return 'heading';
    return tag;
  };
  const accessibleName = (el) => {
    const labelledBy = normalize(el.getAttribute('aria-labelledby'));
    if (labelledBy) {
      const root = el.getRootNode && el.getRootNode();
      const text = labelledBy
        .split(/\s+/)
        .map((id) => root?.getElementById?.(id)?.textContent || document.getElementById(id)?.textContent || '')
        .join(' ');
      if (normalize(text)) return normalize(text);
    }
    return normalize([
      el.getAttribute('aria-label'),
      el.getAttribute('alt'),
      el.getAttribute('title'),
      el.getAttribute('placeholder'),
      el.getAttribute('value'),
      el.innerText,
      el.textContent
    ].filter(Boolean).join(' ')).slice(0, 240);
  };
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.right >= 0 &&
      rect.top <= Math.max(window.innerHeight, 1) * 3 && rect.left <= Math.max(window.innerWidth, 1) * 3;
  };
  const interactable = (el) => Boolean(el.matches && el.matches([
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
  ].join(',')));
  const computedSummary = (el) => {
    const style = window.getComputedStyle(el);
    return {
      display: style.display,
      position: style.position,
      color: style.color,
      background: style.backgroundColor,
      font: `${style.fontSize} ${style.fontFamily}`,
      margin: style.margin,
      padding: style.padding,
      border: style.border,
      border_radius: style.borderRadius,
      box_sizing: style.boxSizing,
    };
  };
  const mapped = [];
  const seen = new Set();
  const mapElement = (el, shadowPath) => {
    if (!(el instanceof Element) || !isVisible(el)) return;
    const role = inferredRole(el);
    const selector = cssPath(el);
    const text = accessibleName(el);
    const href = el instanceof HTMLAnchorElement ? el.href : '';
    const form = el instanceof HTMLFormElement ? el : el.closest('form');
    const key = `${frameId}|${shadowPath.join('>')}|${role}|${selector}|${href}|${text.slice(0, 80)}`;
    const nodeId = normalize(el.getAttribute('data-pa-node-id')) || `pa_${hash(key)}`;
    if (seen.has(nodeId)) return;
    seen.add(nodeId);
    el.setAttribute('data-pa-node-id', nodeId);
    el.setAttribute('data-pa-role', role);
    const rect = el.getBoundingClientRect();
    mapped.push({
      node_id: nodeId,
      role,
      tag: el.tagName.toLowerCase(),
      text,
      selector,
      href,
      name: normalize(el.getAttribute('name')),
      input_type: el instanceof HTMLInputElement ? normalize(el.type) : '',
      form_method: form ? normalize(form.getAttribute('method') || 'get').toLowerCase() : '',
      form_action: form ? new URL(form.getAttribute('action') || el.ownerDocument.baseURI, el.ownerDocument.baseURI).href : '',
      tab_id: '',
      frame_id: frameId,
      frame_url: frameUrl,
      selector_chain: [...shadowPath, selector],
      shadow_path: shadowPath,
      stable_key: key,
      interactable: interactable(el),
      computed_summary: computedSummary(el),
      bounds: {
        x: Math.round(rect.x + offsetX),
        y: Math.round(rect.y + offsetY),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      },
      visible: true
    });
  };
  const collect = (root, shadowPath = []) => {
    if (!root || typeof root.querySelectorAll !== 'function' || mapped.length >= 500) return;
    for (const el of Array.from(root.querySelectorAll(selectors))) {
      mapElement(el, shadowPath);
      if (mapped.length >= 500) return;
    }
    for (const host of Array.from(root.querySelectorAll('*'))) {
      if (!host.shadowRoot) continue;
      const hostSelector = cssPath(host);
      collect(host.shadowRoot, [...shadowPath, hostSelector]);
      if (mapped.length >= 500) return;
    }
  }
  collect(document, []);
  return mapped;
}
"""

_BROWSER_ACT_SCRIPT = r"""
async ({ nodeId, selector, shadowPath, action, value, key, targetSelector, targetShadowPath, timeoutMs, text, x, y }) => {
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
  const resolveElement = (nextNodeId, nextSelector, nextShadowPath) => {
    const root = resolveRoot(nextShadowPath) || document;
    let found = Array.from(root.querySelectorAll('[data-pa-node-id]'))
      .find((candidate) => candidate.getAttribute('data-pa-node-id') === nextNodeId);
    if (!found && nextSelector) {
      try {
        found = root.querySelector(nextSelector);
      } catch (_error) {}
    }
    return found || null;
  };
  let el = resolveElement(nodeId, selector, shadowPath);
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
  return {
    ok: true,
    node_id: nodeId,
    action,
    url: window.location.href,
    selector: selector || '',
    tag: el.tagName || ''
  };
}
"""

_COMPUTED_HTML_SNAPSHOT_SCRIPT = r"""
({ url }) => {
  const important = [
    'display', 'position', 'box-sizing', 'float', 'clear',
    'width', 'height', 'min-width', 'min-height', 'max-width', 'max-height',
    'margin', 'padding', 'border', 'border-radius', 'outline',
    'font', 'font-size', 'font-family', 'font-weight', 'font-style', 'line-height',
    'letter-spacing', 'text-align', 'text-decoration', 'text-transform', 'white-space',
    'color', 'background', 'background-color', 'background-image', 'background-size',
    'background-position', 'background-repeat', 'opacity',
    'display', 'flex-direction', 'flex-wrap', 'align-items', 'align-content',
    'justify-content', 'gap', 'row-gap', 'column-gap',
    'grid-template-columns', 'grid-template-rows', 'grid-auto-flow',
    'list-style', 'vertical-align', 'overflow', 'object-fit', 'object-position'
  ];
  const pairs = [];
  const cloneTree = (source) => {
    if (!source) return null;
    if (source.nodeType === Node.TEXT_NODE) return document.createTextNode(source.nodeValue || '');
    if (source.nodeType !== Node.ELEMENT_NODE) return null;
    if (['SCRIPT', 'NOSCRIPT', 'TEMPLATE'].includes(source.tagName)) return null;
    const target = source.cloneNode(false);
    pairs.push([source, target]);
    for (const child of Array.from(source.childNodes || [])) {
      const clonedChild = cloneTree(child);
      if (clonedChild) target.appendChild(clonedChild);
    }
    if (source instanceof HTMLInputElement && target instanceof HTMLInputElement) {
      target.setAttribute('value', source.value || '');
      if (source.checked) target.setAttribute('checked', 'checked');
      else target.removeAttribute('checked');
    } else if (source instanceof HTMLTextAreaElement && target instanceof HTMLTextAreaElement) {
      target.textContent = source.value || '';
    } else if (source instanceof HTMLOptionElement && target instanceof HTMLOptionElement) {
      if (source.selected) target.setAttribute('selected', 'selected');
      else target.removeAttribute('selected');
    }
    return target;
  };
  const clone = cloneTree(document.documentElement) || document.createElement('html');
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  for (let index = 0; index < pairs.length && index < 1600; index += 1) {
    const [source, target] = pairs[index];
    if (!target || !source || target.nodeType !== Node.ELEMENT_NODE) continue;
    if (!visible(source) && target.tagName !== 'HTML' && target.tagName !== 'BODY' && target.tagName !== 'HEAD') {
      target.setAttribute('data-pa-hidden', 'true');
      target.setAttribute('style', 'display:none !important');
      continue;
    }
    const style = window.getComputedStyle(source);
    const inline = [];
    for (const prop of important) {
      const value = style.getPropertyValue(prop);
      if (value) inline.push(`${prop}:${value}`);
    }
    target.setAttribute('style', inline.join(';'));
  }
  clone.querySelectorAll('[data-pa-hidden="true"]').forEach((node) => node.remove());
  const head = clone.querySelector('head') || clone.insertBefore(document.createElement('head'), clone.firstChild);
  head.querySelectorAll('link[rel~="stylesheet"],style[data-personagent-embedded-css]').forEach((node) => node.remove());
  const base = document.createElement('base');
  base.href = url || document.baseURI || window.location.href;
  head.insertBefore(base, head.firstChild);
  const marker = document.createElement('meta');
  marker.setAttribute('name', 'personagent-css-fidelity');
  marker.setAttribute('content', 'computed');
  head.appendChild(marker);
  return '<!doctype html>\n' + clone.outerHTML;
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


def _search_results_script(provider: str) -> str:
    if provider == "yahoo":
        return _YAHOO_RESULTS_SCRIPT
    if provider == "bing":
        return _BING_RESULTS_SCRIPT
    if provider == "google":
        return _GOOGLE_RESULTS_SCRIPT
    return _GENERIC_RESULTS_SCRIPT


class LightPandaBrowserWorker:
    """Keeps one CDP browser connection and per-conversation pages."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_ms: int = 30_000,
        search_base_url: str = _DEFAULT_SEARCH_BASE_URL,
        session_ttl_seconds: int = 900,
        max_sessions: int = 32,
        auto_start_lightpanda: bool = True,
        connector: Connector | None = None,
    ) -> None:
        self.enabled = enabled
        self.cdp_url = cdp_url
        self.timeout_ms = max(1, int(timeout_ms))
        self.search_base_url = search_base_url or _DEFAULT_SEARCH_BASE_URL
        self.search_provider = _infer_search_provider(self.search_base_url)
        self.session_ttl_seconds = max(1, int(session_ttl_seconds))
        self.max_sessions = max(1, int(max_sessions))
        self.auto_start_lightpanda = auto_start_lightpanda
        self._connector = connector
        self._lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._container_start_lock = asyncio.Lock()
        self._container_start_attempted = False
        self._playwright: Any | None = None
        self._sessions: dict[str, _BrowserSession] = {}
        self._search_cache: dict[str, list[BrowserSearchSnapshot]] = {}
        self._current_url_cache: dict[str, str] = {}
        self._last_open_cache: dict[str, BrowserOpenedPage] = {}
        self._opened_pages_cache: dict[str, list[BrowserOpenedPage]] = {}
        self._element_map_cache: dict[str, list[dict[str, Any]]] = {}
        self._stylesheet_cache: dict[str, tuple[float, str]] = {}
        self._console_cache: dict[str, dict[str, list[BrowserConsoleEntry]]] = {}
        self._console_sequence = 0
        self._console_listener_keys: set[tuple[str, str, int]] = set()

    async def warmup(self) -> bool:
        """Best-effort startup connection. Failures are logged, not raised."""

        try:
            browser = await self._connect_browser()
        except BrowserError as exc:
            logger.warning("lightpanda_warmup_failed", error=str(exc))
            return False
        await self._release_browser(browser)
        return True

    async def close(self) -> None:
        """Close pages, contexts, browser and Playwright runtime."""

        async with self._lock:
            await self._close_sessions()
            if self._playwright is not None:
                await self._best_effort_resource_call(
                    "playwright_stop",
                    self._playwright.stop,
                )
                self._playwright = None
            self._search_cache.clear()
            self._current_url_cache.clear()
            self._last_open_cache.clear()
            self._opened_pages_cache.clear()
            self._stylesheet_cache.clear()
            self._console_cache.clear()
            self._console_listener_keys.clear()

    @property
    def search_provider_label(self) -> str:
        return {
            "yahoo": "Yahoo",
            "bing": "Bing",
            "google": "Google",
            "generic": "the configured search provider",
        }.get(self.search_provider, self.search_provider)

    async def search(
        self,
        *,
        conversation_id: str,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        """Search the configured search provider in the conversation browser session."""

        session = await self._get_session(conversation_id)
        search_url = self.search_url(query, max_results=max_results)
        resolved_search_url = search_url
        search_page = await self._new_session_page(session)
        if search_page is not None:
            try:
                await self._goto_page(search_page, search_url)
                await self._raise_if_search_blocked(search_page)
                extracted = await self._evaluate_page(
                    search_page,
                    _search_results_script(self.search_provider),
                    {"maxResults": max_results},
                )
                resolved_search_url = str(getattr(search_page, "url", search_url) or search_url)
            finally:
                if search_page is not session.page:
                    await self._best_effort_resource_call(
                        "browser_search_page_close",
                        search_page.close,
                    )
        else:
            expression = (
                f"({_search_results_script(self.search_provider)})"
                f"({json.dumps({'maxResults': max_results})})"
            )
            extracted = await self._raw_runtime_evaluate_value(
                search_url,
                expression,
                label="search_results",
                timeout=min(self.timeout_ms / 1000, 12),
            )
        results = [
            BrowserSearchResult(
                index=index + 1,
                title=str(item.get("title") or "").strip(),
                url=_clean_browser_url(str(item.get("url") or "")),
                snippet=str(item.get("snippet") or "").strip(),
            )
            for index, item in enumerate(extracted or [])
            if isinstance(item, dict)
            and item.get("title")
            and _clean_browser_url(str(item.get("url") or ""))
        ][:max_results]
        snapshot = self._cache_search_results(
            conversation_id=conversation_id,
            query=query,
            search_url=resolved_search_url,
            results=results,
        )
        session.search_results = self._copy_search_results(snapshot.results)
        session.current_url = resolved_search_url
        self._remember_current_url(conversation_id, session.current_url)
        session.touch()
        return {
            "type": "browser_search",
            "provider": self.search_provider,
            "query": query,
            "search_url": resolved_search_url,
            "search_id": snapshot.search_id,
            "cached_search_count": len(self._search_cache.get(conversation_id, [])),
            "results": [
                {**result.to_dict(), "search_id": snapshot.search_id} for result in snapshot.results
            ],
        }

    async def open(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        result_index: int | None = None,
        search_id: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        """Open a URL or one of the last search results."""

        session = await self._get_session(conversation_id)
        target_url = _clean_browser_url(url) if isinstance(url, str) else url
        matched_search_id = None
        matched_search_title = ""
        if target_url is None and result_index is not None:
            target_url, matched_search_id = self._result_url(
                conversation_id,
                session,
                result_index,
                search_id=search_id,
            )
            matched_search_title = self._result_title(
                conversation_id,
                result_index,
                search_id=matched_search_id or search_id,
            )
        elif target_url and search_id:
            matched_search_id = self._match_search_result_url(
                conversation_id,
                target_url,
                search_id=search_id,
            )
            if matched_search_id:
                matched_search_title = self._match_search_result_title(
                    conversation_id,
                    target_url,
                    search_id=matched_search_id,
                )
        if target_url is None:
            raise BrowserError("BrowserOpen requires url or result_index.")
        page = await self._new_session_page(session)
        close_failed_page = page is not None
        if page is None:
            page = self._preferred_session_page(session)
        try:
            await self._goto_page(page, target_url, allow_partial=True)
            await self._raise_if_search_blocked(page)
        except Exception:
            if close_failed_page:
                await self._best_effort_resource_call("browser_open_failed_page_close", page.close)
            raise
        title = await self._safe_title(page)
        if not title:
            title = matched_search_title
        final_url = str(getattr(page, "url", target_url) or target_url)
        session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        opened_page = self._cache_opened_page(
            conversation_id=conversation_id,
            url=target_url,
            final_url=final_url,
            title=title,
            source_search_id=matched_search_id,
            opener_tool_call_id=tool_call_id,
        )
        session.pages[opened_page.page_id] = page
        session.page = page
        session.last_open_url = opened_page.final_url
        session.last_open_page_id = opened_page.page_id
        session.current_page_id = opened_page.page_id
        self._attach_page_console_listeners(conversation_id, opened_page.page_id, page)
        session.touch()
        return {
            "type": "browser_open",
            "url": target_url,
            "final_url": final_url,
            "title": title,
            "search_id": matched_search_id,
            "page_id": opened_page.page_id,
            "window_id": opened_page.window_id,
            "opened_page_count": len(self._opened_pages_cache.get(conversation_id, [])),
            "recent_opened_pages": [
                page.to_dict() for page in self._opened_pages_cache.get(conversation_id, [])[:5]
            ],
        }

    async def extract_content(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
        include_links: bool,
    ) -> dict[str, Any]:
        """Return organized markdown/text content for the current or provided URL."""

        session = self._cached_usable_session(conversation_id)
        target_url, target_page_id = self._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._get_session(conversation_id)
            target_url, target_page_id = self._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        if session is None and url and not target_page_id:
            session = await self._get_session(conversation_id)
        final_url = _clean_browser_url(str(target_url))
        page = await self._content_page_for_target(
            conversation_id=conversation_id,
            session=session,
            target_url=final_url,
            target_page_id=target_page_id,
            allow_navigation=bool(url and not target_page_id),
        )
        title = self._target_title(conversation_id, target_page_id)
        if page is not None:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                final_url = page_url
            if not title:
                title = await self._safe_title(page)
            content, extraction_method, content_cleanup = await self._markdown_or_text_page(
                page,
                fallback_url=final_url,
            )
        else:
            if not title and session is not None:
                title = await self._safe_title(session.page)
            content, extraction_method, content_cleanup = await self._markdown_or_text_url(
                final_url
            )
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars].rstrip()
        links = self._extract_links_from_content(content) if include_links else []
        buttons: list[dict[str, str]] = []
        if session is not None:
            session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        opened_page = self._opened_page(conversation_id, target_page_id) if target_page_id else None
        if opened_page is not None:
            if session is not None:
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
            self._mark_opened_page_extracted(opened_page)
        if session is not None:
            session.touch()
        return {
            "type": "browser_extract_content",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "content": content,
            "extraction_method": extraction_method,
            "content_cleanup": content_cleanup,
            "links": links,
            "buttons": buttons,
            "truncated": truncated,
        }

    async def get_html(
        self,
        *,
        conversation_id: str,
        url: str | None = None,
        page_id: str | None = None,
        max_chars: int,
    ) -> dict[str, Any]:
        """Return raw HTML for the current or provided URL."""

        session = self._cached_usable_session(conversation_id)
        target_url, target_page_id = self._resolve_content_target(
            conversation_id,
            session,
            url=url,
            page_id=page_id,
        )
        if not target_url:
            session = await self._get_session(conversation_id)
            target_url, target_page_id = self._resolve_content_target(
                conversation_id,
                session,
                url=url,
                page_id=page_id,
            )
        if not target_url:
            raise BrowserError("No browser page selected. Run BrowserOpen or provide a URL.")
        if session is None and url and not target_page_id:
            session = await self._get_session(conversation_id)
        final_url = _clean_browser_url(str(target_url))
        page = await self._content_page_for_target(
            conversation_id=conversation_id,
            session=session,
            target_url=final_url,
            target_page_id=target_page_id,
            allow_navigation=bool(url and not target_page_id),
        )
        title = self._target_title(conversation_id, target_page_id)
        if page is not None:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                final_url = page_url
            if not title:
                title = await self._safe_title(page)
            html, html_method = await self._html_or_empty_page(page, fallback_url=final_url)
        else:
            if not title and session is not None:
                title = await self._safe_title(session.page)
            html, html_method = await self._html_or_empty_url(final_url)
        truncated = len(html) > max_chars
        if truncated:
            html = html[:max_chars].rstrip()
        if session is not None:
            session.current_url = final_url
        self._remember_current_url(conversation_id, final_url)
        if session is not None and target_page_id:
            opened_page = self._opened_page(conversation_id, target_page_id)
            if opened_page is not None:
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
        if session is not None:
            session.touch()
        return {
            "type": "browser_get_html",
            "url": final_url,
            "title": title,
            "page_id": target_page_id,
            "window_id": target_page_id,
            "html": html,
            "html_method": html_method,
            "truncated": truncated,
        }

    async def list_tabs(
        self,
        *,
        conversation_id: str,
        max_tabs: int,
    ) -> dict[str, Any]:
        """Return logical browser tabs opened during the conversation."""

        await self._cleanup_sessions()
        max_tabs = min(max(1, int(max_tabs)), 50)
        session = self._sessions.get(conversation_id)
        current_url = self._current_url_cache.get(conversation_id)
        if session is not None:
            current_url = session.current_url or current_url
        last_open = self._last_open_cache.get(conversation_id)
        pages = self._opened_pages_cache.get(conversation_id, [])[:max_tabs]
        tabs = [
            self._opened_page_tab(
                page,
                index=index,
                current_url=current_url,
                last_open_page_id=last_open.page_id if last_open is not None else None,
            )
            for index, page in enumerate(pages, start=1)
        ]
        return {
            "type": "browser_tabs",
            "tab_count": len(tabs),
            "max_tabs": max_tabs,
            "current_url": current_url,
            "last_open_page_id": last_open.page_id if last_open is not None else None,
            "last_open_window_id": last_open.window_id if last_open is not None else None,
            "tabs": tabs,
        }

    async def view_snapshot(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Return a real LightPanda-rendered screenshot for a session-panel browser."""

        session = await self._get_session(browser_id)
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_navigate(
        self,
        *,
        browser_id: str,
        url: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Navigate the session-panel browser and return the rendered view."""

        session = await self._get_session(browser_id)
        target_url = _normalize_navigation_url(url)
        await self._goto(browser_id, session, target_url, allow_partial=True)
        final_url = _clean_browser_url(str(getattr(session.page, "url", target_url) or target_url))
        session.current_url = final_url
        session.last_open_url = final_url
        self._remember_current_url(browser_id, final_url)
        session.touch()
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_history(
        self,
        *,
        browser_id: str,
        direction: int,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Move the session-panel browser back or forward in its real page history."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        operation = getattr(page, "go_back" if direction < 0 else "go_forward", None)
        if not callable(operation):
            raise BrowserUnavailableError("LightPanda history navigation is unavailable.")
        with suppress(Exception):
            await operation(wait_until="domcontentloaded", timeout=self.timeout_ms)
        with suppress(Exception):
            await page.wait_for_timeout(250)
        final_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if final_url:
            session.current_url = final_url
            session.last_open_url = final_url
            self._remember_current_url(browser_id, final_url)
        session.touch()
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_reload(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Reload the current session-panel browser page and return the rendered view."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        current_url = _clean_browser_url(
            str(getattr(page, "url", "") or session.current_url or session.last_open_url or "")
        )
        operation = getattr(page, "reload", None)
        if callable(operation):
            try:
                await operation(wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as exc:
                if current_url.startswith(("http://", "https://")):
                    logger.warning("lightpanda_reload_falling_back_to_goto", url=current_url, error=str(exc))
                    await self._goto_page(page, current_url, allow_partial=True)
                else:
                    raise BrowserUnavailableError("LightPanda reload is unavailable.") from exc
        elif current_url.startswith(("http://", "https://")):
            await self._goto_page(page, current_url, allow_partial=True)
        else:
            raise BrowserUnavailableError("LightPanda reload is unavailable.")
        with suppress(Exception):
            await page.wait_for_timeout(250)
        session.touch()
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_click(
        self,
        *,
        browser_id: str,
        x: float,
        y: float,
        width: int,
        height: int,
        button: str = "left",
    ) -> dict[str, Any]:
        """Click within the rendered session-panel browser viewport."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._set_page_viewport(page, viewport_width, viewport_height)
        mouse = getattr(page, "mouse", None)
        click = getattr(mouse, "click", None)
        if not callable(click):
            raise BrowserUnavailableError("LightPanda pointer interaction is unavailable.")
        safe_button = button if button in {"left", "middle", "right"} else "left"
        await click(
            min(max(float(x), 0.0), float(viewport_width)),
            min(max(float(y), 0.0), float(viewport_height)),
            button=safe_button,
        )
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
        with suppress(Exception):
            await page.wait_for_timeout(250)
        session.touch()
        return await self._browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
        )

    async def view_key(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
        text: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        """Type or press a key in the focused session-panel browser page."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        keyboard = getattr(page, "keyboard", None)
        if keyboard is None:
            raise BrowserUnavailableError("LightPanda keyboard interaction is unavailable.")
        if text:
            type_text = getattr(keyboard, "type", None)
            if not callable(type_text):
                raise BrowserUnavailableError("LightPanda text input is unavailable.")
            await type_text(text)
        elif key:
            press_key = getattr(keyboard, "press", None)
            if not callable(press_key):
                raise BrowserUnavailableError("LightPanda key input is unavailable.")
            await press_key(key)
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
        with suppress(Exception):
            await page.wait_for_timeout(120)
        session.touch()
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_scroll(
        self,
        *,
        browser_id: str,
        delta_x: float,
        delta_y: float,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Scroll the real session-panel browser page."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        mouse = getattr(page, "mouse", None)
        wheel = getattr(mouse, "wheel", None)
        if callable(wheel):
            await wheel(float(delta_x), float(delta_y))
        else:
            await self._evaluate_page(
                page,
                "([deltaX, deltaY]) => window.scrollBy(deltaX, deltaY)",
                [float(delta_x), float(delta_y)],
            )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        session.touch()
        return await self._browser_view_snapshot(browser_id, session, width=width, height=height)

    async def view_act(
        self,
        *,
        browser_id: str,
        node_id: str,
        action: str,
        width: int,
        height: int,
        value: str | None = None,
        key: str | None = None,
        target_node_id: str | None = None,
        timeout_ms: int | None = None,
        files: list[str] | None = None,
        text: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        """Execute a mapped DOM action and return the updated browser workspace view."""

        normalized_node_id = str(node_id or "").strip()
        normalized_action = str(action or "").strip().lower()
        if not normalized_node_id:
            raise BrowserError("BrowserAct requires node_id.")
        supported_actions = {
            "click",
            "fill",
            "submit",
            "select",
            "press",
            "hover",
            "wait",
            "drag",
            "drop",
            "upload",
            "select_text",
            "scroll_to",
            "screenshot",
        }
        if normalized_action not in supported_actions:
            raise BrowserError(f"BrowserAct action must be one of: {', '.join(sorted(supported_actions))}.")
        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._set_page_viewport(page, viewport_width, viewport_height)
        # The snapshot step injects stable data-pa-node-id attributes. Re-inject before acting
        # so agent tools can act after a fresh BrowserOpen without a visible UI snapshot.
        raw_map = await self._browser_element_map(page)
        self._element_map_cache[browser_id] = self._enrich_browser_element_map(
            raw_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        target = self._element_target(browser_id, normalized_node_id)
        target_action = self._element_target(browser_id, str(target_node_id or "").strip())
        cached_selector = str(target.get("selector") or "")
        target_selector = str(target_action.get("selector") or "")
        action_context = await self._action_context_for_element(page, target)
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if normalized_action == "upload":
            result = await self._upload_files(action_context, cached_selector, files or [])
        else:
            result = await self._evaluate_page(
                action_context,
                _BROWSER_ACT_SCRIPT,
                {
                    "nodeId": normalized_node_id,
                    "selector": cached_selector,
                    "shadowPath": target.get("shadow_path") if isinstance(target.get("shadow_path"), list) else [],
                    "action": normalized_action,
                    "value": value,
                    "key": key,
                    "targetSelector": target_selector,
                    "targetShadowPath": target_action.get("shadow_path")
                    if isinstance(target_action.get("shadow_path"), list)
                    else [],
                    "timeoutMs": timeout_ms,
                    "text": text,
                    "x": x,
                    "y": y,
                },
            )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        navigated = bool(after_url and after_url != before_url)
        if (not isinstance(result, Mapping) or not result.get("ok")) and not navigated:
            reason = ""
            if isinstance(result, Mapping):
                reason = str(result.get("reason") or "")
            raise BrowserError(reason or "Browser action failed.")
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
        with suppress(Exception):
            await page.wait_for_timeout(250)
        session.touch()
        view = await self._browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
        )
        view["last_action"] = {
            "node_id": normalized_node_id,
            "action": normalized_action,
            "value": value if normalized_action in {"fill", "select"} else None,
            "key": key if normalized_action == "press" else None,
            "target_node_id": target_node_id,
            "timeout_ms": timeout_ms,
            "files": files if normalized_action == "upload" else None,
            "text": text if normalized_action == "select_text" else None,
            "result": dict(result) if isinstance(result, Mapping) else result,
        }
        return view

    async def click(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        node_id: str | None = None,
        x: float | None = None,
        y: float | None = None,
        width: int = 1024,
        height: int = 720,
        button: str = "left",
        click_count: int = 1,
        modifiers: list[str] | None = None,
        wait_after_ms: int = 250,
    ) -> dict[str, Any]:
        """Click a mapped element or viewport coordinate on a live browser page."""

        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        safe_wait_ms = min(max(int(wait_after_ms), 0), 10_000)
        if node_id:
            view = await self.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="click",
                width=viewport_width,
                height=viewport_height,
            )
        else:
            if x is None or y is None:
                raise BrowserError("BrowserClick requires node_id or x/y coordinates.")
            await self._set_page_viewport(page, viewport_width, viewport_height)
            mouse = getattr(page, "mouse", None)
            click = getattr(mouse, "click", None)
            if not callable(click):
                raise BrowserUnavailableError("Browser pointer interaction is unavailable.")
            safe_button = button if button in {"left", "middle", "right"} else "left"
            kwargs = {
                "button": safe_button,
                "click_count": min(max(int(click_count), 1), 3),
            }
            if modifiers:
                keyboard = getattr(page, "keyboard", None)
                for modifier in modifiers:
                    down = getattr(keyboard, "down", None)
                    if callable(down):
                        with suppress(Exception):
                            await down(str(modifier))
                try:
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
                finally:
                    for modifier in reversed(modifiers):
                        up = getattr(keyboard, "up", None)
                        if callable(up):
                            with suppress(Exception):
                                await up(str(modifier))
            else:
                try:
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
                except TypeError:
                    kwargs.pop("click_count", None)
                    await click(
                        min(max(float(x), 0.0), float(viewport_width)),
                        min(max(float(y), 0.0), float(viewport_height)),
                        **kwargs,
                    )
            with suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
            if safe_wait_ms:
                with suppress(Exception):
                    await page.wait_for_timeout(safe_wait_ms)
            session.touch()
            view = await self._browser_view_snapshot(
                conversation_id,
                session,
                width=viewport_width,
                height=viewport_height,
            )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or view.get("url") or ""))
        view.update(
            {
                "type": "browser_click",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": bool(after_url and before_url and after_url != before_url),
                "last_action": {
                    "action": "click",
                    "node_id": node_id,
                    "x": x,
                    "y": y,
                    "button": button,
                    "click_count": min(max(int(click_count), 1), 3),
                    "modifiers": modifiers or [],
                },
            }
        )
        return view

    async def type_input(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        node_id: str | None = None,
        mode: str = "type",
        text: str | None = None,
        key: str | None = None,
        clear: bool = False,
        delay_ms: int = 0,
        submit: bool = False,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        """Type, fill, or press keys on a live browser page."""

        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        normalized_mode = str(mode or "type").strip().lower()
        if normalized_mode not in {"type", "fill", "press"}:
            raise BrowserError("BrowserType mode must be one of: type, fill, press.")
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if node_id and normalized_mode == "fill":
            view = await self.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="fill",
                value=text or "",
                width=viewport_width,
                height=viewport_height,
            )
        elif node_id and normalized_mode == "press":
            view = await self.view_act(
                browser_id=conversation_id,
                node_id=node_id,
                action="press",
                key=key or text or "",
                width=viewport_width,
                height=viewport_height,
            )
        else:
            await self._set_page_viewport(page, viewport_width, viewport_height)
            if node_id:
                await self.view_act(
                    browser_id=conversation_id,
                    node_id=node_id,
                    action="click",
                    width=viewport_width,
                    height=viewport_height,
                )
            keyboard = getattr(page, "keyboard", None)
            if keyboard is None:
                raise BrowserUnavailableError("Browser keyboard interaction is unavailable.")
            if clear:
                press_key = getattr(keyboard, "press", None)
                if callable(press_key):
                    with suppress(Exception):
                        await press_key("Control+A")
                    with suppress(Exception):
                        await press_key("Backspace")
            if normalized_mode == "press":
                press_key = getattr(keyboard, "press", None)
                if not callable(press_key):
                    raise BrowserUnavailableError("Browser key input is unavailable.")
                await press_key(key or text or "")
            elif text:
                type_text = getattr(keyboard, "type", None)
                if not callable(type_text):
                    raise BrowserUnavailableError("Browser text input is unavailable.")
                delay = min(max(int(delay_ms), 0), 1_000)
                try:
                    await type_text(text, delay=delay)
                except TypeError:
                    await type_text(text)
            if submit:
                press_key = getattr(keyboard, "press", None)
                if callable(press_key):
                    await press_key("Enter")
            with suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
            with suppress(Exception):
                await page.wait_for_timeout(120)
            session.touch()
            view = await self._browser_view_snapshot(
                conversation_id,
                session,
                width=viewport_width,
                height=viewport_height,
            )
        if submit and node_id and normalized_mode in {"fill", "press"}:
            keyboard = getattr(session.page, "keyboard", None)
            press_key = getattr(keyboard, "press", None)
            if callable(press_key):
                with suppress(Exception):
                    await press_key("Enter")
                with suppress(Exception):
                    await session.page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5_000))
                with suppress(Exception):
                    await session.page.wait_for_timeout(120)
                view = await self._browser_view_snapshot(
                    conversation_id,
                    session,
                    width=viewport_width,
                    height=viewport_height,
                )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or view.get("url") or ""))
        view.update(
            {
                "type": "browser_type",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": bool(after_url and before_url and after_url != before_url),
                "last_action": {
                    "action": normalized_mode,
                    "node_id": node_id,
                    "text": text if normalized_mode in {"type", "fill"} else None,
                    "key": key if normalized_mode == "press" else None,
                    "clear": bool(clear),
                    "submit": bool(submit),
                },
            }
        )
        return view

    async def screenshot(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        width: int = 1024,
        height: int = 720,
        full_page: bool = False,
        image_format: str = "png",
        quality: int | None = None,
    ) -> dict[str, Any]:
        """Capture a page screenshot or return the controlled DOM-mirror fallback."""

        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._set_page_viewport(page, viewport_width, viewport_height)
        title, user_agent, raw_element_map, html = await asyncio.gather(
            self._safe_title(page),
            self._safe_user_agent(page),
            self._browser_element_map(page),
            self._safe_html(page),
        )
        current_url = _clean_browser_url(str(getattr(page, "url", "") or "about:blank"))
        runtime = "lightpanda" if user_agent.lower().startswith("lightpanda/") else "chrome_cdp"
        render_mode = "html_mirror"
        image_data = ""
        image_error = ""
        screenshot_method = ""
        requested_format = str(image_format or "png").lower()
        if requested_format not in {"png", "jpeg"}:
            requested_format = "png"
        if runtime == "lightpanda":
            image_error = "LightPanda has no graphical rendering engine; using DOM mirror."
        else:
            try:
                screenshot = getattr(page, "screenshot", None)
                if not callable(screenshot):
                    raise BrowserUnavailableError("Page screenshot capture is unavailable.")
                kwargs: dict[str, Any] = {
                    "type": requested_format,
                    "full_page": bool(full_page),
                }
                if requested_format == "jpeg" and quality is not None:
                    kwargs["quality"] = min(max(int(quality), 1), 100)
                raw_image = await asyncio.wait_for(
                    screenshot(**kwargs),
                    timeout=min(max(self.timeout_ms / 1000, 1.0), 10.0),
                )
                image_data = base64.b64encode(raw_image).decode("ascii")
                render_mode = "pixel"
                screenshot_method = "playwright_page_screenshot"
            except Exception as exc:
                image_error = str(exc)
                logger.warning("browser_control_screenshot_failed", error=image_error)
        element_map = self._enrich_browser_element_map(
            raw_element_map,
            browser_id=conversation_id,
            tab_id=resolved_page_id,
        )
        self._element_map_cache[conversation_id] = element_map
        session.current_url = current_url or session.current_url
        session.touch()
        return {
            "type": "browser_screenshot",
            "page_id": resolved_page_id,
            "window_id": resolved_page_id,
            "url": current_url,
            "title": title,
            "runtime": runtime,
            "render_mode": render_mode,
            "active_tab_id": session.current_page_id or resolved_page_id,
            "navigated": False,
            "image_data": image_data,
            "image_mime_type": f"image/{requested_format}" if image_data else "",
            "screenshot_method": screenshot_method,
            "screenshot_error": image_error,
            "can_capture": bool(image_data),
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "full_page": bool(full_page),
            "html": html if not image_data else "",
            "document_html": html if not image_data else "",
            "element_map": element_map[:80],
        }

    async def close_tab(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        max_tabs: int = 20,
    ) -> dict[str, Any]:
        """Close one logical browser tab and return the updated tab list."""

        session = await self._get_session(conversation_id)
        target_page_id = str(page_id or session.current_page_id or session.last_open_page_id or "").strip()
        if not target_page_id:
            last_open = self._last_open_cache.get(conversation_id)
            target_page_id = last_open.page_id if last_open is not None else ""
        if not target_page_id:
            raise BrowserError("No browser page selected. Run BrowserOpen first.")
        live_page = session.pages.pop(target_page_id, None)
        closed = False
        if live_page is not None:
            await self._best_effort_resource_call("browser_control_close_page", live_page.close)
            closed = True
        pages = self._opened_pages_cache.get(conversation_id, [])
        remaining_pages = [opened_page for opened_page in pages if opened_page.page_id != target_page_id]
        self._opened_pages_cache[conversation_id] = remaining_pages
        if self._last_open_cache.get(conversation_id) is not None and self._last_open_cache[conversation_id].page_id == target_page_id:
            if remaining_pages:
                self._last_open_cache[conversation_id] = remaining_pages[0]
            else:
                self._last_open_cache.pop(conversation_id, None)
        self._console_cache.get(conversation_id, {}).pop(target_page_id, None)
        self._element_map_cache.pop(conversation_id, None)
        if session.current_page_id == target_page_id:
            next_page_id = next((candidate for candidate in session.pages if candidate != target_page_id), None)
            if next_page_id:
                session.current_page_id = next_page_id
                session.last_open_page_id = next_page_id
                session.page = session.pages[next_page_id]
            elif remaining_pages:
                session.current_page_id = remaining_pages[0].page_id
                session.last_open_page_id = remaining_pages[0].page_id
            else:
                session.current_page_id = None
                session.last_open_page_id = None
        session.touch()
        tabs = await self.list_tabs(conversation_id=conversation_id, max_tabs=max_tabs)
        tabs.update(
            {
                "type": "browser_close_tab",
                "closed_page_id": target_page_id,
                "closed_window_id": target_page_id,
                "closed": closed or len(remaining_pages) != len(pages),
            }
        )
        return tabs

    async def read_console(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        levels: list[str] | None = None,
        since_id: int | None = None,
        limit: int = 100,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Read a bounded ring buffer of captured console events for a browser page."""

        session = await self._get_session(conversation_id)
        target_page_id = str(page_id or session.current_page_id or session.last_open_page_id or "").strip()
        if not target_page_id:
            last_open = self._last_open_cache.get(conversation_id)
            target_page_id = last_open.page_id if last_open is not None else conversation_id
        page = session.pages.get(target_page_id) or self._preferred_session_page(session)
        with suppress(Exception):
            await self._drain_page_console_entries(page, conversation_id, target_page_id)
        allowed_levels = {str(level).lower() for level in levels or [] if str(level).strip()}
        page_entries = list(self._console_cache.get(conversation_id, {}).get(target_page_id, []))
        if since_id is not None:
            page_entries = [entry for entry in page_entries if entry.entry_id > int(since_id)]
        if allowed_levels:
            page_entries = [entry for entry in page_entries if entry.level.lower() in allowed_levels]
        safe_limit = min(max(int(limit), 1), _MAX_CONSOLE_ENTRIES_PER_PAGE)
        selected = page_entries[-safe_limit:]
        if clear:
            self._console_cache.get(conversation_id, {}).pop(target_page_id, None)
        return {
            "type": "browser_console",
            "page_id": target_page_id,
            "window_id": target_page_id,
            "url": _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "")),
            "title": await self._safe_title(page),
            "runtime": await self._page_runtime(page),
            "render_mode": "html_mirror" if await self._is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or target_page_id,
            "navigated": False,
            "entries": [entry.to_dict() for entry in selected],
            "next_since_id": selected[-1].entry_id if selected else since_id,
            "cleared": bool(clear),
        }

    async def script(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        mode: str = "evaluate",
        script: str | None = None,
        args: Any | None = None,
        cdp_method: str | None = None,
        cdp_params: dict[str, Any] | None = None,
        timeout_ms: int = 5_000,
    ) -> dict[str, Any]:
        """Run allowlisted page JS or selected CDP methods for advanced browser control."""

        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        normalized_mode = str(mode or "evaluate").strip().lower()
        safe_timeout_ms = min(max(int(timeout_ms), 1), 30_000)
        current_url = _clean_browser_url(str(getattr(page, "url", "") or session.current_url or "about:blank"))
        if normalized_mode == "evaluate":
            if not isinstance(script, str) or not script.strip():
                raise BrowserError("BrowserScript evaluate requires a non-empty script.")
            if len(script) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(f"BrowserScript script is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters.")
            value = await asyncio.wait_for(
                self._evaluate_page(page, script, args),
                timeout=safe_timeout_ms / 1000,
            )
            method = "Runtime.evaluate"
        elif normalized_mode == "cdp":
            method = str(cdp_method or "").strip()
            if method not in _BROWSER_SCRIPT_CDP_ALLOWLIST:
                raise BrowserError(
                    "BrowserScript cdp_method must be one of: "
                    + ", ".join(sorted(_BROWSER_SCRIPT_CDP_ALLOWLIST))
                    + "."
                )
            raw_params = cdp_params or {}
            if len(json.dumps(raw_params, ensure_ascii=False, default=str)) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript cdp_params is too large; max {_MAX_BROWSER_SCRIPT_CHARS} serialized characters."
                )
            expression = raw_params.get("expression") if isinstance(raw_params, dict) else None
            if isinstance(expression, str) and len(expression) > _MAX_BROWSER_SCRIPT_CHARS:
                raise BrowserError(
                    f"BrowserScript Runtime.evaluate expression is too large; max {_MAX_BROWSER_SCRIPT_CHARS} characters."
                )
            value = await asyncio.wait_for(
                self._cdp_command_for_page(
                    page,
                    url=current_url,
                    method=method,
                    params=raw_params,
                ),
                timeout=safe_timeout_ms / 1000,
            )
        else:
            raise BrowserError("BrowserScript mode must be one of: evaluate, cdp.")
        result_text, result, truncated = self._bounded_script_result(value)
        return {
            "type": "browser_script",
            "page_id": resolved_page_id,
            "window_id": resolved_page_id,
            "url": current_url,
            "title": await self._safe_title(page),
            "runtime": await self._page_runtime(page),
            "render_mode": "html_mirror" if await self._is_lightpanda_page(page) else "pixel",
            "active_tab_id": session.current_page_id or resolved_page_id,
            "navigated": False,
            "mode": normalized_mode,
            "cdp_method": method if normalized_mode == "cdp" else None,
            "result": result,
            "result_text": result_text,
            "truncated": truncated,
        }

    async def scroll(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        delta_x: float = 0.0,
        delta_y: float = 600.0,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        view = await self.view_scroll(
            browser_id=conversation_id,
            delta_x=delta_x,
            delta_y=delta_y,
            width=width,
            height=height,
        )
        view.update(
            {
                "type": "browser_scroll",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": False,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    async def reload(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        view = await self.view_reload(browser_id=conversation_id, width=width, height=height)
        view.update(
            {
                "type": "browser_reload",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "navigated": True,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    async def history(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        direction: int = -1,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, _page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        safe_direction = -1 if int(direction) < 0 else 1
        view = await self.view_history(
            browser_id=conversation_id,
            direction=safe_direction,
            width=width,
            height=height,
        )
        view.update(
            {
                "type": "browser_history",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "direction": safe_direction,
                "navigated": True,
                "active_tab_id": session.current_page_id or resolved_page_id,
            }
        )
        return view

    async def switch_tab(
        self,
        *,
        conversation_id: str,
        page_id: str,
        max_tabs: int = 20,
    ) -> dict[str, Any]:
        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        session.current_url = _clean_browser_url(str(getattr(page, "url", "") or session.current_url or ""))
        session.touch()
        tabs = await self.list_tabs(conversation_id=conversation_id, max_tabs=max_tabs)
        tabs.update(
            {
                "type": "browser_switch_tab",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "active_tab_id": resolved_page_id,
                "navigated": False,
            }
        )
        return tabs

    async def wait(
        self,
        *,
        conversation_id: str,
        page_id: str | None = None,
        timeout_ms: int = 1_000,
        state: str | None = None,
        width: int = 1024,
        height: int = 720,
    ) -> dict[str, Any]:
        session, page, resolved_page_id = await self._resolve_live_page(
            conversation_id,
            page_id=page_id,
            activate=True,
        )
        safe_timeout_ms = min(max(int(timeout_ms), 1), 120_000)
        state_value = str(state or "").strip()
        if state_value:
            wait_for_load_state = getattr(page, "wait_for_load_state", None)
            if callable(wait_for_load_state):
                with suppress(Exception):
                    await wait_for_load_state(state_value, timeout=safe_timeout_ms)
        else:
            with suppress(Exception):
                await page.wait_for_timeout(safe_timeout_ms)
        view = await self._browser_view_snapshot(conversation_id, session, width=width, height=height)
        view.update(
            {
                "type": "browser_wait",
                "page_id": resolved_page_id,
                "window_id": resolved_page_id,
                "timeout_ms": safe_timeout_ms,
                "state": state_value or None,
                "navigated": False,
            }
        )
        return view

    def search_url(self, query: str, *, max_results: int | None = None) -> str:
        parsed = urlparse(self.search_base_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if self.search_provider == "yahoo":
            params["p"] = query
            params.pop("q", None)
        else:
            params["q"] = query
        if self.search_provider == "google":
            params.update(
                {
                    "hl": params.get("hl") or "en",
                    "gl": params.get("gl") or "us",
                    "pws": params.get("pws") or "0",
                }
            )
        elif self.search_provider == "bing":
            params.update(
                {
                    "setlang": params.get("setlang") or "en-US",
                    "cc": params.get("cc") or "US",
                }
            )
        if max_results is not None:
            result_count = str(min(max(1, int(max_results)), 10))
            if self.search_provider == "bing":
                params["count"] = result_count
            elif self.search_provider == "yahoo":
                params["pz"] = result_count
            else:
                params["num"] = result_count
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(params),
                parsed.fragment,
            )
        )

    async def _browser_view_snapshot(
        self,
        browser_id: str,
        session: _BrowserSession,
        *,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        page = self._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._set_page_viewport(page, viewport_width, viewport_height)
        current_url = _clean_browser_url(str(getattr(page, "url", "") or "about:blank"))
        title, user_agent, raw_element_map, html = await asyncio.gather(
            self._safe_title(page),
            self._safe_user_agent(page),
            self._browser_element_map(page),
            self._safe_html(page),
        )
        element_map = self._enrich_browser_element_map(
            raw_element_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        self._element_map_cache[browser_id] = element_map
        html_from_fallback = False
        if not html.strip() and current_url.startswith(("http://", "https://")):
            html, _html_method = await self._html_or_empty_page(page, fallback_url=current_url)
            html_from_fallback = True
        if not html.strip() and current_url.startswith(("http://", "https://")):
            html = _browser_empty_fallback_html(current_url, title)
            html_from_fallback = True
        html, embedded_stylesheet_count = await self._html_with_embedded_stylesheet_fallbacks(
            html,
            current_url,
        )
        is_lightpanda = user_agent.lower().startswith("lightpanda/")
        image_data = ""
        image_error = ""
        if is_lightpanda:
            image_error = "LightPanda has no graphical rendering engine; using DOM mirror."
        else:
            try:
                screenshot = getattr(page, "screenshot", None)
                if not callable(screenshot):
                    raise BrowserUnavailableError("Page screenshot capture is unavailable.")
                raw_image = await asyncio.wait_for(
                    screenshot(type="png", full_page=False),
                    timeout=min(max(self.timeout_ms / 1000, 1.0), 10.0),
                )
                image_data = base64.b64encode(raw_image).decode("ascii")
            except Exception as exc:
                image_error = str(exc)
                logger.warning("lightpanda_browser_view_screenshot_failed", error=image_error)

        if current_url and current_url != "about:blank":
            session.current_url = current_url
            self._remember_current_url(browser_id, current_url)
        session.touch()
        render_mode = "html_mirror" if is_lightpanda or not image_data else "pixel"
        runtime = "lightpanda" if is_lightpanda else "chrome_cdp"
        css_fidelity = self._css_fidelity(
            html=html,
            render_mode=render_mode,
            embedded_stylesheet_count=embedded_stylesheet_count,
        )
        if html_from_fallback and css_fidelity == "original":
            css_fidelity = "fallback_html"
        if render_mode == "html_mirror" and css_fidelity == "fallback_html" and html.strip():
            computed_html = await self._computed_html_snapshot(page, current_url)
            if computed_html.strip():
                html = computed_html
                render_mode = "computed_html"
                css_fidelity = "computed"
        fallback_reason = (
            ""
            if css_fidelity in {"original", "pixel", "embedded", "computed"}
            else "Page HTML was captured, but original CSS could not be confirmed."
        )
        if css_fidelity == "computed":
            fallback_reason = "Original CSS was not confirmed; using a computed-style DOM snapshot."
        tabs = self._browser_tabs_snapshot(browser_id, session, current_url=current_url, title=title, runtime=runtime)
        active_tab_id = session.current_page_id or browser_id
        frame_tree = await self._browser_frame_tree_snapshot(page, current_url=current_url, title=title)
        browser_snapshot = {
            "document_html": html,
            "url": current_url,
            "title": title,
            "render_mode": render_mode,
            "runtime": runtime,
            "css_fidelity": css_fidelity,
            "fallback_reason": fallback_reason,
            "tabs": tabs,
            "active_tab_id": active_tab_id,
            "frame_tree": frame_tree,
            "element_map": element_map,
        }
        return {
            "type": "browser_view",
            "browser_id": browser_id,
            "url": current_url,
            "title": title,
            "html": html,
            "document_html": html,
            "render_mode": render_mode,
            "runtime": runtime,
            "css_fidelity": css_fidelity,
            "fallback_reason": fallback_reason,
            "tabs": tabs,
            "active_tab_id": active_tab_id,
            "frame_tree": frame_tree,
            "element_map": element_map,
            "annotations": [],
            "timeline_events": [],
            "browser_snapshot": browser_snapshot,
            "user_agent": user_agent,
            "image_data": image_data,
            "image_mime_type": "image/png" if image_data else "",
            "screenshot_method": "playwright_page_screenshot" if image_data else "",
            "screenshot_error": image_error,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "can_capture": bool(image_data),
        }

    def _enrich_browser_element_map(
        self,
        raw_map: list[dict[str, Any]],
        *,
        browser_id: str,
        tab_id: str,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for item in raw_map:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            selector = str(item.get("selector") or "")
            role = str(item.get("role") or "")
            text = str(item.get("text") or "")
            frame_id = str(item.get("frame_id") or "main")
            stable_key = str(item.get("stable_key") or f"{tab_id}|{frame_id}|{selector}|{role}|{text[:80]}")
            next_item = dict(item)
            next_item["node_id"] = node_id
            next_item["tab_id"] = str(item.get("tab_id") or tab_id or browser_id)
            next_item["frame_id"] = frame_id
            next_item["selector_chain"] = item.get("selector_chain") if isinstance(item.get("selector_chain"), list) else [selector]
            next_item["shadow_path"] = item.get("shadow_path") if isinstance(item.get("shadow_path"), list) else []
            next_item["stable_key"] = stable_key
            next_item["interactable"] = bool(
                item.get("interactable")
                or role in {"link", "button", "input", "textbox", "select", "form", "checkbox", "radio", "tab"}
            )
            if not isinstance(next_item.get("computed_summary"), dict):
                next_item["computed_summary"] = {}
            enriched.append(next_item)
            if len(enriched) >= 220:
                break
        return enriched

    def _browser_tabs_snapshot(
        self,
        browser_id: str,
        session: _BrowserSession,
        *,
        current_url: str,
        title: str,
        runtime: str,
    ) -> list[dict[str, Any]]:
        opened_pages = self._opened_pages_cache.get(browser_id, [])
        active_tab_id = session.current_page_id or browser_id
        tabs: list[dict[str, Any]] = []
        for index, opened_page in enumerate(opened_pages[:50], start=1):
            tabs.append(
                {
                    "tab_id": opened_page.page_id,
                    "id": opened_page.page_id,
                    "url": opened_page.final_url or opened_page.url,
                    "title": opened_page.title or title,
                    "runtime": runtime,
                    "active": opened_page.page_id == active_tab_id,
                    "is_active": opened_page.page_id == active_tab_id,
                    "history": [opened_page.final_url or opened_page.url],
                    "index": index,
                }
            )
        if not tabs:
            tabs.append(
                {
                    "tab_id": active_tab_id,
                    "id": active_tab_id,
                    "url": current_url,
                    "title": title,
                    "runtime": runtime,
                    "active": True,
                    "is_active": True,
                    "history": [current_url] if current_url and current_url != "about:blank" else [],
                    "index": 1,
                }
            )
        return tabs

    async def _browser_element_map(self, page: Any) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        with suppress(Exception):
            value = await self._evaluate_page(
                page,
                _BROWSER_ELEMENT_MAP_SCRIPT,
                {"frameId": "main", "frameUrl": str(getattr(page, "url", "") or "")},
            )
            if isinstance(value, list):
                mapped.extend(
                    item
                    for item in value
                    if isinstance(item, dict) and isinstance(item.get("node_id"), str)
                )
        mapped.extend(await self._browser_iframe_element_map(page))
        return mapped[:500]

    async def _browser_iframe_element_map(self, page: Any) -> list[dict[str, Any]]:
        frames = await self._page_frames(page)
        if len(frames) <= 1:
            return []
        main_frame = self._main_frame(page)
        mapped: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if frame is main_frame:
                continue
            frame_id = self._frame_id(frame, index)
            offset = await self._frame_viewport_offset(frame)
            with suppress(Exception):
                evaluate = getattr(frame, "evaluate", None)
                if not callable(evaluate):
                    continue
                value = evaluate(
                    _BROWSER_ELEMENT_MAP_SCRIPT,
                    {
                        "frameId": frame_id,
                        "frameUrl": str(getattr(frame, "url", "") or ""),
                        "offsetX": offset[0],
                        "offsetY": offset[1],
                    },
                )
                if inspect.isawaitable(value):
                    value = await value
                if isinstance(value, list):
                    mapped.extend(
                        item
                        for item in value
                        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
                    )
            if len(mapped) >= 280:
                break
        return mapped[:280]

    async def _browser_frame_tree_snapshot(
        self,
        page: Any,
        *,
        current_url: str,
        title: str,
    ) -> list[dict[str, Any]]:
        frames = await self._page_frames(page)
        if not frames:
            return [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]
        main_frame = self._main_frame(page)
        tree: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            frame_id = "main" if frame is main_frame or index == 0 else self._frame_id(frame, index)
            parent_id = ""
            frame_url = str(getattr(frame, "url", "") or "")
            parent_frame = getattr(frame, "parent_frame", None)
            if callable(parent_frame):
                with suppress(Exception):
                    parent = parent_frame()
                    if parent is not None and parent is not main_frame:
                        parent_index = frames.index(parent) if parent in frames else 0
                        parent_id = self._frame_id(parent, parent_index)
                    elif parent is main_frame:
                        parent_id = "main"
            tree.append(
                {
                    "frame_id": frame_id,
                    "url": frame_url or (current_url if frame_id == "main" else ""),
                    "title": title if frame_id == "main" else "",
                    "parent_frame_id": parent_id,
                }
            )
        return tree or [{"frame_id": "main", "url": current_url, "title": title, "parent_frame_id": ""}]

    async def _html_with_embedded_stylesheet_fallbacks(
        self,
        html: str,
        current_url: str,
    ) -> tuple[str, int]:
        if not html or not current_url.startswith(("http://", "https://")):
            return html, 0
        hrefs = self._stylesheet_hrefs(html, current_url, max_hrefs=12)
        if not hrefs:
            return html, 0
        timeout = httpx.Timeout(1.8, connect=0.6)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            results = await asyncio.gather(
                *(self._fetch_stylesheet_css(client, href) for href in hrefs),
                return_exceptions=True,
            )
        embedded_styles = [
            f"/* PersonAgent embedded stylesheet fallback: {href} */\n{css_text}"
            for href, css_text in zip(hrefs, results, strict=False)
            if isinstance(css_text, str) and css_text.strip()
        ]
        if not embedded_styles:
            return html, 0
        style_block = (
            '<style data-personagent-embedded-css="true">\n'
            + "\n\n".join(embedded_styles)
            + "\n</style>"
        )
        if re.search(r"<head(\s[^>]*)?>", html, flags=re.IGNORECASE):
            return (
                re.sub(
                    r"<head(\s[^>]*)?>",
                    lambda match: f"{match.group(0)}{style_block}",
                    html,
                    count=1,
                    flags=re.IGNORECASE,
                ),
                len(embedded_styles),
            )
        return f"{style_block}{html}", len(embedded_styles)

    async def _computed_html_snapshot(self, page: Any, current_url: str) -> str:
        with suppress(Exception):
            value = await self._evaluate_page(
                page,
                _COMPUTED_HTML_SNAPSHOT_SCRIPT,
                {"url": current_url},
            )
            if isinstance(value, str):
                return value[:2_000_000]
        return ""

    @staticmethod
    def _stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
        hrefs: list[str] = []
        for tag_match in _LINK_TAG_PATTERN.finditer(html):
            attrs = LightPandaBrowserWorker._html_attrs(str(tag_match.group(0) or ""))
            href = str(attrs.get("href") or "").strip()
            if not href:
                continue
            rel = str(attrs.get("rel") or "").lower()
            as_attr = str(attrs.get("as") or "").lower()
            parsed_path = urlparse(href).path.lower()
            looks_like_stylesheet = (
                "stylesheet" in rel
                or as_attr == "style"
                or parsed_path.endswith(".css")
                or ".css" in parsed_path
            )
            if not looks_like_stylesheet:
                continue
            absolute = urljoin(current_url, href)
            if absolute.startswith(("http://", "https://")) and absolute not in hrefs:
                hrefs.append(absolute)
            if len(hrefs) >= max_hrefs:
                break
        return hrefs

    @staticmethod
    def _html_attrs(tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for match in _HTML_ATTR_PATTERN.finditer(tag):
            name = str(match.group("name") or "").lower()
            value = str(match.group("value") or "")
            if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
                value = value[1:-1]
            attrs[name] = value
        return attrs

    async def _fetch_stylesheet_css(self, client: httpx.AsyncClient, href: str) -> str:
        now = time.monotonic()
        cached = self._stylesheet_cache.get(href)
        if cached is not None and cached[0] > now:
            return cached[1]
        response = await client.get(href)
        if response.status_code >= 400:
            return ""
        content_type = response.headers.get("content-type", "")
        css_text = response.text
        if "css" not in content_type.lower() and "{" not in css_text[:1000]:
            return ""
        css_text = self._rewrite_css_urls(css_text[:350_000], href)
        self._stylesheet_cache[href] = (now + _STYLESHEET_CACHE_TTL_SECONDS, css_text)
        if len(self._stylesheet_cache) > _MAX_STYLESHEET_CACHE_ENTRIES:
            expired = [key for key, (expires_at, _) in self._stylesheet_cache.items() if expires_at <= now]
            for key in expired:
                self._stylesheet_cache.pop(key, None)
            while len(self._stylesheet_cache) > _MAX_STYLESHEET_CACHE_ENTRIES:
                self._stylesheet_cache.pop(next(iter(self._stylesheet_cache)))
        return css_text

    @staticmethod
    def _rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
        def replace(match: re.Match[str]) -> str:
            raw_url = str(match.group("url") or "").strip()
            quote = str(match.group("quote") or "")
            if not raw_url or raw_url.startswith(("data:", "http://", "https://", "#")):
                return match.group(0)
            return f"url({quote}{urljoin(stylesheet_url, raw_url)}{quote})"

        return _CSS_URL_PATTERN.sub(replace, css_text)

    @staticmethod
    def _css_fidelity(*, html: str, render_mode: str, embedded_stylesheet_count: int = 0) -> str:
        if render_mode in {"screenshot", "pixel"}:
            return "pixel"
        if render_mode == "computed_html":
            return "computed"
        if not html.strip():
            return "fallback_html"
        if embedded_stylesheet_count > 0:
            return "embedded"
        lowered = html.lower()
        if (
            'rel="stylesheet"' in lowered
            or "rel='stylesheet'" in lowered
            or "as=\"style\"" in lowered
            or "as='style'" in lowered
            or "<style" in lowered
        ):
            return "original"
        return "fallback_html"

    def _element_selector(self, browser_id: str, node_id: str) -> str:
        for item in self._element_map_cache.get(browser_id, []):
            if str(item.get("node_id") or "") == node_id:
                return str(item.get("selector") or "")
        return ""

    def _element_target(self, browser_id: str, node_id: str) -> dict[str, Any]:
        if not node_id:
            return {}
        for item in self._element_map_cache.get(browser_id, []):
            if str(item.get("node_id") or "") == node_id:
                return item
        return {}

    async def _action_context_for_element(self, page: Any, target: dict[str, Any]) -> Any:
        frame_id = str(target.get("frame_id") or "main")
        if frame_id == "main":
            return page
        frames = await self._page_frames(page)
        for index, frame in enumerate(frames):
            if self._frame_id(frame, index) == frame_id:
                return frame
        return page

    async def _page_frames(self, page: Any) -> list[Any]:
        frames_attr = getattr(page, "frames", None)
        if callable(frames_attr):
            with suppress(Exception):
                value = frames_attr()
                if inspect.isawaitable(value):
                    value = await value
                if isinstance(value, list):
                    return value
        if isinstance(frames_attr, list):
            return frames_attr
        return [page]

    def _main_frame(self, page: Any) -> Any:
        main_frame = getattr(page, "main_frame", None)
        if callable(main_frame):
            with suppress(Exception):
                return main_frame()
        if main_frame is not None:
            return main_frame
        return page

    def _frame_id(self, frame: Any, index: int) -> str:
        frame_url = str(getattr(frame, "url", "") or "")
        frame_name = ""
        name = getattr(frame, "name", None)
        with suppress(Exception):
            frame_name = str(name() if callable(name) else name or "")
        digest = hashlib.sha1(f"{index}|{frame_name}|{frame_url}".encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"frame_{digest}"

    async def _frame_viewport_offset(self, frame: Any) -> tuple[float, float]:
        frame_element = getattr(frame, "frame_element", None)
        if not callable(frame_element):
            return (0.0, 0.0)
        with suppress(Exception):
            element = frame_element()
            if inspect.isawaitable(element):
                element = await element
            bounding_box = getattr(element, "bounding_box", None)
            if not callable(bounding_box):
                return (0.0, 0.0)
            box = bounding_box()
            if inspect.isawaitable(box):
                box = await box
            if isinstance(box, Mapping):
                return (float(box.get("x") or 0.0), float(box.get("y") or 0.0))
        return (0.0, 0.0)

    async def _upload_files(self, page: Any, selector: str, files: list[str]) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "selector_not_found"}
        paths = [str(Path(path).expanduser()) for path in files if str(path or "").strip()]
        if not paths:
            return {"ok": False, "reason": "files_required"}
        locator = getattr(page, "locator", None)
        if not callable(locator):
            return {"ok": False, "reason": "locator_unavailable"}
        try:
            file_input = locator(selector).first
            if callable(file_input):
                file_input = file_input()
            set_input_files = getattr(file_input, "set_input_files", None)
            if not callable(set_input_files):
                return {"ok": False, "reason": "file_upload_unavailable"}
            result = set_input_files(paths)
            if inspect.isawaitable(result):
                await result
            return {"ok": True, "action": "upload", "file_count": len(paths)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    async def _drag_between_elements(
        self,
        page: Any,
        selector: str,
        *,
        target_selector: str,
        x: float | None,
        y: float | None,
    ) -> dict[str, Any]:
        if not selector:
            return {"ok": False, "reason": "selector_not_found"}
        mouse = getattr(page, "mouse", None)
        if mouse is None:
            return {"ok": False, "reason": "mouse_unavailable"}
        payload = await self._evaluate_page(
            page,
            """
            ({ selector, targetSelector, x, y }) => {
              const rectFor = (nextSelector) => {
                if (!nextSelector) return null;
                const el = document.querySelector(nextSelector);
                if (!el) return null;
                el.scrollIntoView({ block: 'center', inline: 'center' });
                const rect = el.getBoundingClientRect();
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
              };
              return {
                source: rectFor(selector),
                target: rectFor(targetSelector) || (
                  Number.isFinite(Number(x)) && Number.isFinite(Number(y))
                    ? { x: Number(x), y: Number(y) }
                    : null
                )
              };
            }
            """,
            {"selector": selector, "targetSelector": target_selector, "x": x, "y": y},
        )
        if not isinstance(payload, Mapping):
            return {"ok": False, "reason": "bounds_unavailable"}
        source = payload.get("source")
        target = payload.get("target")
        if not isinstance(source, Mapping) or not isinstance(target, Mapping):
            return {"ok": False, "reason": "drag_points_unavailable"}
        move = getattr(mouse, "move", None)
        down = getattr(mouse, "down", None)
        up = getattr(mouse, "up", None)
        if not (callable(move) and callable(down) and callable(up)):
            return {"ok": False, "reason": "drag_unavailable"}
        await move(float(source["x"]), float(source["y"]))
        await down()
        await move(float(target["x"]), float(target["y"]), steps=12)
        await up()
        return {"ok": True, "action": "drop"}

    async def _set_page_viewport(self, page: Any, width: int, height: int) -> None:
        operation = getattr(page, "set_viewport_size", None)
        if not callable(operation):
            return
        with suppress(Exception):
            result = operation({"width": int(width), "height": int(height)})
            if inspect.isawaitable(result):
                await result

    async def _safe_user_agent(self, page: Any) -> str:
        with suppress(Exception):
            value = await self._evaluate_page(page, "() => navigator.userAgent || ''")
            if isinstance(value, str):
                return value.strip()
        return ""

    async def _safe_html(self, page: Any) -> str:
        operation = getattr(page, "content", None)
        if not callable(operation):
            return ""
        with suppress(Exception):
            value = operation()
            if inspect.isawaitable(value):
                value = await asyncio.wait_for(
                    value,
                    timeout=min(max(self.timeout_ms / 1000, 1.0), 5.0),
                )
            if isinstance(value, str):
                return value[:2_000_000]
        return ""

    async def _get_session(self, conversation_id: str) -> _BrowserSession:
        async with self._sessions_lock:
            await self._cleanup_sessions()
            session = self._sessions.get(conversation_id)
            if session is not None:
                try:
                    browser_connected = True
                    is_connected = getattr(session.browser, "is_connected", None)
                    if callable(is_connected):
                        browser_connected = bool(is_connected())
                    if browser_connected and self._session_has_open_page(session):
                        session.page = self._preferred_session_page(session)
                        cached_results = self._latest_cached_search_results(conversation_id)
                        if cached_results:
                            session.search_results = cached_results
                        else:
                            session.search_results = []
                        session.current_url = session.current_url or self._current_url_cache.get(
                            conversation_id
                        )
                        last_open = self._last_open_cache.get(conversation_id)
                        if last_open is not None:
                            session.last_open_url = session.last_open_url or last_open.final_url
                            session.last_open_page_id = (
                                session.last_open_page_id or last_open.page_id
                            )
                        session.touch()
                        return session
                except Exception:
                    await self._close_session(conversation_id, session)
                    session = None
                if session is not None:
                    await self._close_session(conversation_id, session)

            browser = await self._connect_browser()
            try:
                context = await browser.new_context()
                new_pages_supported = True
                try:
                    page = await context.new_page()
                except Exception as exc:
                    if not _is_target_already_loaded_error(exc):
                        raise
                    page = self._first_open_context_page(context)
                    if page is None:
                        raise
                    new_pages_supported = False
                page.set_default_timeout(self.timeout_ms)
                last_open = self._last_open_cache.get(conversation_id)
                session = _BrowserSession(
                    browser=browser,
                    context=context,
                    page=page,
                    search_results=self._latest_cached_search_results(conversation_id),
                    current_url=self._current_url_cache.get(conversation_id),
                    last_open_url=last_open.final_url if last_open is not None else None,
                    last_open_page_id=last_open.page_id if last_open is not None else None,
                    current_page_id=last_open.page_id if last_open is not None else None,
                    new_pages_supported=new_pages_supported,
                )
                self._sessions[conversation_id] = session
                await self._enforce_session_limit()
                return session
            except Exception as exc:
                await self._release_browser(browser)
                raise BrowserUnavailableError(
                    f"Could not create a LightPanda browser session: {exc}"
                ) from exc

    async def _ensure_browser(self) -> Any:
        """Open one CDP browser connection.

        LightPanda currently does not behave like Chromium when many contexts are
        created on the same Playwright CDP connection. The worker therefore keeps
        the singleton at the worker level, but each conversation session owns its
        own CDP connection.
        """

        return await self._connect_browser()

    def _cached_usable_session(self, conversation_id: str) -> _BrowserSession | None:
        session = self._sessions.get(conversation_id)
        if session is None:
            return None
        try:
            browser_connected = True
            is_connected = getattr(session.browser, "is_connected", None)
            if callable(is_connected):
                browser_connected = bool(is_connected())
            if browser_connected and self._session_has_open_page(session):
                session.page = self._preferred_session_page(session)
                return session
        except Exception:
            pass
        self._sessions.pop(conversation_id, None)
        return None

    def _session_has_open_page(self, session: _BrowserSession) -> bool:
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return True
        return False

    def _preferred_session_page(self, session: _BrowserSession) -> Any:
        if session.current_page_id:
            page = session.pages.get(session.current_page_id)
            if page is not None:
                with suppress(Exception):
                    if not page.is_closed():
                        return page
        for page in self._session_pages(session):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return session.page

    def _session_pages(self, session: _BrowserSession) -> list[Any]:
        pages: list[Any] = []
        seen: set[int] = set()
        for page in (session.page, *session.pages.values()):
            marker = id(page)
            if marker in seen:
                continue
            seen.add(marker)
            pages.append(page)
        return pages

    async def _resolve_live_page(
        self,
        conversation_id: str,
        *,
        page_id: str | None = None,
        activate: bool = True,
    ) -> tuple[_BrowserSession, Any, str]:
        session = await self._get_session(conversation_id)
        target_page_id = str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or (self._last_open_cache.get(conversation_id).page_id if self._last_open_cache.get(conversation_id) else "")
            or ""
        ).strip()
        page = session.pages.get(target_page_id) if target_page_id else None
        if page is not None and not self._page_is_open(page):
            session.pages.pop(target_page_id, None)
            page = None
        if page is None and target_page_id:
            opened_page = self._opened_page(conversation_id, target_page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {target_page_id}. Run BrowserOpen first."
                )
            page = self._preferred_session_page(session)
            if not self._page_is_open(page):
                raise BrowserError(
                    f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                )
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            target_url = opened_page.final_url or opened_page.url
            if target_url.startswith(("http://", "https://")) and not _urls_equivalent(page_url, target_url):
                await self._goto_page(page, target_url, allow_partial=True)
            session.pages[target_page_id] = page
        if page is None:
            page = self._preferred_session_page(session)
            if not self._page_is_open(page):
                raise BrowserError("No live browser page is available. Run BrowserOpen first.")
            target_page_id = target_page_id or session.current_page_id or session.last_open_page_id or conversation_id
        if activate:
            session.page = page
            session.current_page_id = target_page_id
            session.last_open_page_id = target_page_id
            current_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if current_url:
                session.current_url = current_url
                self._remember_current_url(conversation_id, current_url)
            session.touch()
        self._attach_page_console_listeners(conversation_id, target_page_id, page)
        return session, page, target_page_id

    def _page_is_open(self, page: Any) -> bool:
        with suppress(Exception):
            is_closed = getattr(page, "is_closed", None)
            if callable(is_closed):
                return not bool(is_closed())
        return True

    def _attach_page_console_listeners(self, conversation_id: str, page_id: str, page: Any) -> None:
        on_event = getattr(page, "on", None)
        if not callable(on_event):
            return
        key = (conversation_id, page_id, id(page))
        if key in self._console_listener_keys:
            return
        self._console_listener_keys.add(key)

        def handle_console(message: Any) -> None:
            level = self._console_message_attr(message, "type") or "log"
            text = self._console_message_attr(message, "text") or str(message)
            location = self._console_message_attr(message, "location")
            url = ""
            if isinstance(location, Mapping):
                url = str(location.get("url") or "")
            self._record_console_entry(
                conversation_id,
                page_id,
                level=str(level),
                text=str(text),
                source="console",
                url=url,
            )

        def handle_page_error(error: Any) -> None:
            self._record_console_entry(
                conversation_id,
                page_id,
                level="error",
                text=str(error),
                source="pageerror",
                url=_clean_browser_url(str(getattr(page, "url", "") or "")),
            )

        with suppress(Exception):
            on_event("console", handle_console)
        with suppress(Exception):
            on_event("pageerror", handle_page_error)

    def _console_message_attr(self, message: Any, name: str) -> Any:
        value = getattr(message, name, None)
        if callable(value):
            with suppress(Exception):
                return value()
        return value

    def _record_console_entry(
        self,
        conversation_id: str,
        page_id: str,
        *,
        level: str,
        text: str,
        source: str,
        url: str = "",
    ) -> None:
        self._console_sequence += 1
        page_cache = self._console_cache.setdefault(conversation_id, {}).setdefault(page_id, [])
        page_cache.append(
            BrowserConsoleEntry(
                entry_id=self._console_sequence,
                page_id=page_id,
                level=(level or "log").lower(),
                text=str(text or "")[:8_000],
                source=source,
                url=url,
            )
        )
        del page_cache[:-_MAX_CONSOLE_ENTRIES_PER_PAGE]

    async def _page_runtime(self, page: Any) -> str:
        return "lightpanda" if await self._is_lightpanda_page(page) else "chrome_cdp"

    async def _is_lightpanda_page(self, page: Any) -> bool:
        user_agent = await self._safe_user_agent(page)
        return user_agent.lower().startswith("lightpanda/")

    def _bounded_script_result(self, value: Any) -> tuple[str, Any | None, bool]:
        try:
            result_text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            result_text = str(value)
        truncated = len(result_text) > _MAX_BROWSER_SCRIPT_RESULT_CHARS
        if truncated:
            result_text = result_text[:_MAX_BROWSER_SCRIPT_RESULT_CHARS].rstrip()
        result: Any | None
        if truncated:
            result = None
        else:
            try:
                result = json.loads(result_text)
            except Exception:
                result = result_text
        return result_text, result, truncated

    async def _cdp_command_for_page(
        self,
        page: Any,
        *,
        url: str,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        context = getattr(page, "context", None)
        if callable(context):
            with suppress(Exception):
                context = context()
        new_cdp_session = getattr(context, "new_cdp_session", None)
        if callable(new_cdp_session):
            cdp_session = await new_cdp_session(page)
            try:
                return await cdp_session.send(method, params or {})
            finally:
                detach = getattr(cdp_session, "detach", None)
                if callable(detach):
                    with suppress(Exception):
                        result = detach()
                        if inspect.isawaitable(result):
                            await result
        return await self._lightpanda_raw_cdp_command(
            url=url or "about:blank",
            method=method,
            params=params or {},
        )

    def _first_open_context_page(self, context: Any) -> Any | None:
        raw_pages = getattr(context, "pages", None)
        if not raw_pages:
            return None
        for page in list(raw_pages):
            with suppress(Exception):
                if not page.is_closed():
                    return page
        return None

    async def _connect_browser(self) -> Any:
        if not self.enabled:
            raise BrowserUnavailableError("LightPanda browser tools are disabled.")
        last_error: Exception | None = None
        for attempt in range(3):
            endpoint = await self._resolve_endpoint()
            try:
                if self._connector is not None:
                    return await self._connector(endpoint)
                return await self._connect_with_playwright(endpoint)
            except Exception as exc:
                last_error = exc
                if attempt == 2:
                    break
                await asyncio.sleep(0.25 * (attempt + 1))
        if await self._try_start_lightpanda_container():
            for attempt in range(4):
                endpoint = await self._resolve_endpoint()
                try:
                    if self._connector is not None:
                        return await self._connector(endpoint)
                    return await self._connect_with_playwright(endpoint)
                except Exception as exc:
                    last_error = exc
                    if attempt == 3:
                        break
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise BrowserUnavailableError(
            "Browser CDP endpoint is unavailable. Start LightPanda with "
            "`docker compose up -d lightpanda` or start Chrome/Chromium with "
            "`--remote-debugging-port=9222`, then verify /json/version."
        ) from last_error

    async def _try_start_lightpanda_container(self) -> bool:
        if (
            not self.auto_start_lightpanda
            or self._connector is not None
            or not _is_local_lightpanda_endpoint(self.cdp_url)
        ):
            return False
        async with self._container_start_lock:
            if self._container_start_attempted:
                return False
            self._container_start_attempted = True
            repo_root = Path(__file__).resolve().parents[5]
            compose_file = repo_root / "docker-compose.yml"
            if not compose_file.exists():
                return False
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "compose",
                    "up",
                    "-d",
                    "lightpanda",
                    cwd=repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=60)
            except (OSError, TimeoutError) as exc:
                logger.warning("lightpanda_container_autostart_failed", error=str(exc))
                return False
            output = (
                stdout_data.decode("utf-8", errors="replace")
                + stderr_data.decode("utf-8", errors="replace")
            ).strip()
            if proc.returncode != 0:
                logger.warning(
                    "lightpanda_container_autostart_failed",
                    returncode=proc.returncode,
                    output=output,
                )
                return False
            logger.info("lightpanda_container_autostarted", output=output)
            return True

    async def _connect_with_playwright(self, endpoint: str) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `playwright` is required for LightPanda browser tools."
            ) from exc

        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            playwright = self._playwright
        return await playwright.chromium.connect_over_cdp(
            endpoint,
            timeout=self.timeout_ms,
        )

    async def _new_session_page(self, session: _BrowserSession) -> Any | None:
        if not session.new_pages_supported:
            return None
        async with session.new_page_lock:
            if not session.new_pages_supported:
                return None
            try:
                page = await session.context.new_page()
            except Exception as exc:
                if _is_target_already_loaded_error(exc):
                    session.new_pages_supported = False
                    if not session.new_page_unavailable_logged:
                        logger.debug("lightpanda_new_page_unavailable", error=str(exc))
                        session.new_page_unavailable_logged = True
                    return None
                raise
        with suppress(Exception):
            page.set_default_timeout(self.timeout_ms)
        return page

    async def _resolve_endpoint(self) -> str:
        version_payload = None
        if self.cdp_url.strip().startswith(("http://", "https://")):
            with suppress(Exception):
                async with httpx.AsyncClient(timeout=self.timeout_ms / 1000) as client:
                    response = await client.get(f"{self.cdp_url.rstrip('/')}/json/version")
                    response.raise_for_status()
                    version_payload = response.json()
        return normalize_lightpanda_cdp_endpoint(self.cdp_url, version_payload)

    async def _goto(
        self,
        conversation_id: str,
        session: _BrowserSession,
        url: str,
        *,
        allow_partial: bool = False,
    ) -> None:
        try:
            await self._goto_page(session.page, url, allow_partial=allow_partial)
        except Exception:
            await self._close_session(conversation_id, session)
            raise

    async def _goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
    ) -> None:
        clean_url = _clean_browser_url(url)
        try:
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(250)
            await self._install_console_capture(page)
        except Exception as exc:
            page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
            if allow_partial and page_url.startswith(("http://", "https://")):
                logger.warning(
                    "lightpanda_navigation_partial",
                    url=clean_url,
                    page_url=page_url,
                    error=str(exc),
                )
                with suppress(Exception):
                    await self._install_console_capture(page)
                return
            if "RobotsBlocked" in str(exc):
                raise BrowserBlockedError(
                    "LightPanda blocked navigation because `--obey-robots` is enabled.",
                    provider=urlparse(clean_url).hostname or "",
                    reason="robots_txt",
                    url=clean_url,
                ) from exc
            raise BrowserUnavailableError(
                f"LightPanda navigation failed for {clean_url}: {exc}"
            ) from exc

    async def _evaluate_page(
        self,
        page: Any,
        script: str,
        arg: Any | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if arg is None:
                    return await page.evaluate(script)
                return await page.evaluate(script, arg)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if "Execution context was destroyed" not in message:
                    raise
                if attempt == 2:
                    break
                with suppress(Exception):
                    await page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=min(self.timeout_ms, 5_000),
                    )
                with suppress(Exception):
                    await page.wait_for_timeout(250)
        if last_error is not None:
            raise last_error
        return None

    async def _install_console_capture(self, page: Any) -> None:
        with suppress(Exception):
            await self._evaluate_page(page, _CONSOLE_CAPTURE_SCRIPT)

    async def _drain_page_console_entries(
        self,
        page: Any,
        conversation_id: str,
        page_id: str,
    ) -> None:
        await self._install_console_capture(page)
        entries = await self._evaluate_page(page, _CONSOLE_DRAIN_SCRIPT)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            self._record_console_entry(
                conversation_id,
                page_id,
                level=str(entry.get("level") or "log"),
                text=str(entry.get("text") or ""),
                source=str(entry.get("source") or "console"),
                url=str(entry.get("url") or ""),
            )

    async def _content_page_for_target(
        self,
        *,
        conversation_id: str,
        session: _BrowserSession | None,
        target_url: str,
        target_page_id: str | None,
        allow_navigation: bool,
    ) -> Any | None:
        if session is None:
            return None
        clean_target_url = _clean_browser_url(target_url)
        if target_page_id:
            page = session.pages.get(target_page_id)
            if page is not None and self._is_live_page_for_url(page, clean_target_url):
                return page
            return None

        preferred_page = self._preferred_session_page(session)
        if self._is_live_page_for_url(preferred_page, clean_target_url):
            return preferred_page
        if not allow_navigation or not clean_target_url.startswith(("http://", "https://")):
            return None

        page = await self._new_session_page(session)
        if page is None:
            page = preferred_page
        await self._goto_page(page, clean_target_url, allow_partial=True)
        session.page = page
        session.current_url = _clean_browser_url(
            str(getattr(page, "url", clean_target_url) or clean_target_url)
        )
        self._remember_current_url(conversation_id, session.current_url)
        session.touch()
        return page

    def _is_live_page_for_url(self, page: Any, target_url: str) -> bool:
        with suppress(Exception):
            if page.is_closed():
                return False
        page_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        return bool(page_url and _urls_equivalent(page_url, target_url))

    async def _prepare_page_for_extraction(self, page: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "prepared_page": True,
            "popup_dismissed_count": 0,
            "popup_dismissed_labels": [],
            "scroll_steps": 0,
        }
        await self._wait_for_page_settle(page)
        with suppress(Exception):
            await page.wait_for_timeout(350)

        first_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, first_dismiss)
        if first_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(350)

        scroll = await self._scroll_page_incrementally(page)
        metadata.update(scroll)

        second_dismiss = await self._dismiss_page_popups(page)
        self._merge_popup_dismissal(metadata, second_dismiss)
        if second_dismiss.get("clicked_count"):
            with suppress(Exception):
                await page.wait_for_timeout(250)
        return metadata

    async def _wait_for_page_settle(self, page: Any) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 8_000))
        with suppress(Exception):
            await wait_for_load_state("load", timeout=min(self.timeout_ms, 2_000))

    async def _dismiss_page_popups(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._evaluate_page(page, _POPUP_DISMISS_SCRIPT),
                timeout=min(self.timeout_ms / 1000, 3),
            )
        except Exception as exc:
            logger.debug("browser_popup_dismiss_failed", error=str(exc))
            return {"clicked_count": 0, "clicked_labels": [], "error": str(exc)}
        if isinstance(value, dict):
            labels = value.get("clicked_labels")
            return {
                "clicked_count": int(value.get("clicked_count") or 0),
                "clicked_labels": labels if isinstance(labels, list) else [],
            }
        return {"clicked_count": 0, "clicked_labels": []}

    def _merge_popup_dismissal(
        self,
        metadata: dict[str, Any],
        dismissed: dict[str, Any],
    ) -> None:
        clicked_count = int(dismissed.get("clicked_count") or 0)
        metadata["popup_dismissed_count"] = (
            int(metadata.get("popup_dismissed_count") or 0) + clicked_count
        )
        labels = metadata.setdefault("popup_dismissed_labels", [])
        if isinstance(labels, list):
            labels.extend(str(label) for label in dismissed.get("clicked_labels") or [])
            del labels[8:]

    async def _scroll_page_incrementally(self, page: Any) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                self._evaluate_page(
                    page,
                    _INCREMENTAL_SCROLL_SCRIPT,
                    {
                        "maxSteps": 36,
                        "delayMs": 180,
                        "stepRatio": 0.82,
                    },
                ),
                timeout=min(max(self.timeout_ms / 1000, 1.0), 8.0),
            )
        except Exception as exc:
            logger.debug("browser_incremental_scroll_failed", error=str(exc))
            return {"scroll_error": str(exc)}
        if not isinstance(value, dict):
            return {}
        return {
            "scroll_steps": int(value.get("steps") or 0),
            "scroll_y": int(value.get("scroll_y") or 0),
            "scroll_height": int(value.get("scroll_height") or 0),
            "viewport_height": int(value.get("viewport_height") or 0),
            "scroll_at_bottom": bool(value.get("at_bottom")),
        }

    async def _markdown_or_text_page(
        self,
        page: Any,
        *,
        fallback_url: str,
    ) -> tuple[str, str, dict[str, Any]]:
        try:
            preparation = await asyncio.wait_for(
                self._prepare_page_for_extraction(page),
                timeout=min(max(self.timeout_ms / 1000, 1.0), 22.0),
            )
        except Exception as exc:
            fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
                fallback_url
            )
            return (
                fallback_content,
                fallback_method,
                {
                    **fallback_stats,
                    "prepared_page": False,
                    "prepare_error": str(exc),
                    "fallback": fallback_method,
                },
            )
        value: Any = None
        with suppress(Exception):
            value = await self._evaluate_page(page, _READABLE_DOM_SCRIPT)
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, str):
                cleaned, stats = _clean_extracted_content(content)
                if cleaned:
                    return (
                        cleaned,
                        "prepared_readable_dom_text",
                        {
                            **stats,
                            **preparation,
                            "selected_tag": value.get("selected_tag"),
                            "readable_score": value.get("score"),
                        },
                    )
        elif isinstance(value, str):
            cleaned, stats = _clean_extracted_content(value)
            if cleaned:
                return cleaned, "prepared_dom_text", {**stats, **preparation}

        text = ""
        with suppress(Exception):
            value = await self._evaluate_page(
                page,
                "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                "|| document.documentElement.textContent || '')",
            )
            if isinstance(value, str):
                text = value
        cleaned_text, text_stats = _clean_extracted_content(text)
        if cleaned_text:
            return cleaned_text, "prepared_dom_text", {**text_stats, **preparation}

        fallback_content, fallback_method, fallback_stats = await self._markdown_or_text_url(
            fallback_url
        )
        return (
            fallback_content,
            fallback_method,
            {
                **fallback_stats,
                **preparation,
                "fallback": fallback_method,
            },
        )

    async def _markdown_or_text(self, session: _BrowserSession) -> tuple[str, str, dict[str, Any]]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._markdown_or_text_url(url)

    async def _markdown_or_text_url(self, url: str) -> tuple[str, str, dict[str, Any]]:
        markdown = await self._lightpanda_markdown_url(url)
        if markdown:
            cleaned_markdown, stats = _clean_extracted_content(markdown)
            if _should_prefer_readable_dom(cleaned_markdown, stats):
                readable = await self._readable_dom_content_url(url)
                if readable:
                    return (
                        readable,
                        "readable_dom_text",
                        {
                            **stats,
                            "fallback": "readable_dom_text",
                        },
                    )
            if cleaned_markdown:
                method = (
                    "lightpanda_markdown_cleaned"
                    if stats.get("removed_link_noise_blocks")
                    else "lightpanda_markdown"
                )
                return cleaned_markdown, method, stats
        readable = await self._readable_dom_content_url(url)
        if readable:
            return readable, "readable_dom_text", {}
        text = await self._raw_runtime_evaluate_value(
            url,
            "(document.body && (document.body.innerText || document.body.textContent)) "
            "|| document.documentElement.textContent || ''",
            label="dom_text",
            timeout=min(self.timeout_ms / 1000, 5),
        )
        if not isinstance(text, str):
            return "", "dom_text_failed", {}
        cleaned_text, stats = _clean_extracted_content(text)
        return cleaned_text, "dom_text", stats

    async def _readable_dom_content_url(self, url: str) -> str:
        value = await self._raw_runtime_evaluate_value(
            url,
            _READABLE_DOM_SCRIPT,
            label="readable_dom",
            timeout=min(self.timeout_ms / 1000, 8),
        )
        if not isinstance(value, dict):
            return ""
        content = value.get("content")
        if not isinstance(content, str):
            return ""
        cleaned, _stats = _clean_extracted_content(content)
        return cleaned

    async def _lightpanda_markdown(self, session: _BrowserSession) -> str:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._lightpanda_markdown_url(url)

    async def _lightpanda_markdown_url(self, url: str) -> str:
        url = _clean_browser_url(url)
        if not url or url == "about:blank":
            return ""
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="LP.getMarkdown",
                ),
                timeout=min(self.timeout_ms / 1000, 15),
            )
            markdown = self._extract_markdown_payload(payload)
            if markdown:
                return markdown
        except TimeoutError as exc:
            logger.warning("lightpanda_markdown_raw_timeout", error=str(exc), url=url)
            return ""
        except Exception as exc:
            logger.warning("lightpanda_markdown_failed", error=str(exc))
            return ""
        return ""

    def _extract_markdown_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("markdown", "content", "text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(payload, str):
            return payload
        return ""

    async def _raw_runtime_evaluate_value(
        self,
        url: str,
        expression: str,
        *,
        label: str,
        timeout: float,
    ) -> Any:
        if not url or url == "about:blank":
            return None
        try:
            payload = await asyncio.wait_for(
                self._lightpanda_raw_cdp_command(
                    url=url,
                    method="Runtime.evaluate",
                    params={
                        "expression": expression,
                        "returnByValue": True,
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_timeout", label=label, error=str(exc))
            return None
        except Exception as exc:
            logger.warning("lightpanda_raw_runtime_evaluate_failed", label=label, error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return result.get("value")

    async def _html_or_empty(self, session: _BrowserSession) -> tuple[str, str]:
        url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return await self._html_or_empty_url(url)

    async def _html_or_empty_page(self, page: Any, *, fallback_url: str) -> tuple[str, str]:
        try:
            await asyncio.wait_for(
                self._prepare_page_for_extraction(page),
                timeout=min(max(self.timeout_ms / 1000, 1.0), 22.0),
            )
        except Exception as exc:
            logger.debug("browser_page_html_prepare_failed", error=str(exc))
            return await self._html_or_empty_url(fallback_url)
        try:
            content = getattr(page, "content", None)
            if callable(content):
                html = await asyncio.wait_for(
                    content(),
                    timeout=min(self.timeout_ms / 1000, 10),
                )
                if isinstance(html, str):
                    return html, "prepared_playwright_page_content"
        except Exception as exc:
            logger.debug("browser_page_html_failed", error=str(exc))
        return await self._html_or_empty_url(fallback_url)

    async def _html_or_empty_url(self, url: str) -> tuple[str, str]:
        url = _clean_browser_url(url)
        value = await self._raw_runtime_evaluate_value(
            url,
            "document.documentElement ? document.documentElement.outerHTML : ''",
            label="html",
            timeout=min(self.timeout_ms / 1000, 10),
        )
        if isinstance(value, str):
            return value, "raw_cdp_runtime_evaluate"
        return "", "raw_cdp_runtime_unavailable"

    async def _lightpanda_raw_cdp_command(
        self,
        *,
        url: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            import websockets
        except ImportError as exc:
            raise BrowserUnavailableError(
                "Python package `websockets` is required for LightPanda native CDP commands."
            ) from exc

        timeout_seconds = self.timeout_ms / 1000
        last_error: Exception | None = None
        for attempt, delay in enumerate(_RAW_CDP_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                endpoint = await self._resolve_endpoint()
                async with websockets.connect(
                    endpoint,
                    open_timeout=timeout_seconds,
                    close_timeout=min(timeout_seconds, 5),
                    max_size=8 * 1024 * 1024,
                ) as websocket:
                    client = _RawCdpClient(websocket)
                    created = await client.send("Target.createTarget", {"url": "about:blank"})
                    target_id = str(created.get("targetId") or "")
                    attached = await client.send(
                        "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True},
                    )
                    session_id = str(attached.get("sessionId") or "")
                    try:
                        with suppress(Exception):
                            await client.send("Page.enable", session_id=session_id)
                        await client.send("Page.navigate", {"url": url}, session_id=session_id)
                        with suppress(TimeoutError, asyncio.TimeoutError):
                            await client.wait_for_event(
                                "Page.domContentEventFired",
                                session_id=session_id,
                                timeout=timeout_seconds,
                            )
                        await asyncio.sleep(0.25)
                        return await client.send(method, params or {}, session_id=session_id)
                    finally:
                        if target_id:
                            with suppress(Exception):
                                await client.send("Target.closeTarget", {"targetId": target_id})
            except Exception as exc:
                last_error = exc
                if attempt == len(_RAW_CDP_RETRY_DELAYS) - 1 or not _is_retryable_raw_cdp_error(
                    exc
                ):
                    raise
                logger.debug(
                    "lightpanda_raw_cdp_retry",
                    attempt=attempt + 1,
                    method=method,
                    url=url,
                    error=str(exc),
                )
        if last_error is not None:
            raise last_error
        raise BrowserUnavailableError("LightPanda raw CDP command failed.")

    def _extract_links_from_content(self, content: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in _MARKDOWN_LINK_PATTERN.finditer(content):
            text = " ".join(match.group(1).split())
            url = match.group(2).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            links.append({"url": url, "text": text})
            if len(links) >= 50:
                break
        return links

    async def _safe_title(self, page: Any) -> str:
        try:
            title = await asyncio.wait_for(
                page.title(),
                timeout=min(self.timeout_ms / 1000, 3),
            )
            return str(title or "").strip()
        except TimeoutError as exc:
            logger.debug("lightpanda_title_timeout", error=str(exc))
            return ""
        except Exception:
            return ""

    async def _safe_title_for_url(self, url: str) -> str:
        value = await self._raw_runtime_evaluate_value(
            url,
            "document.title || ''",
            label="title",
            timeout=min(self.timeout_ms / 1000, 5),
        )
        return str(value or "").strip() if isinstance(value, str) else ""

    async def _raise_if_google_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "sorry/index" not in page_url and "google." not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_google_surface = "google." in page_url or "google" in title
        if "sorry/index" not in page_url and not is_google_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "our systems have detected",
            "before you continue",
            "consent.google",
            "enable javascript on your web browser",
        )
        if "sorry/index" in page_url or (
            is_google_surface and any(marker in sample or marker in title for marker in markers)
        ):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Google blocked this browser session with consent, CAPTCHA, or unusual-traffic checks. "
                "This is a Google/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="google",
                reason="captcha_or_unusual_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_bing_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "bing.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_bing_surface = "bing.com" in page_url or "bing" in title
        if not is_bing_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
            "solve this puzzle",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Bing blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="bing",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_yahoo_blocked(self, page: Any) -> None:
        page_url = str(getattr(page, "url", "") or "").lower()
        if "search.yahoo.com" not in page_url:
            return
        raw_title = await self._safe_title(page)
        title = raw_title.lower()
        is_yahoo_surface = "search.yahoo.com" in page_url or "yahoo search" in title
        if not is_yahoo_surface:
            return
        raw_sample = ""
        with suppress(Exception):
            raw_sample = str(
                await self._evaluate_page(
                    page,
                    "() => ((document.body && (document.body.innerText || document.body.textContent)) "
                    "|| '').slice(0, 3000)",
                )
                or ""
            )
        sample = raw_sample.lower()
        markers = (
            "unusual traffic",
            "automated requests",
            "verify you are human",
            "are you a robot",
            "please solve the challenge",
            "enter the characters you see",
        )
        if any(marker in sample or marker in title for marker in markers):
            compact_sample = " ".join(raw_sample.split())[:700]
            raise BrowserBlockedError(
                "Yahoo blocked this browser session with CAPTCHA or automated-traffic checks. "
                "This is a search-provider/browser-fingerprint block, not a Playwright CDP connection error.",
                provider="yahoo",
                reason="captcha_or_automated_traffic",
                url=str(getattr(page, "url", "") or ""),
                title=raw_title,
                sample=compact_sample,
            )

    async def _raise_if_search_blocked(self, page: Any) -> None:
        await self._raise_if_google_blocked(page)
        await self._raise_if_bing_blocked(page)
        await self._raise_if_yahoo_blocked(page)

    def _cache_search_results(
        self,
        *,
        conversation_id: str,
        query: str,
        search_url: str,
        results: list[BrowserSearchResult],
    ) -> BrowserSearchSnapshot:
        raw_id = f"{conversation_id}\n{query}\n{search_url}\n{time.monotonic_ns()}"
        search_id = f"search_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        snapshot = BrowserSearchSnapshot(
            search_id=search_id,
            query=query,
            search_url=search_url,
            provider=self.search_provider,
            results=self._copy_search_results(results),
        )
        snapshots = self._search_cache.setdefault(conversation_id, [])
        snapshots.insert(0, snapshot)
        del snapshots[_MAX_CACHED_SEARCHES_PER_CONVERSATION:]
        return snapshot

    def _latest_cached_search_results(self, conversation_id: str) -> list[BrowserSearchResult]:
        snapshots = self._search_cache.get(conversation_id) or []
        if not snapshots:
            return []
        return self._copy_search_results(snapshots[0].results)

    def _copy_search_results(
        self,
        results: list[BrowserSearchResult],
    ) -> list[BrowserSearchResult]:
        return [
            BrowserSearchResult(
                index=result.index,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
            )
            for result in results
        ]

    def _remember_current_url(self, conversation_id: str, url: str | None) -> None:
        url = _clean_browser_url(str(url or ""))
        if not url or url == "about:blank":
            return
        self._current_url_cache[conversation_id] = url

    def _cache_opened_page(
        self,
        *,
        conversation_id: str,
        url: str,
        final_url: str,
        title: str,
        source_search_id: str | None,
        opener_tool_call_id: str | None,
    ) -> BrowserOpenedPage:
        url = _clean_browser_url(url)
        final_url = _clean_browser_url(final_url)
        raw_id = f"{conversation_id}\n{final_url}\n{time.monotonic_ns()}"
        page_id = f"page_{hashlib.sha256(raw_id.encode()).hexdigest()[:12]}"
        opened_page = BrowserOpenedPage(
            page_id=page_id,
            url=url,
            final_url=final_url,
            title=title,
            source_search_id=source_search_id,
            opener_tool_call_id=opener_tool_call_id,
        )
        pages = self._opened_pages_cache.setdefault(conversation_id, [])
        pages.insert(0, opened_page)
        del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
        self._last_open_cache[conversation_id] = opened_page
        return opened_page

    def _mark_opened_page_extracted(self, opened_page: BrowserOpenedPage) -> None:
        opened_page.extraction_count += 1
        opened_page.last_extracted_at = time.monotonic()

    def _opened_page_tab(
        self,
        page: BrowserOpenedPage,
        *,
        index: int,
        current_url: str | None,
        last_open_page_id: str | None,
    ) -> dict[str, Any]:
        parsed = urlparse(page.final_url or page.url)
        domain = parsed.netloc
        title = page.title.strip() if page.title else ""
        summary = title or domain or page.final_url
        return {
            "index": index,
            "page_id": page.page_id,
            "window_id": page.window_id,
            "url": page.url,
            "final_url": page.final_url,
            "domain": domain,
            "title": title,
            "summary": summary,
            "source_search_id": page.source_search_id,
            "opener_tool_call_id": page.opener_tool_call_id,
            "extraction_count": page.extraction_count,
            "is_last_open": page.page_id == last_open_page_id,
            "is_current_page": bool(current_url and current_url == page.final_url),
        }

    def _opened_page(
        self,
        conversation_id: str,
        page_id: str,
    ) -> BrowserOpenedPage | None:
        for opened_page in self._opened_pages_cache.get(conversation_id, []):
            if opened_page.page_id == page_id:
                return opened_page
        return None

    def _target_title(self, conversation_id: str, page_id: str | None) -> str:
        if not page_id:
            return ""
        opened_page = self._opened_page(conversation_id, page_id)
        return opened_page.title if opened_page is not None else ""

    def _resolve_content_target(
        self,
        conversation_id: str,
        session: _BrowserSession | None,
        *,
        url: str | None = None,
        page_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        if url and page_id:
            raise BrowserError("Use either url or page_id, not both.")
        if page_id:
            opened_page = self._opened_page(conversation_id, page_id)
            if opened_page is None:
                raise BrowserError(
                    f"No opened browser page with page_id {page_id}. Run BrowserOpen first."
                )
            return opened_page.final_url, opened_page.page_id
        if url:
            return _clean_browser_url(url), None
        next_unextracted = self._next_unextracted_opened_page(conversation_id)
        if next_unextracted is not None:
            return next_unextracted.final_url, next_unextracted.page_id
        last_open = self._last_open_cache.get(conversation_id)
        if last_open is not None:
            return last_open.final_url, last_open.page_id
        if session is not None and session.last_open_url:
            return session.last_open_url, session.last_open_page_id
        current_url = _clean_browser_url(
            str(
                (session.current_url if session is not None else None)
                or self._current_url_cache.get(conversation_id)
                or ""
            )
        )
        if current_url.startswith(("http://", "https://")):
            return current_url, None
        if session is not None:
            page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
            if page_url.startswith(("http://", "https://")):
                return page_url, None
        return None, None

    def _next_unextracted_opened_page(self, conversation_id: str) -> BrowserOpenedPage | None:
        pages = [
            page
            for page in self._opened_pages_cache.get(conversation_id, [])
            if page.extraction_count == 0
        ]
        if len(pages) <= 1:
            return None
        return min(pages, key=lambda page: page.opened_at)

    def _should_navigate_for_content(self, session: _BrowserSession, target_url: str) -> bool:
        target_url = _clean_browser_url(target_url)
        if not target_url.startswith(("http://", "https://")):
            return False
        page_url = _clean_browser_url(str(getattr(session.page, "url", "") or ""))
        return page_url != target_url

    def _result_url(
        self,
        conversation_id: str,
        session: _BrowserSession,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> tuple[str, str | None]:
        if search_id:
            for snapshot in self._search_cache.get(conversation_id, []):
                if snapshot.search_id != search_id:
                    continue
                for result in snapshot.results:
                    if result.index == result_index:
                        return _clean_browser_url(result.url), snapshot.search_id
                raise BrowserError(
                    f"No browser search result with index {result_index} in search_id {search_id}."
                )
            raise BrowserError(
                f"No cached browser search with search_id {search_id}. Run BrowserSearch first."
            )

        for snapshot in self._search_cache.get(conversation_id, []):
            for result in snapshot.results:
                if result.index == result_index:
                    return _clean_browser_url(result.url), snapshot.search_id

        for result in session.search_results:
            if result.index == result_index:
                return _clean_browser_url(result.url), None
        raise BrowserError(
            f"No browser search result with index {result_index}. Run BrowserSearch first."
        )

    def _result_title(
        self,
        conversation_id: str,
        result_index: int,
        *,
        search_id: str | None = None,
    ) -> str:
        snapshots = self._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if result.index == result_index:
                    return result.title
        return ""

    def _match_search_result_url(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str | None:
        snapshots = self._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if _urls_equivalent(url, result.url):
                    return snapshot.search_id
        return None

    def _match_search_result_title(
        self,
        conversation_id: str,
        url: str,
        *,
        search_id: str | None = None,
    ) -> str:
        snapshots = self._search_cache.get(conversation_id, [])
        for snapshot in snapshots:
            if search_id and snapshot.search_id != search_id:
                continue
            for result in snapshot.results:
                if _urls_equivalent(url, result.url):
                    return result.title
        return ""

    async def _cleanup_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            conversation_id
            for conversation_id, session in self._sessions.items()
            if now - session.updated_at > self.session_ttl_seconds
        ]
        for conversation_id in expired:
            await self._close_session(conversation_id, self._sessions[conversation_id])
        self._cleanup_search_cache(now)

    def _cleanup_search_cache(self, now: float) -> None:
        for conversation_id, snapshots in list(self._search_cache.items()):
            fresh = [
                snapshot
                for snapshot in snapshots
                if now - snapshot.created_at <= self.session_ttl_seconds
            ][:_MAX_CACHED_SEARCHES_PER_CONVERSATION]
            if fresh:
                self._search_cache[conversation_id] = fresh
            else:
                self._search_cache.pop(conversation_id, None)
                if conversation_id not in self._sessions:
                    self._current_url_cache.pop(conversation_id, None)
                    self._last_open_cache.pop(conversation_id, None)
                    self._opened_pages_cache.pop(conversation_id, None)
                    self._element_map_cache.pop(conversation_id, None)
                    self._console_cache.pop(conversation_id, None)

    async def _enforce_session_limit(self) -> None:
        while len(self._sessions) > self.max_sessions:
            conversation_id, session = min(
                self._sessions.items(),
                key=lambda item: item[1].updated_at,
            )
            await self._close_session(conversation_id, session)

    async def _reset_browser(self) -> None:
        async with self._lock:
            await self._close_sessions()

    async def _close_sessions(self) -> None:
        for conversation_id, session in list(self._sessions.items()):
            await self._close_session(conversation_id, session)

    async def _close_session(self, conversation_id: str, session: _BrowserSession) -> None:
        self._sessions.pop(conversation_id, None)
        self._element_map_cache.pop(conversation_id, None)
        self._console_cache.pop(conversation_id, None)
        for page in self._session_pages(session):
            await self._best_effort_resource_call("browser_page_close", page.close)
        await self._best_effort_resource_call("browser_context_close", session.context.close)
        await self._release_browser(session.browser)

    async def _release_browser(self, browser: Any) -> None:
        await self._best_effort_resource_call("browser_close", browser.close)

    async def _best_effort_resource_call(
        self,
        label: str,
        operation: Callable[[], Any],
    ) -> None:
        try:
            result = operation()
            if inspect.isawaitable(result):
                await asyncio.wait_for(
                    result,
                    timeout=min(max(self.timeout_ms / 1000, 0.5), 2),
                )
        except Exception as exc:
            logger.debug("lightpanda_resource_close_failed", label=label, error=str(exc))


class _RawCdpClient:
    """Tiny sequential CDP client for LightPanda-native domain calls."""

    def __init__(self, websocket: Any) -> None:
        self._websocket = websocket
        self._next_id = 0
        self._events: list[dict[str, Any]] = []

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        await self._websocket.send(json.dumps(message))
        while True:
            payload = json.loads(await self._websocket.recv())
            if payload.get("id") == message_id:
                if "error" in payload:
                    error = payload["error"]
                    raise BrowserUnavailableError(f"LightPanda CDP {method} failed: {error}")
                result = payload.get("result")
                return result if isinstance(result, dict) else {}
            self._events.append(payload)

    async def wait_for_event(
        self,
        method: str,
        *,
        session_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for index, event in enumerate(self._events):
                if self._is_matching_event(event, method, session_id):
                    return self._events.pop(index)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for CDP event {method}.")
            payload = json.loads(await asyncio.wait_for(self._websocket.recv(), timeout=remaining))
            if self._is_matching_event(payload, method, session_id):
                return payload
            self._events.append(payload)

    @staticmethod
    def _is_matching_event(payload: dict[str, Any], method: str, session_id: str) -> bool:
        return payload.get("method") == method and payload.get("sessionId") == session_id


_GOOGLE_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      if (parsed.pathname === '/url' && parsed.searchParams.get('q')) {
        return parsed.searchParams.get('q');
      }
      if (parsed.searchParams.get('url')) {
        return parsed.searchParams.get('url');
      }
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  for (const anchor of Array.from(document.querySelectorAll('a'))) {
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host.includes('google.')) continue;
    const heading = anchor.querySelector('h3');
    const title = clean(heading ? heading.textContent : anchor.textContent);
    if (!title || title.length < 3) continue;
    let container = anchor;
    for (let i = 0; i < 4 && container.parentElement; i += 1) {
      container = container.parentElement;
    }
    let snippet = clean(container.textContent).replace(title, '').replace(href, '').trim();
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_YAHOO_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      const ru = parsed.searchParams.get('RU') || parsed.searchParams.get('url');
      if (ru && /^https?:\\/\\//i.test(ru)) return ru;
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  const containers = Array.from(
    document.querySelectorAll('ol.searchCenterMiddle > li, div.dd.algo, div.algo')
  );
  for (const container of containers) {
    const anchor = container.querySelector(
      '.compTitle a[href], h3 a[href], a[href][target="_blank"]'
    );
    if (!anchor) continue;
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host === 'search.yahoo.com' || host.endsWith('.search.yahoo.com')) continue;
    const titleNode = anchor.querySelector('h3, .title') || container.querySelector('h3');
    const title = clean(titleNode ? titleNode.textContent : anchor.textContent);
    if (!title || title.length < 3) continue;
    const snippetNode = container.querySelector('.compText, .compText p, p');
    let snippet = clean(snippetNode ? snippetNode.textContent : '');
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_BING_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const decodeBingRedirect = (parsed) => {
    const encoded = parsed.searchParams.get('u');
    if (!encoded) return '';
    try {
      let value = encoded.startsWith('a1') ? encoded.slice(2) : encoded;
      value = value.replace(/-/g, '+').replace(/_/g, '/');
      while (value.length % 4) value += '=';
      return atob(value);
    } catch (_) {
      return '';
    }
  };
  const normalizeHref = (href) => {
    try {
      const parsed = new URL(href, location.href);
      const host = parsed.hostname.toLowerCase();
      if (host.endsWith('bing.com') && parsed.pathname.startsWith('/ck/')) {
        const decoded = decodeBingRedirect(parsed);
        if (/^https?:\\/\\//i.test(decoded)) return decoded;
      }
      if (parsed.searchParams.get('url')) {
        return parsed.searchParams.get('url');
      }
      return parsed.href;
    } catch (_) {
      return href || '';
    }
  };
  const results = [];
  const containers = Array.from(document.querySelectorAll('li.b_algo, #b_results > li'));
  for (const container of containers) {
    const anchor = container.querySelector('h2 a[href], a[href]');
    if (!anchor) continue;
    const href = normalizeHref(anchor.getAttribute('href') || anchor.href || '');
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host.endsWith('bing.com')) continue;
    const title = clean(anchor.textContent);
    if (!title || title.length < 3) continue;
    let snippet = clean(
      (container.querySelector('.b_caption p, p') || {}).textContent || ''
    );
    if (!snippet) {
      snippet = clean(container.textContent).replace(title, '').replace(href, '').trim();
    }
    if (snippet.length > 280) snippet = snippet.slice(0, 280).trim();
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet });
    if (results.length >= maxResults) break;
  }
  return results;
}"""

_GENERIC_RESULTS_SCRIPT = """({ maxResults }) => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const results = [];
  const searchHost = location.hostname.toLowerCase();
  for (const anchor of Array.from(document.querySelectorAll('a[href]'))) {
    let href = '';
    try {
      href = new URL(anchor.getAttribute('href') || anchor.href || '', location.href).href;
    } catch (_) {
      continue;
    }
    if (!/^https?:\\/\\//i.test(href)) continue;
    let host = '';
    try {
      host = new URL(href).hostname.toLowerCase();
    } catch (_) {
      continue;
    }
    if (host === searchHost) continue;
    const title = clean(anchor.textContent);
    if (!title || title.length < 3) continue;
    if (results.some((item) => item.url === href)) continue;
    results.push({ title, url: href, snippet: '' });
    if (results.length >= maxResults) break;
  }
  return results;
}"""
