from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.interfaces.api.routes import workspace


class FakeSettings:
    def __init__(self, allowed_root: Path) -> None:
        self.tool_allowed_root_paths = [allowed_root]


@pytest.mark.asyncio
async def test_workspace_files_are_restricted_to_requested_workspace(monkeypatch, tmp_path):
    allowed_root = tmp_path
    eval_root = tmp_path / "Eval"
    webpilot_root = tmp_path / "WebPilot"
    eval_root.mkdir()
    webpilot_root.mkdir()
    (webpilot_root / "webpilot.py").write_text("print('webpilot')", encoding="utf-8")

    monkeypatch.setattr(workspace, "get_settings", lambda: FakeSettings(allowed_root))

    app = FastAPI()
    app.include_router(workspace.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/workspace/files",
            params={"path": str(webpilot_root), "workspace_root": str(eval_root)},
        )

    assert response.status_code == 403
    assert "outside active workspace" in response.json()["detail"]


@pytest.mark.asyncio
async def test_workspace_file_reads_text_inside_requested_workspace(monkeypatch, tmp_path):
    allowed_root = tmp_path
    eval_root = tmp_path / "Eval"
    eval_root.mkdir()
    target = eval_root / "README.md"
    target.write_text("# Eval\n\ncontent", encoding="utf-8")

    monkeypatch.setattr(workspace, "get_settings", lambda: FakeSettings(allowed_root))

    app = FastAPI()
    app.include_router(workspace.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/workspace/file",
            params={"path": str(target), "workspace_root": str(eval_root)},
        )

    assert response.status_code == 200
    assert response.json() == {
        "path": str(target),
        "name": "README.md",
        "content": "# Eval\n\ncontent",
    }


@pytest.mark.asyncio
async def test_workspace_file_rejects_paths_outside_requested_workspace(monkeypatch, tmp_path):
    allowed_root = tmp_path
    eval_root = tmp_path / "Eval"
    webpilot_root = tmp_path / "WebPilot"
    eval_root.mkdir()
    webpilot_root.mkdir()
    target = webpilot_root / "webpilot.py"
    target.write_text("print('webpilot')", encoding="utf-8")

    monkeypatch.setattr(workspace, "get_settings", lambda: FakeSettings(allowed_root))

    app = FastAPI()
    app.include_router(workspace.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/workspace/file",
            params={"path": str(target), "workspace_root": str(eval_root)},
        )

    assert response.status_code == 403
    assert "outside active workspace" in response.json()["detail"]
