import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.interfaces.api.routes import workspace


class FakeSettings:
    def __init__(self, allowed_root: Path) -> None:
        self.tool_allowed_root_paths = [allowed_root]


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _workspace_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncClient:
    monkeypatch.setattr(workspace, "get_settings", lambda: FakeSettings(tmp_path))
    app = FastAPI()
    app.include_router(workspace.router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _init_committed_repo(repo: Path) -> None:
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.invalid")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# Repo\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial")
    _run_git(repo, "branch", "-M", "main")


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_branches_returns_non_repo_state(monkeypatch, tmp_path):
    workspace_root = tmp_path / "NoRepo"
    workspace_root.mkdir()

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/git-branches",
            params={"workspace_root": str(workspace_root)},
        )

    assert response.status_code == 200
    assert response.json() == {"is_repo": False, "current": "", "branches": []}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_branches_handles_empty_repo(monkeypatch, tmp_path):
    repo = tmp_path / "EmptyRepo"
    repo.mkdir()
    _run_git(repo, "init")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/git-branches",
            params={"workspace_root": str(repo)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_repo"] is True
    assert payload["branches"] == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_branches_lists_local_and_remote_branches(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    remote = tmp_path / "origin.git"
    _init_committed_repo(repo)
    _run_git(tmp_path, "init", "--bare", str(remote))
    _run_git(repo, "remote", "add", "origin", str(remote))
    _run_git(repo, "push", "-u", "origin", "main")
    _run_git(repo, "switch", "-c", "feature/local")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run_git(repo, "add", "feature.txt")
    _run_git(repo, "commit", "-m", "feature local")
    _run_git(repo, "switch", "main")
    _run_git(repo, "switch", "-c", "temp-remote")
    (repo / "remote.txt").write_text("remote\n", encoding="utf-8")
    _run_git(repo, "add", "remote.txt")
    _run_git(repo, "commit", "-m", "remote branch")
    _run_git(repo, "push", "origin", "temp-remote:remote-only")
    _run_git(repo, "switch", "main")
    _run_git(repo, "branch", "-D", "temp-remote")
    _run_git(repo, "fetch", "origin")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/git-branches",
            params={"workspace_root": str(repo)},
        )
        duplicate_checkout = await client.post(
            "/workspace/git-checkout",
            json={"workspace_root": str(repo), "name": "origin/main", "kind": "remote"},
        )
        checkout = await client.post(
            "/workspace/git-checkout",
            json={"workspace_root": str(repo), "name": "origin/remote-only", "kind": "remote"},
        )

    assert response.status_code == 200
    payload = response.json()
    branches = {(item["kind"], item["name"]): item for item in payload["branches"]}
    assert payload["is_repo"] is True
    assert payload["current"] == "main"
    assert branches[("local", "main")]["current"] is True
    assert branches[("local", "feature/local")]["last_commit_subject"] == "feature local"
    assert ("remote", "origin/main") not in branches
    assert ("remote", "origin/remote-only") in branches
    assert ("remote", "origin/HEAD") not in branches
    assert duplicate_checkout.status_code == 200
    assert duplicate_checkout.json()["branch"] == "main"
    assert checkout.status_code == 200
    assert checkout.json()["branch"] == "remote-only"
    assert _run_git(repo, "branch", "--show-current").stdout.strip() == "remote-only"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_create_branch_validates_name_and_switches(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)

    async with _workspace_client(monkeypatch, tmp_path) as client:
        invalid = await client.post(
            "/workspace/git-branches",
            json={"workspace_root": str(repo), "name": "bad branch"},
        )
        created = await client.post(
            "/workspace/git-branches",
            json={"workspace_root": str(repo), "name": "feature/new"},
        )

    assert invalid.status_code == 400
    assert created.status_code == 200
    assert created.json()["branch"] == "feature/new"
    assert _run_git(repo, "branch", "--show-current").stdout.strip() == "feature/new"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_checkout_switches_local_branch(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    _run_git(repo, "switch", "-c", "feature/checkout")
    _run_git(repo, "switch", "main")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post(
            "/workspace/git-checkout",
            json={"workspace_root": str(repo), "name": "feature/checkout", "kind": "local"},
        )

    assert response.status_code == 200
    assert response.json()["branch"] == "feature/checkout"
    assert _run_git(repo, "branch", "--show-current").stdout.strip() == "feature/checkout"
