from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.adapters.api.main import app as personagent_app
from personagent.adapters.api.routes import workspace
from personagent.application.qa.contracts import RuntimeEventType, TraceMode
from personagent.application.qa.indexer import PythonCodeIndexer
from personagent.application.qa.redaction import redact_mapping
from personagent.application.qa.runtime_tracer import PythonRuntimeTracer
from personagent.infrastructure.persistence import models as _models  # noqa: F401
from personagent.infrastructure.persistence.database import Base


class FakeSettings:
    def __init__(self, allowed_root: Path) -> None:
        self.tool_allowed_root_paths = [allowed_root]


def test_python_code_indexer_maps_fastapi_routes_symbols_and_operations(tmp_path: Path) -> None:
    route_dir = tmp_path / "@backend" / "src" / "personagent" / "interfaces" / "api" / "routes"
    route_dir.mkdir(parents=True)
    (route_dir / "transfers.py").write_text(
        """
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
import httpx

router = APIRouter(prefix="/transfers")

class TransferDTO(BaseModel):
    amount: int

async def get_db():
    return None

@router.post("", response_model=TransferDTO)
async def create_transfer(payload: TransferDTO, db=Depends(get_db)):
    stmt = select(TransferDTO)
    raw = text("select 1")
    async with httpx.AsyncClient() as client:
        await client.get("https://example.invalid/score")
    return payload
""",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "@backend" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_transfers.py").write_text(
        "from personagent.adapters.api.routes import transfers\n\n"
        "def test_create_transfer():\n"
        "    assert transfers.router\n",
        encoding="utf-8",
    )

    graph = PythonCodeIndexer(tmp_path).build()

    endpoint_names = {node.name for node in graph.nodes if node.kind.value == "endpoint"}
    node_kinds = {node.kind.value for node in graph.nodes}
    edge_kinds = {edge.kind.value for edge in graph.edges}

    assert "POST /transfers" in endpoint_names
    assert {"schema", "controller", "external_http", "sql", "test"}.issubset(node_kinds)
    assert {"routes_to", "executes_sql", "calls_external_http", "covered_by_test"}.issubset(edge_kinds)


def test_personagent_smoke_index_contains_current_backend_endpoints() -> None:
    repo_root = Path.cwd().parent

    graph = PythonCodeIndexer(repo_root, app=personagent_app).build()
    endpoint_names = {node.name for node in graph.nodes if node.kind.value == "endpoint"}

    assert "GET /workspace/files" in endpoint_names
    assert "POST /chat/completions/stream" in endpoint_names
    assert "GET /sessions/{conversation_id}/panel" in endpoint_names
    assert graph.stats["endpoint_count"] >= 20


@pytest.mark.asyncio
async def test_runtime_tracer_captures_real_lines_for_workspace_requests(monkeypatch, tmp_path):
    project = tmp_path / "Project"
    project.mkdir()
    target = project / "README.md"
    target.write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(workspace, "get_settings", lambda: FakeSettings(tmp_path))

    app = FastAPI()
    app.include_router(workspace.router)
    tracer = PythonRuntimeTracer()
    source_root = Path.cwd() / "src" / "personagent"

    async def list_operation():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(
                "/workspace/files",
                params={"path": str(project), "workspace_root": str(project)},
            )

    response, events, trace_id = await tracer.capture(
        session_id="session-a",
        request_id="request-a",
        source_roots=[source_root],
        mode=TraceMode.LINE,
        request_payload={"path": "/workspace/files"},
        operation=list_operation,
    )

    assert response.status_code == 200
    assert trace_id
    assert any(
        event.event_type == RuntimeEventType.CALL
        and event.function == "list_workspace_files"
        and event.file == "interfaces/api/routes/workspace.py"
        for event in events
    )
    assert any(
        event.event_type == RuntimeEventType.LINE
        and event.file == "interfaces/api/routes/workspace.py"
        for event in events
    )

    async def read_operation():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(
                "/workspace/file",
                params={"path": str(target), "workspace_root": str(project)},
            )

    response, events, _ = await tracer.capture(
        session_id="session-a",
        request_id="request-b",
        source_roots=[source_root],
        mode=TraceMode.FUNCTION,
        request_payload={"path": "/workspace/file"},
        operation=read_operation,
    )

    assert response.status_code == 200
    assert any(event.function == "read_workspace_file" for event in events)
    assert not any(event.function == "list_workspace_files" for event in events)


def test_qa_redaction_removes_sensitive_values() -> None:
    payload = redact_mapping(
        {
            "Authorization": "Bearer secret",
            "nested": {"api_key": "secret-key", "normal": "visible"},
            "body": "hello",
        }
    )

    assert payload["Authorization"] == "[REDACTED]"
    assert payload["nested"]["api_key"] == "[REDACTED]"
    assert payload["nested"]["normal"] == "visible"
    assert payload["body"] == "hello"


def test_qa_tables_are_registered_in_sqlalchemy_metadata() -> None:
    expected = {
        "qa_sessions",
        "qa_code_nodes",
        "qa_code_edges",
        "qa_request_runs",
        "qa_runtime_events",
        "qa_artifacts",
    }

    assert expected.issubset(set(Base.metadata.tables))
