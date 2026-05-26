"""JavaScript injection scripts for browser content extraction.

Extracted from ``scripts.py`` (Slice 1 of scripts decomposition).
Consumed exclusively by ``content.py``.
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
