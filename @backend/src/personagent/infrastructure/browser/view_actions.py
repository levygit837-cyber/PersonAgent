"""Browser view-mode action wrappers.

Extracted from ``lightpanda.py`` as part of the god-file decomposition
(Slice 7).  Each ``view_*`` method wraps a low-level browser primitive
(navigate, click, key, scroll, etc.) with view-mode semantics: it
performs the action, then returns a fresh ``browser_view_snapshot``
so the caller always gets the resulting DOM state.

``BrowserViewActions`` receives a back-reference to the worker
(``self._w``) and delegates infrastructure calls through it.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import structlog

from personagent.infrastructure.browser.models import (
    BrowserError,
    BrowserUnavailableError,
)
from personagent.infrastructure.browser.url_utils import (
    clamped_viewport as _clamped_viewport,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)
from personagent.infrastructure.browser.url_utils import (
    normalize_navigation_url as _normalize_navigation_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker

logger = structlog.get_logger(__name__)

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


class BrowserViewActions:
    """View-mode action wrappers extracted from ``LightPandaBrowserWorker``."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

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

        session = await self._w.session_manager.get_session(browser_id)
        target_url = _normalize_navigation_url(url)
        await self._w._goto(browser_id, session, target_url, allow_partial=True, wait_for_styles=wait_for_styles)
        final_url = _clean_browser_url(str(getattr(session.page, "url", target_url) or target_url))
        session.current_url = final_url
        session.last_open_url = final_url
        self._w.session_manager.ensure_session_page_alias(browser_id, session)
        self._w.search_result_cache.remember_current_url(browser_id, final_url)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
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

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        operation = getattr(page, "go_back" if direction < 0 else "go_forward", None)
        if not callable(operation):
            raise BrowserUnavailableError("LightPanda history navigation is unavailable.")
        with suppress(Exception):
            await operation(
                wait_until="load" if wait_for_styles else "domcontentloaded",
                timeout=self._w.timeout_ms,
            )
        if wait_for_styles:
            await self._w.page_helpers.wait_for_page_visual_ready(page)
        final_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if final_url:
            session.current_url = final_url
            session.last_open_url = final_url
            self._w.search_result_cache.remember_current_url(browser_id, final_url)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
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

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        current_url = _clean_browser_url(
            str(getattr(page, "url", "") or session.current_url or session.last_open_url or "")
        )
        operation = getattr(page, "reload", None)
        if callable(operation):
            try:
                await operation(
                    wait_until="load" if wait_for_styles else "domcontentloaded",
                    timeout=self._w.timeout_ms,
                )
            except Exception as exc:
                if current_url.startswith(("http://", "https://")):
                    logger.warning("lightpanda_reload_falling_back_to_goto", url=current_url, error=str(exc))
                    await self._w._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
                else:
                    raise BrowserUnavailableError("LightPanda reload is unavailable.") from exc
        elif current_url.startswith(("http://", "https://")):
            await self._w._goto_page(page, current_url, allow_partial=True, wait_for_styles=wait_for_styles)
        else:
            raise BrowserUnavailableError("LightPanda reload is unavailable.")
        if wait_for_styles:
            await self._w.page_helpers.wait_for_page_visual_ready(page)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
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

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w._set_page_viewport(page, viewport_width, viewport_height)
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
        await self._w._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(
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

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
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
        await self._w._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)

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

        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        mouse = getattr(page, "mouse", None)
        wheel = getattr(mouse, "wheel", None)
        if callable(wheel):
            await wheel(float(delta_x), float(delta_y))
        else:
            await self._w._evaluate_page(
                page,
                "([deltaX, deltaY]) => window.scrollBy(deltaX, deltaY)",
                [float(delta_x), float(delta_y)],
            )
        with suppress(Exception):
            await page.wait_for_timeout(120)
        session.touch()
        return await self._w.snapshot.browser_view_snapshot(browser_id, session, width=width, height=height, wait_for_styles=False)

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
        session = await self._w.session_manager.get_session(browser_id)
        page = self._w._preferred_session_page(session)
        session.page = page
        viewport_width, viewport_height = _clamped_viewport(width, height)
        await self._w._set_page_viewport(page, viewport_width, viewport_height)
        previous_target = self._w._element_target(browser_id, normalized_node_id)
        previous_target_action = self._w._element_target(browser_id, str(target_node_id or "").strip())
        raw_map = await self._w.snapshot.browser_element_map(page)
        self._w._element_map_cache[browser_id] = self._w.snapshot.enrich_browser_element_map(
            raw_map,
            browser_id=browser_id,
            tab_id=session.current_page_id or browser_id,
        )
        target = self._w._element_target(browser_id, normalized_node_id) or previous_target
        target_action = self._w._element_target(browser_id, str(target_node_id or "").strip()) or previous_target_action
        cached_selector = str(target.get("selector") or "")
        target_selector = str(target_action.get("selector") or "")
        action_context = await self._w._action_context_for_element(page, target)
        before_url = _clean_browser_url(str(getattr(page, "url", "") or ""))
        if normalized_action == "upload":
            result = await self._w._upload_files(action_context, cached_selector, files or [])
        else:
            result = await self._w._evaluate_page(
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
        await self._w._wait_for_page_load_complete(page, timeout_ms=1_500)
        session.touch()
        view = await self._w.snapshot.browser_view_snapshot(
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
            "target": self._w._browser_action_target_payload(target, fallback_node_id=normalized_node_id),
            "result": dict(result) if isinstance(result, Mapping) else result,
        }
        return view
