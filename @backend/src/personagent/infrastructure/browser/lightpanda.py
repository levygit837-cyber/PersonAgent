"""LightPanda CDP worker used by chat browser tools."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import structlog

from personagent.infrastructure.browser.actions import BrowserActions
from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache
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
from personagent.infrastructure.browser.page_cache import get_browser_page_cache
from personagent.infrastructure.browser.page_lifecycle import BrowserPageLifecycle
from personagent.infrastructure.browser.snapshot import BrowserSnapshot
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
_MAX_LIVE_PAGES_PER_SESSION = max(
    1,
    int(os.getenv("PERSONAGENT_BROWSER_MAX_LIVE_PAGES_PER_SESSION", "4")),
)
_STYLESHEET_LINK_PATTERN = re.compile(
    r"<link\b(?=[^>]*\brel\s*=\s*['\"][^'\"]*stylesheet[^'\"]*['\"])(?=[^>]*\bhref\s*=\s*['\"](?P<href>[^'\"]+)['\"])[^>]*>",
    re.IGNORECASE,
)
_LINK_TAG_PATTERN = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HTML_ATTR_PATTERN = re.compile(
    r"(?P<name>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'>`]+)"
)
_CSS_URL_PATTERN = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"\s][^)'\"]*)(?P=quote)\)")
_STYLESHEET_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_TTL_SECONDS", "900"))
_MAX_STYLESHEET_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_ENTRIES", "256"))
_MAX_STYLESHEET_HREFS_PER_PAGE = int(os.getenv("PERSONAGENT_BROWSER_CSS_MAX_HREFS", "32"))
_STYLESHEET_CACHE_DIR = Path(
    os.getenv("PERSONAGENT_BROWSER_CSS_CACHE_DIR", str(Path.home() / ".cache/personagent/browser-css"))
)
_RENDER_SNAPSHOT_CACHE_TTL_SECONDS = float(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_TTL_SECONDS", "180"))
_MAX_RENDER_SNAPSHOT_CACHE_ENTRIES = int(os.getenv("PERSONAGENT_BROWSER_RENDER_CACHE_ENTRIES", "16"))
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
        session_ttl_seconds: int = 600,
        max_sessions: int = 12,
        artifact_root: str | Path | None = None,
        render_cache_entries: int = _MAX_RENDER_SNAPSHOT_CACHE_ENTRIES,
        render_cache_ttl_seconds: float = _RENDER_SNAPSHOT_CACHE_TTL_SECONDS,
        css_cache_entries: int = _MAX_STYLESHEET_CACHE_ENTRIES,
        css_cache_ttl_seconds: float = _STYLESHEET_CACHE_TTL_SECONDS,
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
        self.artifact_root = Path(artifact_root).expanduser() if artifact_root else None
        self._snapshot_cache = SnapshotCache(
            max_entries=max(1, int(render_cache_entries)),
            ttl_seconds=max(1.0, float(render_cache_ttl_seconds)),
        )
        self._max_stylesheet_cache_entries = max(1, int(css_cache_entries))
        self._stylesheet_cache_ttl_seconds = max(1.0, float(css_cache_ttl_seconds))
        self._stylesheet_disk_cache = StylesheetDiskCache(
            cache_dir=_STYLESHEET_CACHE_DIR,
            max_entries=self._max_stylesheet_cache_entries,
        )
        self.auto_start_lightpanda = auto_start_lightpanda
        self._connector = connector
        self.actions = BrowserActions(self)
        self.lifecycle = BrowserPageLifecycle(self)
        self.snapshot = BrowserSnapshot(self)
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
        self._cooperation_event_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._cooperation_listener_keys: set[tuple[str, str, int]] = set()

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
            self._snapshot_cache.clear()
            self._console_cache.clear()
            self._console_listener_keys.clear()
            self._cooperation_event_cache.clear()
            self._cooperation_listener_keys.clear()

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
        already_read = opened_page.extraction_count > 0 if opened_page is not None else False
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
                await self._cleanup_live_pages(
                    conversation_id,
                    session,
                    keep_page_id=opened_page.page_id,
                    close_read_pages=True,
                )
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
            "already_read": already_read,
            "read_status": "already_read" if already_read else "read",
            "extraction_count": opened_page.extraction_count if opened_page is not None else 0,
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
        opened_page = None
        if session is not None and target_page_id:
            opened_page = self._opened_page(conversation_id, target_page_id)
            if opened_page is not None:
                already_read = opened_page.extraction_count > 0
                session.last_open_url = opened_page.final_url
                session.last_open_page_id = opened_page.page_id
                session.current_page_id = opened_page.page_id
                tab_page = session.pages.get(opened_page.page_id)
                if tab_page is not None:
                    session.page = tab_page
                self._mark_opened_page_extracted(opened_page)
                await self._cleanup_live_pages(
                    conversation_id,
                    session,
                    keep_page_id=opened_page.page_id,
                    close_read_pages=True,
                )
            else:
                already_read = False
        else:
            already_read = False
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
            "already_read": already_read,
            "read_status": "already_read" if already_read else "read",
            "extraction_count": opened_page.extraction_count
            if session is not None and target_page_id and opened_page is not None
            else 0,
        }

    async def view_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.snapshot.view_snapshot(**kwargs)

    async def view_navigate(
        self,
        *,
        browser_id: str,
        url: str,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        """Navigate the session-panel browser and return the rendered view."""

        session = await self._get_session(browser_id)
        target_url = _normalize_navigation_url(url)
        await self._goto(browser_id, session, target_url, allow_partial=True, wait_for_styles=wait_for_styles)
        final_url = _clean_browser_url(str(getattr(session.page, "url", target_url) or target_url))
        session.current_url = final_url
        session.last_open_url = final_url
        self._ensure_session_page_alias(browser_id, session)
        self._remember_current_url(browser_id, final_url)
        session.touch()
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    async def view_history(
        self,
        *,
        browser_id: str,
        direction: int,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        """Move the session-panel browser back or forward in its real page history."""

        session = await self._get_session(browser_id)
        page = self._preferred_session_page(session)
        session.page = page
        operation = getattr(page, "go_back" if direction < 0 else "go_forward", None)
        if not callable(operation):
            raise BrowserUnavailableError("LightPanda history navigation is unavailable.")
        with suppress(Exception):
            await operation(
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self.timeout_ms,
            )
        if wait_for_styles:
            await self._wait_for_page_visual_ready(page)
        final_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if final_url:
            session.current_url = final_url
            session.last_open_url = final_url
            self._remember_current_url(browser_id, final_url)
        session.touch()
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    async def view_reload(
        self,
        *,
        browser_id: str,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
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
                await operation(
                    wait_until="load" if wait_for_styles else "domcontentloaded",
                    timeout=self.timeout_ms,
                )
            except Exception as exc:
                if current_url.startswith(("http://", "https://")):
                    logger.warning("lightpanda_reload_falling_back_to_goto", url=current_url, error=str(exc))
                    await self._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
                else:
                    raise BrowserUnavailableError("LightPanda reload is unavailable.") from exc
        elif current_url.startswith(("http://", "https://")):
            await self._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
        else:
            raise BrowserUnavailableError("LightPanda reload is unavailable.")
        if wait_for_styles:
            await self._wait_for_page_visual_ready(page)
        session.touch()
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

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
        await self._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
            wait_for_styles=False,
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
        await self._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)

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
        return await self.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)

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
        previous_target = self._element_target(browser_id, normalized_node_id)
        previous_target_action = self._element_target(browser_id, str(target_node_id or "").strip())
        # The snapshot step injects stable data-pa-node-id attributes. Re-inject before acting
        # so agent tools can act after a fresh BrowserOpen without a visible UI snapshot. Keep
        # the previous target as a fallback because agent-visible node ids can outlive a fresh DOM
        # remap when the layout shifts between BrowserGetElementMap and BrowserClick.
        raw_map = await self.snapshot.browser_element_map(page)
        self._element_map_cache[browser_id] = self.snapshot.enrich_browser_element_map(
            raw_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        target = self._element_target(browser_id, normalized_node_id) or previous_target
        target_action = self._element_target(browser_id, str(target_node_id or "").strip()) or previous_target_action
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
                    "targetText": target.get("text"),
                    "targetHref": target.get("href"),
                    "targetRole": target.get("role"),
                    "targetTag": target.get("tag"),
                },
            )
        after_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        navigated = bool(after_url and after_url != before_url)
        if (not isinstance(result, Mapping) or not result.get("ok")) and not navigated:
            reason = ""
            if isinstance(result, Mapping):
                reason = str(result.get("reason") or "")
            raise BrowserError(reason or "Browser action failed.")
        await self._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        view = await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=viewport_width,
            height=viewport_height,
            wait_for_styles=False,
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
            "target": self._browser_action_target_payload(target, fallback_node_id=normalized_node_id),
            "result": dict(result) if isinstance(result, Mapping) else result,
        }
        return view

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserActions (Slice 3)
    # ------------------------------------------------------------------

    async def click(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.click(**kwargs)

    async def type_input(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.type_input(**kwargs)

    async def screenshot(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.screenshot(**kwargs)

    async def read_console(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.read_console(**kwargs)

    async def script(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.script(**kwargs)

    async def scroll(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.scroll(**kwargs)

    async def wait(self, **kwargs: Any) -> dict[str, Any]:
        return await self.actions.wait(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserPageLifecycle (Slice 4)
    # ------------------------------------------------------------------

    async def open(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.open(**kwargs)

    async def list_tabs(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.list_tabs(**kwargs)

    async def close_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.close_tab(**kwargs)

    async def reload(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.reload(**kwargs)

    async def history(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.history(**kwargs)

    async def switch_tab(self, **kwargs: Any) -> dict[str, Any]:
        return await self.lifecycle.switch_tab(**kwargs)

    # ------------------------------------------------------------------
    # Backward-compat delegations → BrowserSnapshot (Slice 5)
    # ------------------------------------------------------------------

    async def _browser_view_snapshot(
        self,
        browser_id: str,
        session: Any,
        *,
        width: int,
        height: int,
        cache_mode: str = "prefer_live",
        wait_for_styles: bool = True,
    ) -> dict[str, Any]:
        return await self.snapshot.browser_view_snapshot(
            browser_id,
            session,
            width=width,
            height=height,
            cache_mode=cache_mode,
            wait_for_styles=wait_for_styles,
        )

    def _enrich_browser_element_map(
        self,
        raw_map: list[dict[str, Any]],
        *,
        browser_id: str,
        tab_id: str,
    ) -> list[dict[str, Any]]:
        return self.snapshot.enrich_browser_element_map(raw_map, browser_id=browser_id, tab_id=tab_id)

    async def _browser_element_map(self, page: Any) -> list[dict[str, Any]]:
        return await self.snapshot.browser_element_map(page)

    async def _panel_session_tabs(
        self,
        *,
        max_tabs: int,
        exclude_conversation_id: str,
    ) -> list[dict[str, Any]]:
        return await self.snapshot.panel_session_tabs(
            max_tabs=max_tabs,
            exclude_conversation_id=exclude_conversation_id,
        )

    async def _html_with_embedded_stylesheet_fallbacks(
        self,
        html: str,
        current_url: str,
    ) -> tuple[str, dict[str, int]]:
        return await self.snapshot.html_with_embedded_stylesheet_fallbacks(html, current_url)

    async def _fetch_stylesheet_css(self, client: Any, href: str) -> tuple[str, bool]:
        return await self.snapshot.fetch_stylesheet_css(client, href)

    @staticmethod
    def _stylesheet_hrefs(html: str, current_url: str, *, max_hrefs: int) -> list[str]:
        return BrowserSnapshot.stylesheet_hrefs(html, current_url, max_hrefs=max_hrefs)

    @staticmethod
    def _html_attrs(tag: str) -> dict[str, str]:
        return BrowserSnapshot.html_attrs(tag)

    @staticmethod
    def _rewrite_css_urls(css_text: str, stylesheet_url: str) -> str:
        return BrowserSnapshot.rewrite_css_urls(css_text, stylesheet_url)

    @staticmethod
    def _css_fidelity(*, html: str, render_mode: str, embedded_stylesheet_count: int = 0) -> str:
        return BrowserSnapshot.css_fidelity(
            html=html, render_mode=render_mode, embedded_stylesheet_count=embedded_stylesheet_count
        )

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

    async def _wait_for_page_visual_ready(self, page: Any) -> dict[str, Any]:
        await self._wait_for_page_load_complete(page)
        metrics: dict[str, Any] = {
            "style_ready": True,
            "stylesheet_count": 0,
            "stylesheet_loaded_count": 0,
            "fonts_ready": True,
        }
        with suppress(Exception):
            value = await asyncio.wait_for(
                self._evaluate_page(page, _STYLE_READY_SNAPSHOT_SCRIPT),
                timeout=min(max(self.timeout_ms / 1000, 1.0), 5.0),
            )
            if isinstance(value, Mapping):
                metrics.update(
                    {
                        "style_ready": bool(value.get("style_ready", metrics["style_ready"])),
                        "stylesheet_count": int(value.get("stylesheet_count") or 0),
                        "stylesheet_loaded_count": int(value.get("stylesheet_loaded_count") or 0),
                        "fonts_ready": bool(value.get("fonts_ready", metrics["fonts_ready"])),
                    }
                )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        return metrics

    async def _wait_for_page_load_complete(self, page: Any, *, timeout_ms: int | None = None) -> None:
        wait_for_load_state = getattr(page, "wait_for_load_state", None)
        if not callable(wait_for_load_state):
            return
        with suppress(Exception):
            await wait_for_load_state("load", timeout=min(timeout_ms or self.timeout_ms, 5_000))

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

    @staticmethod
    def _browser_action_target_payload(
        target: Mapping[str, Any],
        *,
        fallback_node_id: str = "",
    ) -> dict[str, Any]:
        if not target and not fallback_node_id:
            return {}
        bounds = target.get("bounds") if isinstance(target.get("bounds"), Mapping) else {}
        return {
            "node_id": str(target.get("node_id") or fallback_node_id),
            "text": str(target.get("text") or ""),
            "role": str(target.get("role") or ""),
            "tag": str(target.get("tag") or ""),
            "selector": str(target.get("selector") or ""),
            "href": str(target.get("href") or ""),
            "bounds": dict(bounds),
        }

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

    async def _safe_scroll_state(self, page: Any) -> dict[str, int]:
        with suppress(Exception):
            value = await self._evaluate_page(
                page,
                """() => ({
                  scroll_x: Math.round(window.scrollX || document.documentElement.scrollLeft || 0),
                  scroll_y: Math.round(window.scrollY || document.documentElement.scrollTop || 0)
                })""",
            )
            if isinstance(value, Mapping):
                return {
                    "scroll_x": int(value.get("scroll_x") or 0),
                    "scroll_y": int(value.get("scroll_y") or 0),
                }
        return {"scroll_x": 0, "scroll_y": 0}

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

    async def _cleanup_live_pages(
        self,
        conversation_id: str,
        session: _BrowserSession,
        *,
        keep_page_id: str | None = None,
        close_read_pages: bool = False,
    ) -> None:
        live_entries = self._live_page_entries(session)
        if not live_entries:
            return
        keep_ids = {
            str(value or "").strip()
            for value in (keep_page_id, session.current_page_id, session.last_open_page_id)
            if str(value or "").strip()
        }
        candidates: list[tuple[int, float, set[str], Any]] = []
        for page_ids, page in live_entries:
            if keep_ids.intersection(page_ids):
                continue
            opened_pages = [
                opened_page
                for page_id in page_ids
                if (opened_page := self._opened_page(conversation_id, page_id)) is not None
            ]
            read = any(opened_page.extraction_count > 0 for opened_page in opened_pages)
            if close_read_pages and read:
                priority = 0
            elif len(live_entries) > _MAX_LIVE_PAGES_PER_SESSION:
                priority = 1 if read else 2
            else:
                continue
            opened_at = min((opened_page.opened_at for opened_page in opened_pages), default=time.monotonic())
            candidates.append((priority, opened_at, page_ids, page))
        live_count = len(live_entries)
        for _priority, _opened_at, page_ids, page in sorted(candidates, key=lambda item: (item[0], item[1])):
            if live_count <= _MAX_LIVE_PAGES_PER_SESSION and not close_read_pages:
                break
            await self._best_effort_resource_call("browser_live_page_close", page.close)
            for page_id in list(page_ids):
                session.pages.pop(page_id, None)
            live_count -= 1
        if session.current_page_id and session.current_page_id not in session.pages:
            session.current_page_id = keep_page_id or session.last_open_page_id
        if session.current_page_id and session.current_page_id in session.pages:
            session.page = session.pages[session.current_page_id]
        elif self._session_has_open_page(session):
            session.page = self._preferred_session_page(session)

    def _live_page_entries(self, session: _BrowserSession) -> list[tuple[set[str], Any]]:
        by_page_object: dict[int, tuple[set[str], Any]] = {}
        for page_id, page in session.pages.items():
            if not self._page_is_open(page):
                continue
            marker = id(page)
            if marker not in by_page_object:
                by_page_object[marker] = (set(), page)
            by_page_object[marker][0].add(page_id)
        return list(by_page_object.values())

    def _ensure_session_page_alias(
        self,
        conversation_id: str,
        session: _BrowserSession,
        *,
        page: Any | None = None,
        page_id: str | None = None,
    ) -> str:
        target_page_id = str(
            page_id
            or session.current_page_id
            or session.last_open_page_id
            or conversation_id
            or ""
        ).strip()
        if not target_page_id:
            target_page_id = conversation_id
        target_page = page or self._preferred_session_page(session)
        if target_page is not None and self._page_is_open(target_page):
            session.pages.setdefault(target_page_id, target_page)
        session.current_page_id = session.current_page_id or target_page_id
        session.last_open_page_id = session.last_open_page_id or target_page_id
        return target_page_id

    def _is_session_page_alias(
        self,
        conversation_id: str,
        session: _BrowserSession | None,
        page_id: str | None,
    ) -> bool:
        target_page_id = str(page_id or "").strip()
        if not target_page_id or session is None:
            return False
        if target_page_id == conversation_id:
            return True
        return target_page_id in {
            str(session.current_page_id or "").strip(),
            str(session.last_open_page_id or "").strip(),
        }

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
            if self._is_session_page_alias(conversation_id, session, target_page_id):
                page = self._preferred_session_page(session)
                if not self._page_is_open(page):
                    raise BrowserError(
                        f"No live browser page with page_id {target_page_id}. Run BrowserOpen again."
                    )
                session.pages[target_page_id] = page
            else:
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
            session.pages.setdefault(target_page_id, page)
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
        wait_for_styles: bool = True,
    ) -> None:
        try:
            await self._goto_page(session.page, url, allow_partial=allow_partial, wait_for_styles=wait_for_styles)
        except Exception:
            await self._close_session(conversation_id, session)
            raise

    async def _goto_page(
        self,
        page: Any,
        url: str,
        *,
        allow_partial: bool = False,
        wait_for_styles: bool = True,
    ) -> None:
        clean_url = _clean_browser_url(url)
        try:
            await page.goto(
                clean_url,
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self.timeout_ms,
            )
            if wait_for_styles:
                await self._wait_for_page_visual_ready(page)
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

    async def _install_cooperation_capture(self, page: Any, browser_id: str, page_id: str) -> None:
        key = (browser_id, page_id, id(page))
        if key not in self._cooperation_listener_keys:
            expose_function = getattr(page, "expose_function", None)
            if callable(expose_function):
                with suppress(Exception):
                    await expose_function(
                        "__personagentBrowserEvent",
                        lambda event: self._record_cooperation_event(browser_id, page_id, event),
                    )
            self._cooperation_listener_keys.add(key)
        with suppress(Exception):
            await self._evaluate_page(
                page,
                _COOPERATION_CAPTURE_SCRIPT,
                {"browserId": browser_id, "pageId": page_id},
            )

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

    async def _drain_cooperation_events(
        self,
        page: Any,
        browser_id: str,
        page_id: str,
    ) -> list[dict[str, Any]]:
        await self._install_cooperation_capture(page, browser_id, page_id)
        entries: list[dict[str, Any]] = []
        cached = self._cooperation_event_cache.setdefault(browser_id, {}).setdefault(page_id, [])
        if cached:
            entries.extend(cached[:200])
            del cached[:200]
        with suppress(Exception):
            drained = await self._evaluate_page(page, _COOPERATION_DRAIN_SCRIPT)
            if isinstance(drained, list):
                entries.extend(item for item in drained if isinstance(item, dict))
        return entries[-200:]

    def _record_cooperation_event(self, browser_id: str, page_id: str, event: Any) -> None:
        if not isinstance(event, Mapping):
            return
        payload = dict(event)
        payload.setdefault("source", "user")
        payload.setdefault("channel", "event")
        payload.setdefault("trace_role", "user")
        payload.setdefault("page_id", page_id)
        payload.setdefault("tab_id", page_id)
        page_cache = self._cooperation_event_cache.setdefault(browser_id, {}).setdefault(page_id, [])
        page_cache.append(payload)
        if len(page_cache) > 500:
            del page_cache[: len(page_cache) - 500]

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
            if page is None and self._is_session_page_alias(conversation_id, session, target_page_id):
                page = self._preferred_session_page(session)
                if page is not None and self._page_is_open(page):
                    session.pages[target_page_id] = page
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
    ) -> tuple[BrowserOpenedPage, bool]:
        url = _clean_browser_url(url)
        final_url = _clean_browser_url(final_url)
        pages = self._opened_pages_cache.setdefault(conversation_id, [])
        existing = self._opened_page_by_url(conversation_id, final_url) or self._opened_page_by_url(
            conversation_id,
            url,
        )
        if existing is not None:
            existing.url = url or existing.url
            existing.final_url = final_url or existing.final_url
            existing.title = title or existing.title
            existing.source_search_id = source_search_id or existing.source_search_id
            existing.opener_tool_call_id = opener_tool_call_id or existing.opener_tool_call_id
            existing.opened_at = time.monotonic()
            pages[:] = [page for page in pages if page.page_id != existing.page_id]
            pages.insert(0, existing)
            del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
            self._last_open_cache[conversation_id] = existing
            return existing, True
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
        pages.insert(0, opened_page)
        del pages[_MAX_OPENED_PAGES_PER_CONVERSATION:]
        self._last_open_cache[conversation_id] = opened_page
        return opened_page, False

    def _browser_open_response(
        self,
        *,
        conversation_id: str,
        opened_page: BrowserOpenedPage,
        requested_url: str,
        title: str,
        search_id: str | None,
        reused_existing_page: bool,
    ) -> dict[str, Any]:
        return {
            "type": "browser_open",
            "url": requested_url,
            "final_url": opened_page.final_url,
            "title": title or opened_page.title,
            "search_id": search_id,
            "page_id": opened_page.page_id,
            "window_id": opened_page.window_id,
            "opened_page_count": len(self._opened_pages_cache.get(conversation_id, [])),
            "recent_opened_pages": [
                page.to_dict() for page in self._opened_pages_cache.get(conversation_id, [])[:5]
            ],
            "reused_existing_page": reused_existing_page,
            "already_open": reused_existing_page,
            "already_read": opened_page.extraction_count > 0,
            "read_status": self._opened_page_read_status(opened_page),
            "extraction_count": opened_page.extraction_count,
        }

    def _mark_opened_page_extracted(self, opened_page: BrowserOpenedPage) -> None:
        opened_page.extraction_count += 1
        opened_page.last_extracted_at = time.monotonic()

    def _opened_page_read_status(self, opened_page: BrowserOpenedPage) -> str:
        return "read" if opened_page.extraction_count > 0 else "unread"

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
            "already_read": page.extraction_count > 0,
            "read_status": self._opened_page_read_status(page),
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

    def _opened_page_by_url(
        self,
        conversation_id: str,
        url: str,
    ) -> BrowserOpenedPage | None:
        target_url = _clean_browser_url(url)
        if not target_url:
            return None
        for opened_page in self._opened_pages_cache.get(conversation_id, []):
            if _urls_equivalent(opened_page.final_url, target_url) or _urls_equivalent(
                opened_page.url,
                target_url,
            ):
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
            if session is not None and self._is_session_page_alias(conversation_id, session, page_id):
                page = self._preferred_session_page(session)
                target_url = _clean_browser_url(
                    str(
                        getattr(page, "url", "")
                        or session.current_url
                        or session.last_open_url
                        or self._current_url_cache.get(conversation_id)
                        or ""
                    )
                )
                if target_url:
                    session.pages.setdefault(page_id, page)
                    return target_url, page_id
            if session is not None:
                page = session.pages.get(page_id)
                if page is not None and self._page_is_open(page):
                    target_url = _clean_browser_url(
                        str(
                            getattr(page, "url", "")
                            or session.current_url
                            or session.last_open_url
                            or self._current_url_cache.get(conversation_id)
                            or ""
                        )
                    )
                    if target_url:
                        return target_url, page_id
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
        if not pages:
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
                    self._cooperation_event_cache.pop(conversation_id, None)

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
        self._cooperation_event_cache.pop(conversation_id, None)
        get_browser_page_cache().clear_conversation(conversation_id)
        self._snapshot_cache.clear_conversation(conversation_id)
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


from personagent.infrastructure.browser.cdp_client import CdpClient as _RawCdpClient  # noqa: E402

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
