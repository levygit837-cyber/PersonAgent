"""In-memory render-snapshot cache and on-disk stylesheet cache."""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from personagent.infrastructure.browser.url_utils import (
    clean_browser_url as _clean_browser_url,
)


class SnapshotCache:
    """In-memory TTL cache for browser render snapshots."""

    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def clear(self) -> None:
        self._store.clear()

    def clear_conversation(self, conversation_id: str) -> None:
        for cache_key in [key for key in self._store if key.startswith(f"{conversation_id}::")]:
            self._store.pop(cache_key, None)

    @staticmethod
    def cache_key(
        browser_id: str,
        current_url: str,
        active_tab_id: str,
        width: int,
        height: int,
    ) -> str:
        raw = "|".join(
            [
                browser_id or "browser",
                active_tab_id or browser_id or "page",
                _clean_browser_url(current_url or "about:blank"),
                str(int(width)),
                str(int(height)),
            ]
        )
        return "::".join([browser_id or "browser", hashlib.sha256(raw.encode("utf-8")).hexdigest()])

    @staticmethod
    def url_cache_key(browser_id: str, current_url: str) -> str:
        raw = "|".join([browser_id or "browser", _clean_browser_url(current_url or "about:blank")])
        return "::".join([browser_id or "browser", "url", hashlib.sha256(raw.encode("utf-8")).hexdigest()])

    def read(self, cache_key: str) -> dict[str, Any] | None:
        if not cache_key:
            return None
        now = time.time()
        cached = self._store.get(cache_key)
        if cached is None:
            return None
        expires_at, view = cached
        if expires_at <= now:
            self._store.pop(cache_key, None)
            return None
        return self.clone(view, status="hit")

    def store(
        self,
        cache_key: str,
        view: dict[str, Any],
        *,
        aliases: list[str] | None = None,
    ) -> None:
        if not cache_key or not view.get("url") or view.get("url") == "about:blank":
            return
        now = time.time()
        for key in [cache_key, *(aliases or [])]:
            if not key:
                continue
            self._store.pop(key, None)
            self._store[key] = (
                now + self._ttl_seconds,
                self.clone(view, status="stored"),
            )
        if len(self._store) > self._max_entries:
            expired = [key for key, (expires_at, _) in self._store.items() if expires_at <= now]
            for key in expired:
                self._store.pop(key, None)
            while len(self._store) > self._max_entries:
                self._store.pop(next(iter(self._store)))

    @staticmethod
    def clone(view: dict[str, Any], *, status: str) -> dict[str, Any]:
        cloned = dict(view)
        cloned["render_cache_status"] = status
        if isinstance(cloned.get("browser_snapshot"), dict):
            snapshot = dict(cloned["browser_snapshot"])
            snapshot["render_cache_status"] = status
            cloned["browser_snapshot"] = snapshot
        return cloned


class StylesheetDiskCache:
    """On-disk TTL cache for fetched CSS stylesheets."""

    def __init__(self, *, cache_dir: Path, max_entries: int) -> None:
        self._cache_dir = cache_dir
        self._max_entries = max(1, int(max_entries))

    def path(self, href: str) -> Path:
        digest = hashlib.sha256(href.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def read(self, href: str, *, now: float) -> str:
        p = self.path(href)
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if str(payload.get("url") or "") != href:
            return ""
        if float(payload.get("expires_at") or 0) <= now:
            with suppress(Exception):
                p.unlink()
            return ""
        css_text = str(payload.get("css") or "")
        if not css_text.strip():
            return ""
        with suppress(Exception):
            p.touch()
        return css_text

    def write(self, href: str, css_text: str, *, expires_at: float) -> None:
        if not css_text.strip():
            return
        with suppress(Exception):
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            p = self.path(href)
            tmp_path = p.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps({"url": href, "expires_at": expires_at, "css": css_text}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(p)
            self.trim()

    def trim(self) -> None:
        with suppress(Exception):
            entries = sorted(
                self._cache_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for p in entries[self._max_entries:]:
                with suppress(Exception):
                    p.unlink()
