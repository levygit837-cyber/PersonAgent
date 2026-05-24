"""JavaScript injection scripts used by the LightPanda browser infrastructure.

Extracted from lightpanda.py as part of Slice 8 to keep the facade module lean.
"""

from __future__ import annotations

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
