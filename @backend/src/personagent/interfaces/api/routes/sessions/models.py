"""Pydantic request/response models for session routes."""

from typing import Any

from pydantic import BaseModel, Field


class SessionTitleVerifyRequest(BaseModel):
    """Request for batch session-title verification."""

    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    batch_size: int | None = Field(default=None, ge=1, le=50)
    force: bool = False
    dry_run: bool = False


class SessionBrowserViewport(BaseModel):
    """Viewport dimensions requested by the desktop session-panel browser."""

    width: int = Field(default=1024, ge=320, le=2400)
    height: int = Field(default=720, ge=240, le=1800)
    cache_mode: str = Field(default="prefer_live", pattern="^(prefer_live|prefer_cached)$")
    wait_for_styles: bool = True


class SessionBrowserNavigateRequest(SessionBrowserViewport):
    """Request to navigate a session-panel browser."""

    url: str = Field(min_length=1)


class SessionBrowserHistoryRequest(SessionBrowserViewport):
    """Request to move session-panel browser history."""

    direction: int = Field(ge=-1, le=1)


class SessionBrowserPointerRequest(SessionBrowserViewport):
    """Request to click a rendered session-panel browser viewport."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    button: str = "left"


class SessionBrowserKeyboardRequest(SessionBrowserViewport):
    """Request to type into the focused session-panel browser page."""

    text: str | None = None
    key: str | None = None


class SessionBrowserScrollRequest(SessionBrowserViewport):
    """Request to scroll a rendered session-panel browser viewport."""

    delta_x: float = 0
    delta_y: float = 0


class SessionBrowserActionRequest(SessionBrowserViewport):
    """Request to execute a mapped browser element action."""

    node_id: str = Field(min_length=1)
    action: str = Field(
        pattern="^(click|fill|submit|select|press|hover|wait|drag|drop|upload|select_text|scroll_to|screenshot)$"
    )
    value: str | None = None
    key: str | None = None
    target_node_id: str | None = None
    timeout_ms: int | None = Field(default=None, ge=1, le=120_000)
    files: list[str] | None = None
    text: str | None = None
    x: float | None = None
    y: float | None = None
    source: str = "user"


class SessionBrowserAnnotationRequest(BaseModel):
    """Create a persistent Browser Workspace annotation."""

    node_id: str = Field(min_length=1)
    body: str = Field(min_length=1, max_length=4000)
    quote: str | None = Field(default=None, max_length=4000)
    url: str | None = None
    title: str | None = None
    selector: str | None = None
    frame_id: str | None = None
    selector_chain: list[str] | None = None
    shadow_path: list[str] | None = None
    tab_id: str | None = None


class SessionBrowserCooperationRequest(BaseModel):
    """Toggle Browser Cooperation tracking/control for one Browser Workspace."""

    enabled: bool = True
    mode: str = Field(default="observe_only")


class SessionBrowserEventInput(BaseModel):
    """Raw Browser -> Agent event captured by the desktop browser mirror."""

    event_id: str | None = None
    id: str | None = None
    kind: str = Field(min_length=1)
    source: str = "user"
    channel: str | None = None
    trace_role: str | None = None
    visibility: str | None = None
    raw_kind: str | None = None
    timestamp: str | None = None
    tab_id: str | None = None
    page_id: str | None = None
    window_id: str | None = None
    url: str | None = None
    target: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    coordinates: dict[str, Any] | None = None
    duration_ms: int | None = None
    trace_effect: str | None = None
    correlation_id: str | None = None
    importance: str | None = None
    semantic_label: str | None = None
    label: str | None = None


class SessionBrowserEventBatchRequest(BaseModel):
    """Batch of browser cooperation events."""

    events: list[SessionBrowserEventInput] = Field(default_factory=list, max_length=100)
