"""Campos de configuração do LightPanda Browser."""

from pydantic import Field


class SettingsBrowserMixin:
    """Mixin com campos do navegador LightPanda."""

    # --- LightPanda Browser ---
    lightpanda_enabled: bool = Field(default=True, alias="LIGHTPANDA_ENABLED")
    lightpanda_cdp_url: str = Field(
        default="http://127.0.0.1:9222",
        alias="LIGHTPANDA_CDP_URL",
    )
    browser_cdp_url: str | None = Field(default=None, alias="BROWSER_CDP_URL")
    lightpanda_timeout_ms: int = Field(default=30_000, alias="LIGHTPANDA_TIMEOUT_MS")
    lightpanda_search_base_url: str = Field(
        default="https://search.yahoo.com/search",
        alias="LIGHTPANDA_SEARCH_BASE_URL",
    )
    lightpanda_session_ttl_seconds: int = Field(
        default=600,
        alias="LIGHTPANDA_SESSION_TTL_SECONDS",
    )
    lightpanda_max_sessions: int = Field(default=12, alias="LIGHTPANDA_MAX_SESSIONS")
    personagent_browser_page_cache_ttl_seconds: int = Field(
        default=1_800,
        alias="PERSONAGENT_BROWSER_PAGE_CACHE_TTL_SECONDS",
    )
    personagent_browser_page_cache_per_conversation: int = Field(
        default=8,
        alias="PERSONAGENT_BROWSER_PAGE_CACHE_PER_CONVERSATION",
    )
    personagent_browser_page_cache_global_entries: int = Field(
        default=128,
        alias="PERSONAGENT_BROWSER_PAGE_CACHE_GLOBAL_ENTRIES",
    )
    personagent_browser_render_cache_entries: int = Field(
        default=16,
        alias="PERSONAGENT_BROWSER_RENDER_CACHE_ENTRIES",
    )
    personagent_browser_render_cache_ttl_seconds: int = Field(
        default=180,
        alias="PERSONAGENT_BROWSER_RENDER_CACHE_TTL_SECONDS",
    )
    personagent_browser_css_cache_entries: int = Field(
        default=256,
        alias="PERSONAGENT_BROWSER_CSS_CACHE_ENTRIES",
    )
    personagent_browser_css_cache_ttl_seconds: int = Field(
        default=900,
        alias="PERSONAGENT_BROWSER_CSS_CACHE_TTL_SECONDS",
    )
