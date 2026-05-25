"""JavaScript injection scripts for browser snapshot generation.

Extracted from ``scripts.py`` (Slice 2 of scripts decomposition).
Consumed exclusively by ``snapshot.py``.
"""

from __future__ import annotations

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
