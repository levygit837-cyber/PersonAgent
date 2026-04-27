"""Tests for the public workflow API."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.interfaces.api.routes import workflows


class FakeWorkflowStore:
    """In-memory workflow store for API contract tests."""

    def __init__(self) -> None:
        self.workflows: dict[UUID, SimpleNamespace] = {}

    async def list(self, limit: int, offset: int):
        values = list(self.workflows.values())
        return values[offset : offset + limit]

    async def create(self, title: str, workflow: dict):
        workflow_id = uuid4()
        now = datetime.now(UTC)
        record = SimpleNamespace(
            id=workflow_id,
            title=title,
            graph=workflow,
            created_at=now,
            updated_at=now,
        )
        self.workflows[workflow_id] = record
        return record

    async def get(self, workflow_id: UUID):
        return self.workflows.get(workflow_id)

    async def update(
        self,
        workflow_id: UUID,
        *,
        title: str | None = None,
        workflow: dict | None = None,
    ):
        record = self.workflows.get(workflow_id)
        if record is None:
            return None
        if title is not None:
            record.title = title
        if workflow is not None:
            record.graph = workflow
        record.updated_at = datetime.now(UTC)
        return record

    async def delete(self, workflow_id: UUID):
        return self.workflows.pop(workflow_id, None) is not None


@pytest.fixture
def app_and_store():
    store = FakeWorkflowStore()
    app = FastAPI()
    app.include_router(workflows.router)
    app.dependency_overrides[workflows.get_workflow_store] = lambda: store
    return app, store


@pytest.mark.asyncio
async def test_workflow_crud_uses_public_contract(app_and_store):
    app, _store = app_and_store
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/workflows", json={"title": "Research Flow"})
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["title"] == "Research Flow"
        assert created["workflow"]["schema_version"] == "1.0"
        assert created["workflow"]["nodes"][0]["type"] == "manual_trigger"

        workflow_id = created["id"]
        get_response = await client.get(f"/workflows/{workflow_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == workflow_id

        updated_workflow = created["workflow"]
        updated_workflow["nodes"][0]["title"] = "Manual Start"
        update_response = await client.put(
            f"/workflows/{workflow_id}",
            json={"title": "Research Flow Updated", "workflow": updated_workflow},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "Research Flow Updated"
        assert updated["workflow"]["nodes"][0]["title"] == "Manual Start"

        list_response = await client.get("/workflows")
        assert list_response.status_code == 200
        assert [workflow["id"] for workflow in list_response.json()] == [workflow_id]

        delete_response = await client.delete(f"/workflows/{workflow_id}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"deleted": True}


@pytest.mark.asyncio
async def test_workflow_update_rejects_invalid_contract(app_and_store):
    app, _store = app_and_store
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/workflows", json={"title": "Invalidable"})
        workflow_id = create_response.json()["id"]

        response = await client.put(
            f"/workflows/{workflow_id}",
            json={
                "workflow": {
                    "schema_version": "1.0",
                    "nodes": [
                        {
                            "id": "agent",
                            "type": "agent",
                            "title": "Agent",
                        }
                    ],
                    "edges": [],
                }
            },
        )

    assert response.status_code == 400
    assert "manual trigger" in response.json()["detail"]


@pytest.mark.asyncio
async def test_workflow_node_type_catalog_exposes_v1_and_future_nodes(app_and_store):
    app, _store = app_and_store
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/workflows/node-types")

    assert response.status_code == 200
    catalog = response.json()
    node_types = {item["type"]: item for item in catalog["node_types"]}
    assert node_types["agent"]["executable"] is True
    assert node_types["browser"]["future"] is True
    assert "tools" in catalog["supported_perks"]
    assert "database" in catalog["unsupported_perks"]
