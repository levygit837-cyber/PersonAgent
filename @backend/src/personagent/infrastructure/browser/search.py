"""Browser search — URL building, provider scripts, and search execution.

Extracted from ``lightpanda.py`` as part of the god-file decomposition
(Slice 6).  ``BrowserSearch`` receives a back-reference to the worker
(``self._w``) and delegates infrastructure calls (page creation, CDP
evaluation, session management) through it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from personagent.infrastructure.browser.models import (
    BrowserSearchResult,
)
from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)

if TYPE_CHECKING:
    from personagent.infrastructure.browser.lightpanda import LightPandaBrowserWorker


# ---------------------------------------------------------------------------
# Search-results extraction scripts (one per provider)
# ---------------------------------------------------------------------------

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


def _search_results_script(provider: str) -> str:
    if provider == "yahoo":
        return _YAHOO_RESULTS_SCRIPT
    if provider == "bing":
        return _BING_RESULTS_SCRIPT
    if provider == "google":
        return _GOOGLE_RESULTS_SCRIPT
    return _GENERIC_RESULTS_SCRIPT


# ---------------------------------------------------------------------------
# BrowserSearch
# ---------------------------------------------------------------------------


class BrowserSearch:
    """Search-related methods extracted from ``LightPandaBrowserWorker``."""

    def __init__(self, worker: LightPandaBrowserWorker) -> None:
        self._w = worker

    # -- helpers (pure / sync) -----------------------------------------------

    @property
    def search_provider_label(self) -> str:
        return {
            "yahoo": "Yahoo",
            "bing": "Bing",
            "google": "Google",
            "generic": "the configured search provider",
        }.get(self._w.search_provider, self._w.search_provider)

    def search_url(self, query: str, *, max_results: int | None = None) -> str:
        parsed = urlparse(self._w.search_base_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if self._w.search_provider == "yahoo":
            params["p"] = query
            params.pop("q", None)
        else:
            params["q"] = query
        if self._w.search_provider == "google":
            params.update(
                {
                    "hl": params.get("hl") or "en",
                    "gl": params.get("gl") or "us",
                    "pws": params.get("pws") or "0",
                }
            )
        elif self._w.search_provider == "bing":
            params.update(
                {
                    "setlang": params.get("setlang") or "en-US",
                    "cc": params.get("cc") or "US",
                }
            )
        if max_results is not None:
            result_count = str(min(max(1, int(max_results)), 10))
            if self._w.search_provider == "bing":
                params["count"] = result_count
            elif self._w.search_provider == "yahoo":
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

    # -- main search method --------------------------------------------------

    async def search(
        self,
        *,
        conversation_id: str,
        query: str,
        max_results: int,
    ) -> dict[str, Any]:
        """Search the configured search provider in the conversation browser session."""

        session = await self._w.session_manager.get_session(conversation_id)
        search_url = self.search_url(query, max_results=max_results)
        resolved_search_url = search_url
        search_page = await self._w.session_manager.new_session_page(session)
        if search_page is not None:
            try:
                await self._w._goto_page(search_page, search_url)
                await self._w.block_detector.raise_if_search_blocked(search_page)
                extracted = await self._w._evaluate_page(
                    search_page,
                    _search_results_script(self._w.search_provider),
                    {"maxResults": max_results},
                )
                resolved_search_url = str(getattr(search_page, "url", search_url) or search_url)
            finally:
                if search_page is not session.page:
                    await self._w.session_manager.best_effort_resource_call(
                        "browser_search_page_close",
                        search_page.close,
                    )
        else:
            expression = (
                f"({_search_results_script(self._w.search_provider)})"
                f"({json.dumps({'maxResults': max_results})})"
            )
            extracted = await self._w._raw_runtime_evaluate_value(
                search_url,
                expression,
                label="search_results",
                timeout=min(self._w.timeout_ms / 1000, 12),
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
        snapshot = self._w.search_result_cache.cache_search_results(
            conversation_id=conversation_id,
            query=query,
            search_url=resolved_search_url,
            results=results,
        )
        session.search_results = self._w.search_result_cache.copy_search_results(snapshot.results)
        session.current_url = resolved_search_url
        self._w.search_result_cache.remember_current_url(conversation_id, session.current_url)
        session.touch()
        return {
            "type": "browser_search",
            "provider": self._w.search_provider,
            "query": query,
            "search_url": resolved_search_url,
            "search_id": snapshot.search_id,
            "cached_search_count": len(self._w._search_cache.get(conversation_id, [])),
            "results": [
                {**result.to_dict(), "search_id": snapshot.search_id} for result in snapshot.results
            ],
        }
