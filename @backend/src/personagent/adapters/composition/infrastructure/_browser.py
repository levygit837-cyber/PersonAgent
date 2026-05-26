"""Browser worker mixin."""

from personagent.infrastructure.browser import LightPandaBrowserWorker
from personagent.infrastructure.browser.page.cache import get_browser_page_cache


class _BrowserMixin:
    def get_lightpanda_browser_worker(self) -> LightPandaBrowserWorker:
        """Retorna o worker LightPanda usado pelas ferramentas de browser."""
        if self._lightpanda_browser_worker is None:
            get_browser_page_cache().configure(
                root=self._settings.personagent_artifact_root,
                ttl_seconds=self._settings.personagent_browser_page_cache_ttl_seconds,
                per_conversation_limit=self._settings.personagent_browser_page_cache_per_conversation,
                global_limit=self._settings.personagent_browser_page_cache_global_entries,
            )
            self._lightpanda_browser_worker = LightPandaBrowserWorker(
                enabled=self._settings.lightpanda_enabled,
                cdp_url=self._settings.browser_cdp_url or self._settings.lightpanda_cdp_url,
                timeout_ms=self._settings.lightpanda_timeout_ms,
                search_base_url=self._settings.lightpanda_search_base_url,
                session_ttl_seconds=self._settings.lightpanda_session_ttl_seconds,
                max_sessions=self._settings.lightpanda_max_sessions,
                artifact_root=self._settings.personagent_artifact_root,
                render_cache_entries=self._settings.personagent_browser_render_cache_entries,
                render_cache_ttl_seconds=self._settings.personagent_browser_render_cache_ttl_seconds,
                css_cache_entries=self._settings.personagent_browser_css_cache_entries,
                css_cache_ttl_seconds=self._settings.personagent_browser_css_cache_ttl_seconds,
                auto_start_lightpanda=not bool(self._settings.browser_cdp_url),
            )
        return self._lightpanda_browser_worker

    async def close_browser_workers(self) -> None:
        """Close browser workers initialized by tools."""
        if self._lightpanda_browser_worker is not None:
            await self._lightpanda_browser_worker.close()
            self._lightpanda_browser_worker = None
