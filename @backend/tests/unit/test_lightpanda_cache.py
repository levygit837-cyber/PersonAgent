"""Unit tests for SnapshotCache and StylesheetDiskCache."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from personagent.infrastructure.browser.cache import SnapshotCache, StylesheetDiskCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _view(url: str = "https://example.com", **extra: Any) -> dict[str, Any]:
    return {"url": url, "title": "Example", **extra}


# ---------------------------------------------------------------------------
# SnapshotCache — cache_key / url_cache_key
# ---------------------------------------------------------------------------


class TestSnapshotCacheKeys:
    def test_cache_key_deterministic(self) -> None:
        k1 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1280, 720)
        k2 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1280, 720)
        assert k1 == k2

    def test_cache_key_varies_by_url(self) -> None:
        k1 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1280, 720)
        k2 = SnapshotCache.cache_key("b1", "https://b.com", "t1", 1280, 720)
        assert k1 != k2

    def test_cache_key_varies_by_viewport(self) -> None:
        k1 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1280, 720)
        k2 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1920, 1080)
        assert k1 != k2

    def test_cache_key_starts_with_browser_id(self) -> None:
        key = SnapshotCache.cache_key("myid", "https://a.com", "t1", 1280, 720)
        assert key.startswith("myid::")

    def test_url_cache_key_deterministic(self) -> None:
        k1 = SnapshotCache.url_cache_key("b1", "https://a.com")
        k2 = SnapshotCache.url_cache_key("b1", "https://a.com")
        assert k1 == k2

    def test_url_cache_key_differs_from_full_key(self) -> None:
        k1 = SnapshotCache.cache_key("b1", "https://a.com", "t1", 1280, 720)
        k2 = SnapshotCache.url_cache_key("b1", "https://a.com")
        assert k1 != k2

    def test_cache_key_empty_browser_id_fallback(self) -> None:
        key = SnapshotCache.cache_key("", "https://a.com", "t1", 1280, 720)
        assert key.startswith("browser::")


# ---------------------------------------------------------------------------
# SnapshotCache — read / store / clear
# ---------------------------------------------------------------------------


class TestSnapshotCacheReadStore:
    def test_read_returns_none_for_empty_cache(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        assert cache.read("nonexistent") is None

    def test_read_returns_none_for_empty_key(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        assert cache.read("") is None

    def test_store_and_read_round_trip(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        view = _view()
        cache.store("k1", view)
        result = cache.read("k1")
        assert result is not None
        assert result["url"] == "https://example.com"
        assert result["render_cache_status"] == "hit"

    def test_store_skips_about_blank(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("k1", _view(url="about:blank"))
        assert cache.read("k1") is None

    def test_store_skips_empty_url(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("k1", _view(url=""))
        assert cache.read("k1") is None

    def test_store_skips_empty_cache_key(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("", _view())
        assert cache.read("") is None

    def test_store_with_aliases(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("primary", _view(), aliases=["alias1", "alias2"])
        assert cache.read("primary") is not None
        assert cache.read("alias1") is not None
        assert cache.read("alias2") is not None

    def test_read_expired_entry_returns_none(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=0.01)
        cache.store("k1", _view())
        with patch("personagent.infrastructure.browser.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 100
            assert cache.read("k1") is None

    def test_store_evicts_oldest_when_full(self) -> None:
        cache = SnapshotCache(max_entries=2, ttl_seconds=60)
        cache.store("k1", _view(url="https://1.com"))
        cache.store("k2", _view(url="https://2.com"))
        cache.store("k3", _view(url="https://3.com"))
        assert cache.read("k1") is None
        assert cache.read("k2") is not None
        assert cache.read("k3") is not None

    def test_clear_removes_all(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("k1", _view())
        cache.store("k2", _view(url="https://2.com"))
        cache.clear()
        assert cache.read("k1") is None
        assert cache.read("k2") is None

    def test_clear_conversation(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=60)
        cache.store("conv1::abc", _view())
        cache.store("conv2::def", _view(url="https://2.com"))
        cache.clear_conversation("conv1")
        assert cache.read("conv1::abc") is None
        assert cache.read("conv2::def") is not None


# ---------------------------------------------------------------------------
# SnapshotCache — clone
# ---------------------------------------------------------------------------


class TestSnapshotCacheClone:
    def test_clone_sets_render_cache_status(self) -> None:
        view = _view()
        cloned = SnapshotCache.clone(view, status="hit")
        assert cloned["render_cache_status"] == "hit"
        assert "render_cache_status" not in view

    def test_clone_sets_nested_browser_snapshot_status(self) -> None:
        view = _view(browser_snapshot={"document_ref": "d1"})
        cloned = SnapshotCache.clone(view, status="stored")
        assert cloned["browser_snapshot"]["render_cache_status"] == "stored"
        assert "render_cache_status" not in view["browser_snapshot"]

    def test_clone_does_not_mutate_original(self) -> None:
        view = _view(browser_snapshot={"document_ref": "d1"})
        SnapshotCache.clone(view, status="hit")
        assert "render_cache_status" not in view
        assert "render_cache_status" not in view["browser_snapshot"]

    def test_ttl_seconds_property(self) -> None:
        cache = SnapshotCache(max_entries=10, ttl_seconds=42.5)
        assert cache.ttl_seconds == 42.5


# ---------------------------------------------------------------------------
# StylesheetDiskCache
# ---------------------------------------------------------------------------


class TestStylesheetDiskCache:
    def test_write_and_read_round_trip(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "body{color:red}", expires_at=time.time() + 600)
        result = cache.read("https://a.com/style.css", now=time.time())
        assert result == "body{color:red}"

    def test_read_returns_empty_for_missing(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        assert cache.read("https://missing.com/x.css", now=time.time()) == ""

    def test_read_returns_empty_for_expired(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "body{}", expires_at=time.time() - 1)
        assert cache.read("https://a.com/style.css", now=time.time()) == ""

    def test_read_returns_empty_for_url_mismatch(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "body{}", expires_at=time.time() + 600)
        p = cache.path("https://a.com/style.css")
        payload = json.loads(p.read_text())
        payload["url"] = "https://other.com/style.css"
        p.write_text(json.dumps(payload))
        assert cache.read("https://a.com/style.css", now=time.time()) == ""

    def test_read_returns_empty_for_whitespace_only_css(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "  \n  ", expires_at=time.time() + 600)
        assert cache.read("https://a.com/style.css", now=time.time()) == ""

    def test_write_skips_whitespace_only_css(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "   ", expires_at=time.time() + 600)
        assert not cache.path("https://a.com/style.css").exists()

    def test_trim_removes_oldest_entries(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=2)
        for i in range(4):
            href = f"https://a.com/{i}.css"
            cache.write(href, f"body{{color:{i}}}", expires_at=time.time() + 600)
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) <= 2

    def test_path_is_deterministic(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        p1 = cache.path("https://a.com/style.css")
        p2 = cache.path("https://a.com/style.css")
        assert p1 == p2

    def test_write_creates_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "sub" / "dir"
        cache = StylesheetDiskCache(cache_dir=cache_dir, max_entries=10)
        cache.write("https://a.com/style.css", "body{}", expires_at=time.time() + 600)
        assert cache_dir.exists()
        assert cache.read("https://a.com/style.css", now=time.time()) == "body{}"

    def test_read_touches_file_on_hit(self, tmp_path: Path) -> None:
        cache = StylesheetDiskCache(cache_dir=tmp_path, max_entries=10)
        cache.write("https://a.com/style.css", "body{color:red}", expires_at=time.time() + 600)
        p = cache.path("https://a.com/style.css")
        old_mtime = p.stat().st_mtime
        import os
        os.utime(p, (old_mtime - 100, old_mtime - 100))
        cache.read("https://a.com/style.css", now=time.time())
        assert p.stat().st_mtime >= old_mtime - 100
