import json
import os
import shutil
import subprocess
import time
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


@pytest.mark.asyncio
async def test_workspace_mentions_returns_file_and_directory_suggestions(monkeypatch, tmp_path):
    project = tmp_path / "Project"
    source_dir = project / "src" / "components"
    source_dir.mkdir(parents=True)
    target = source_dir / "InputDock.tsx"
    target.write_text("export function InputDock() {}", encoding="utf-8")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/mentions",
            params={"workspace_root": str(project), "q": "input"},
        )
        directory_response = await client.get(
            "/workspace/mentions",
            params={"workspace_root": str(project), "q": "components"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["type"] == "file"
    assert payload[0]["path"] == str(target)
    assert payload[0]["display_path"] == "src/components/InputDock.tsx"
    assert directory_response.status_code == 200
    assert any(
        item["type"] == "directory" and item["display_path"] == "src/components/"
        for item in directory_response.json()
    )


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
    linked_worktree = tmp_path / "linked-worktree"
    _run_git(repo, "worktree", "add", "-b", "locked/worktree", str(linked_worktree), "main")

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
        locked_checkout = await client.post(
            "/workspace/git-checkout",
            json={"workspace_root": str(repo), "name": "locked/worktree", "kind": "local"},
        )

    assert response.status_code == 200
    payload = response.json()
    branches = {(item["kind"], item["name"]): item for item in payload["branches"]}
    assert payload["is_repo"] is True
    assert payload["current"] == "main"
    assert branches[("local", "main")]["current"] is True
    assert branches[("local", "feature/local")]["last_commit_subject"] == "feature local"
    assert branches[("local", "locked/worktree")]["checked_out_elsewhere"] is True
    assert branches[("local", "locked/worktree")]["worktree_path"] == str(linked_worktree)
    assert ("remote", "origin/main") not in branches
    assert ("remote", "origin/remote-only") in branches
    assert ("remote", "origin/HEAD") not in branches
    assert duplicate_checkout.status_code == 200
    assert duplicate_checkout.json()["branch"] == "main"
    assert checkout.status_code == 200
    assert checkout.json()["branch"] == "remote-only"
    assert _run_git(repo, "branch", "--show-current").stdout.strip() == "remote-only"
    assert locked_checkout.status_code == 409
    assert "already checked out in another worktree" in locked_checkout.json()["detail"]


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
async def test_git_create_worktree_adds_unique_branch_without_switching(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post(
            "/workspace/git-worktrees",
            json={"workspace_root": str(repo), "name": "agent-output"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["branch"] == "personagent/agent-output"
    assert Path(payload["path"]).is_dir()
    assert _run_git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert _run_git(Path(payload["path"]), "branch", "--show-current").stdout.strip() == "personagent/agent-output"


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_commit_stages_changes_and_returns_commit_metadata(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    (repo / "README.md").write_text("# Repo\n\nUpdated\n", encoding="utf-8")
    (repo / "notes.txt").write_text("notes\n", encoding="utf-8")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post(
            "/workspace/git-commit",
            json={"workspace_root": str(repo), "message": "Update docs"},
        )
        status = await client.get("/workspace/git-status", params={"workspace_root": str(repo)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["message"] == "Update docs"
    assert payload["short_sha"]
    assert status.json()["is_dirty"] is False
    assert _run_git(repo, "log", "-1", "--format=%s").stdout.strip() == "Update docs"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_commit_removes_stale_index_lock_before_staging(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    (repo / "README.md").write_text("# Repo\n\nUpdated\n", encoding="utf-8")
    lock_path = repo / ".git" / "index.lock"
    lock_path.write_text("", encoding="utf-8")
    stale_time = time.time() - workspace.STALE_GIT_INDEX_LOCK_SECONDS - 60
    os.utime(lock_path, (stale_time, stale_time))

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post(
            "/workspace/git-commit",
            json={"workspace_root": str(repo), "message": "Update docs"},
        )

    assert response.status_code == 200
    assert not lock_path.exists()
    assert _run_git(repo, "log", "-1", "--format=%s").stdout.strip() == "Update docs"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_commit_can_auto_generate_message(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    (repo / "notes.txt").write_text("notes\n", encoding="utf-8")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        message_response = await client.get(
            "/workspace/git-commit-message",
            params={"workspace_root": str(repo)},
        )
        commit_response = await client.post(
            "/workspace/git-commit",
            json={"workspace_root": str(repo), "auto_generate_message": True},
        )

    assert message_response.status_code == 200
    assert message_response.json()["message"] == "Add notes.txt"
    assert commit_response.status_code == 200
    assert commit_response.json()["message"] == "Add notes.txt"
    assert _run_git(repo, "log", "-1", "--format=%s").stdout.strip() == "Add notes.txt"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_push_pushes_current_branch_to_origin(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    remote = tmp_path / "origin.git"
    _init_committed_repo(repo)
    _run_git(tmp_path, "init", "--bare", str(remote))
    _run_git(repo, "remote", "add", "origin", str(remote))
    _run_git(repo, "push", "-u", "origin", "main")
    _run_git(repo, "switch", "-c", "feature/push")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _run_git(repo, "add", "feature.txt")
    _run_git(repo, "commit", "-m", "feature push")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post("/workspace/git-push", json={"workspace_root": str(repo)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["branch"] == "feature/push"
    assert payload["upstream"] == "origin/feature/push"
    assert _run_git(remote, "rev-parse", "--verify", "refs/heads/feature/push").stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_recent_actions_lists_local_commits(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    (repo / "notes.txt").write_text("notes\n", encoding="utf-8")
    _run_git(repo, "add", "notes.txt")
    _run_git(repo, "commit", "-m", "Add notes")

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/git-recent-actions",
            params={"workspace_root": str(repo)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_repo"] is True
    commit_actions = [item for item in payload["actions"] if item["type"] == "commit"]
    assert commit_actions[0]["title"] == "Add notes"
    assert commit_actions[0]["subtitle"].startswith(
        _run_git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_workspace_projects_lists_git_repositories(monkeypatch, tmp_path):
    personagent = tmp_path / "PersonAgent"
    webpilot = tmp_path / "WebPilot"
    _init_committed_repo(personagent)
    _init_committed_repo(webpilot)
    (tmp_path / "NotRepo").mkdir()

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get("/workspace/projects")

    assert response.status_code == 200
    projects = {item["name"]: item for item in response.json()["projects"]}
    assert projects["PersonAgent"]["path"] == str(personagent)
    assert projects["WebPilot"]["path"] == str(webpilot)
    assert "NotRepo" not in projects


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_pull_requests_normalizes_pr_comments(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    original_run_command = workspace._run_command

    def fake_run_command(cwd, args, timeout=10):
        if args[:3] == ["gh", "api", "user"]:
            return subprocess.CompletedProcess(args, 0, "levy\n", "")
        if args[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps(
                    [
                        {
                            "additions": 120,
                            "author": {"login": "levy", "is_bot": False},
                            "baseRefName": "main",
                            "body": "Carries selected context into the backend prompt builder.",
                            "comments": [
                                {
                                    "id": "comment-1",
                                    "author": {"login": "reviewer", "is_bot": False},
                                    "body": "Please inspect DTO serialization.",
                                    "createdAt": "2026-04-28T15:21:00Z",
                                    "url": "https://example.invalid/comment-1",
                                },
                                {
                                    "id": "comment-2",
                                    "author": {"login": "personagent", "is_bot": False},
                                    "body": "PersonAgent AI analysis: prompt-surface tests need review.",
                                    "createdAt": "2026-04-28T15:22:00Z",
                                },
                            ],
                            "deletions": 12,
                            "files": [{"path": "src/chat.py", "additions": 90, "deletions": 8}],
                            "headRefName": "feature/context",
                            "isDraft": False,
                            "labels": [{"name": "backend"}],
                            "latestReviews": [
                                {
                                    "id": "review-1",
                                    "author": {"login": "reviewer", "is_bot": False},
                                    "body": "",
                                    "state": "CHANGES_REQUESTED",
                                    "submittedAt": "2026-04-28T15:23:00Z",
                                }
                            ],
                            "mergeStateStatus": "CLEAN",
                            "mergeable": "MERGEABLE",
                            "number": 84,
                            "reviewDecision": "REVIEW_REQUIRED",
                            "state": "OPEN",
                            "statusCheckRollup": [{"conclusion": "SUCCESS", "status": "COMPLETED"}],
                            "title": "Add context attachments",
                            "updatedAt": "2026-04-28T15:20:00Z",
                            "url": "https://example.invalid/pr/84",
                        }
                    ]
                ),
                "",
            )
        return original_run_command(cwd, args, timeout)

    monkeypatch.setattr(workspace, "_run_command", fake_run_command)

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.get(
            "/workspace/git-pull-requests",
            params={"workspace_root": str(repo)},
        )

    assert response.status_code == 200
    payload = response.json()
    pull_request = payload["pullRequests"][0]
    assert payload["viewerLogin"] == "levy"
    assert pull_request["isMine"] is True
    assert pull_request["status"] == "needs_review"
    assert pull_request["statusLabel"] == "Needs review"
    assert pull_request["files"][0]["path"] == "src/chat.py"
    assert pull_request["comments"][0]["kind"] == "human_review"
    assert pull_request["comments"][1]["kind"] == "ai_review"
    assert pull_request["comments"][2]["kind"] == "status"
    assert pull_request["comments"][2]["status"] == "refused"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
@pytest.mark.asyncio
async def test_git_pull_request_comment_uses_standardized_body(monkeypatch, tmp_path):
    repo = tmp_path / "Repo"
    _init_committed_repo(repo)
    original_run_command = workspace._run_command
    gh_calls = []

    def fake_run_command(cwd, args, timeout=10):
        if args[:3] == ["gh", "pr", "comment"]:
            gh_calls.append(args)
            return subprocess.CompletedProcess(args, 0, "https://example.invalid/comment\n", "")
        return original_run_command(cwd, args, timeout)

    monkeypatch.setattr(workspace, "_run_command", fake_run_command)

    async with _workspace_client(monkeypatch, tmp_path) as client:
        response = await client.post(
            "/workspace/git-pull-requests/84/comments",
            json={
                "workspace_root": str(repo),
                "body": "The DTO boundary needs one more regression test.",
                "kind": "ai_review",
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert gh_calls == [
        [
            "gh",
            "pr",
            "comment",
            "84",
            "--body",
            "PersonAgent AI analysis\n\nThe DTO boundary needs one more regression test.",
        ]
    ]
