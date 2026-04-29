"""Contracts for QA indexing, sandbox sessions, and runtime traces."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TraceMode(StrEnum):
    """Runtime trace depth for a QA request."""

    FUNCTION = "function"
    BLOCKS = "blocks"
    LINE = "line"


class QASessionStatus(StrEnum):
    """Lifecycle status for a QA session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class QARequestRunStatus(StrEnum):
    """Lifecycle status for one executed request."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CodeNodeKind(StrEnum):
    """Stable code graph node kinds exposed to agents."""

    ENDPOINT = "endpoint"
    CONTROLLER = "controller"
    MIDDLEWARE = "middleware"
    SERVICE = "service"
    REPOSITORY = "repository"
    MODEL = "model"
    SCHEMA = "schema"
    FUNCTION = "function"
    EXTERNAL_HTTP = "external_http"
    SQL = "sql"
    QUEUE_EVENT = "queue_event"
    TEST = "test"
    CONFIG = "config"
    FILE = "file"


class CodeEdgeKind(StrEnum):
    """Stable code graph edge kinds exposed to agents."""

    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS_STATIC = "calls_static"
    ROUTES_TO = "routes_to"
    DEPENDS_ON = "depends_on"
    USES_MODEL = "uses_model"
    EXECUTES_SQL = "executes_sql"
    CALLS_EXTERNAL_HTTP = "calls_external_http"
    COVERED_BY_TEST = "covered_by_test"
    RUNTIME_CALLED = "runtime_called"


class RuntimeEventType(StrEnum):
    """Runtime events captured by the Python tracer."""

    REQUEST = "request"
    CALL = "call"
    RETURN = "return"
    LINE = "line"
    EXCEPTION = "exception"
    RESPONSE = "response"


class QASessionCreateRequest(BaseModel):
    """Create a sandboxed QA debugging session."""

    model_config = ConfigDict(populate_by_name=True)

    repo_root: str = Field(..., description="Repository root to analyze.")
    base_commit: str | None = Field(default=None, description="Commit SHA or ref to pin.")
    branch_mode: Literal["current", "worktree"] = Field(
        default="current",
        description="Use current checkout or create an isolated git worktree.",
    )
    env_profile: dict[str, str] | str | None = Field(
        default=None,
        description="Named env profile or explicit env var map for the QA session.",
    )
    trace_mode: TraceMode = Field(default=TraceMode.FUNCTION)
    agent_id: str | None = Field(default=None)


class QAIndexRequest(BaseModel):
    """Options for building the static code graph."""

    include_tests: bool = True
    force: bool = False


class QARequestRunRequest(BaseModel):
    """Execute one request inside the QA session."""

    model_config = ConfigDict(populate_by_name=True)

    method: str = Field(default="GET")
    path: str = Field(..., description="ASGI path to execute, for example /workspace/files.")
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any | None = Field(default=None, alias="json")
    body: str | bytes | None = None
    trace_mode: TraceMode | None = None
    timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)


class CodeNodeData(BaseModel):
    """Serializable code graph node."""

    id: str
    kind: CodeNodeKind
    name: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeEdgeData(BaseModel):
    """Serializable code graph edge."""

    id: str
    kind: CodeEdgeKind
    source_id: str
    target_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QACodeGraph(BaseModel):
    """Static code graph plus summary stats."""

    nodes: list[CodeNodeData] = Field(default_factory=list)
    edges: list[CodeEdgeData] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


class QASessionData(BaseModel):
    """Persisted QA session returned by the API."""

    id: str
    repo_root: str
    sandbox_path: str | None = None
    base_commit: str | None = None
    branch_name: str | None = None
    branch_mode: str
    env_profile: dict[str, Any] | str | None = None
    trace_mode: TraceMode
    agent_id: str | None = None
    status: QASessionStatus = QASessionStatus.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class QARuntimeEventData(BaseModel):
    """Runtime event captured during a request execution."""

    id: str
    session_id: str
    request_id: str | None = None
    sequence: int
    trace_id: str
    span_id: str | None = None
    parent_id: str | None = None
    event_type: RuntimeEventType
    function: str | None = None
    file: str | None = None
    line: int | None = None
    duration_ms: float | None = None
    exception: str | None = None
    sanitized_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class QARequestRunData(BaseModel):
    """Persisted result of one request executed under QA tracing."""

    id: str
    session_id: str
    method: str
    path: str
    status: QARequestRunStatus
    trace_id: str
    status_code: int | None = None
    duration_ms: float | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class QAGraphResponse(BaseModel):
    """Static graph plus runtime overlay for a session."""

    session: QASessionData
    graph: QACodeGraph
    runtime_edges: list[CodeEdgeData] = Field(default_factory=list)


class QAContextResponse(BaseModel):
    """Agent-ready QA debugging context."""

    session: QASessionData
    summary: str
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    recent_requests: list[QARequestRunData] = Field(default_factory=list)
    relevant_events: list[QARuntimeEventData] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
