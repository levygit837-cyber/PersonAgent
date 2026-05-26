"""Browser act script injected into the page for DOM actions."""

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
