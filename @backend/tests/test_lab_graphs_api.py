"""Testes das rotas de grafos do Lab."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.interfaces.api.routes import lab


class FakeLabGraphStore:
    """Store em memória para exercitar o contrato HTTP do Lab."""

    def __init__(self):
        self.graphs = {}

    async def list(self, limit: int, offset: int):
        values = list(self.graphs.values())
        return values[offset : offset + limit]

    async def create(self, request):
        graph_id = uuid4()
        now = datetime.now(UTC)
        graph = SimpleNamespace(
            id=graph_id,
            title=request.title,
            graph=request.graph,
            created_at=now,
            updated_at=now,
        )
        self.graphs[graph_id] = graph
        return graph

    async def get(self, graph_id: UUID):
        return self.graphs.get(graph_id)

    async def update(self, graph_id: UUID, request):
        graph = self.graphs.get(graph_id)
        if graph is None:
            return None
        if request.title is not None:
            graph.title = request.title
        if request.graph is not None:
            graph.graph = request.graph
        graph.updated_at = datetime.now(UTC)
        return graph

    async def delete(self, graph_id: UUID):
        return self.graphs.pop(graph_id, None) is not None


@pytest.fixture
def app_and_store():
    store = FakeLabGraphStore()
    app = FastAPI()
    app.include_router(lab.router)
    app.dependency_overrides[lab.get_lab_graph_store] = lambda: store
    return app, store


@pytest.mark.asyncio
async def test_lab_graph_crud_preserves_graph_document(app_and_store):
    app, _store = app_and_store
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post(
            "/lab/graphs",
            json={
                "title": "Research Graph",
                "graph": {
                    "viewport": {"x": 12, "y": -20, "zoom": 0.72},
                    "nodes": [{"id": "node_a", "type": "agentSession"}],
                    "edges": [],
                    "selected_node_id": "node_a",
                    "execution_state": {"mode": "idle"},
                    "trace_events": [],
                },
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()

        get_response = await client.get(f"/lab/graphs/{created['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["graph"]["viewport"]["zoom"] == 0.72

        update_response = await client.put(
            f"/lab/graphs/{created['id']}",
            json={
                "title": "Research Graph Updated",
                "graph": {
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                    "nodes": [{"id": "node_a"}, {"id": "node_b"}],
                    "edges": [{"id": "edge_ab", "from": "node_a", "to": "node_b"}],
                    "selected_node_id": "node_b",
                    "execution_state": {"mode": "running"},
                    "trace_events": [{"event": "node_started"}],
                },
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "Research Graph Updated"
        assert updated["graph"]["selected_node_id"] == "node_b"
        assert updated["graph"]["edges"][0]["id"] == "edge_ab"
        assert updated["graph"]["trace_events"][0]["event"] == "node_started"

        list_response = await client.get("/lab/graphs")
        assert list_response.status_code == 200
        assert [graph["id"] for graph in list_response.json()] == [created["id"]]

        delete_response = await client.delete(f"/lab/graphs/{created['id']}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"deleted": True}


@pytest.mark.asyncio
async def test_lab_graph_get_missing_returns_404(app_and_store):
    app, _store = app_and_store
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/lab/graphs/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Lab graph not found"
