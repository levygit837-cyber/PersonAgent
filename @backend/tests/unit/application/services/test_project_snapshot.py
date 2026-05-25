"""Unit tests for the extracted project_snapshot module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from personagent.application.services import project_snapshot, session_panel


def _run_result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return session_panel._RunResult(returncode, stdout, stderr)


class TestOwnerRepoFromRemote:
    def test_ssh_url(self):
        assert project_snapshot.owner_repo_from_remote("git@github.com:acme/repo.git") == "acme/repo"

    def test_https_url(self):
        assert project_snapshot.owner_repo_from_remote("https://github.com/acme/repo.git") == "acme/repo"

    def test_https_url_without_git_suffix(self):
        assert project_snapshot.owner_repo_from_remote("https://github.com/acme/repo") == "acme/repo"

    def test_non_github_url_returns_none(self):
        assert project_snapshot.owner_repo_from_remote("https://gitlab.com/acme/repo.git") is None


class TestRepoInfoFromResults:
    def test_gh_repo_view_success(self):
        repo_result = _run_result(
            0,
            json.dumps(
                {
                    "nameWithOwner": "acme/repo",
                    "url": "https://github.com/acme/repo",
                    "defaultBranchRef": {"name": "main"},
                    "pushedAt": "2026-04-27T22:12:44Z",
                }
            ),
        )
        errors: list[str] = []
        info = project_snapshot.repo_info_from_results(repo_result, _run_result(), _run_result(), errors)
        assert info == {
            "name_with_owner": "acme/repo",
            "url": "https://github.com/acme/repo",
            "default_branch": "main",
            "pushed_at": "2026-04-27T22:12:44Z",
            "source": "gh",
        }
        assert not errors

    def test_git_fallback_when_gh_fails(self):
        repo_result = _run_result(1, "", "gh not authenticated")
        remote_result = _run_result(0, "https://github.com/acme/repo.git\n", "")
        current_branch_result = _run_result(0, "main\n", "")
        errors: list[str] = []
        info = project_snapshot.repo_info_from_results(repo_result, remote_result, current_branch_result, errors)
        assert info == {
            "name_with_owner": "acme/repo",
            "url": "https://github.com/acme/repo",
            "default_branch": "main",
            "pushed_at": None,
            "source": "git",
        }
        assert len(errors) == 1
        assert "gh repo view" in errors[0]

    def test_returns_none_when_both_fail(self):
        repo_result = _run_result(1, "", "gh failed")
        remote_result = _run_result(1, "", "no remote")
        errors: list[str] = []
        info = project_snapshot.repo_info_from_results(repo_result, remote_result, _run_result(), errors)
        assert info is None


class TestPrsFromResult:
    def test_success(self):
        result = _run_result(
            0,
            json.dumps(
                [
                    {
                        "number": 42,
                        "title": "Add feature",
                        "state": "OPEN",
                        "headRefName": "feat",
                        "baseRefName": "main",
                        "url": "https://github.com/acme/repo/pull/42",
                        "createdAt": "2026-04-01T00:00:00Z",
                        "updatedAt": "2026-04-02T00:00:00Z",
                    }
                ]
            ),
        )
        errors: list[str] = []
        prs = project_snapshot.prs_from_result(result, errors)
        assert len(prs) == 1
        assert prs[0]["id"] == "42"
        assert prs[0]["type"] == "pr"
        assert "Add feature" in prs[0]["title"]
        assert not errors

    def test_failure_records_error(self):
        result = _run_result(1, "", "gh pr list failed")
        errors: list[str] = []
        prs = project_snapshot.prs_from_result(result, errors)
        assert prs == []
        assert len(errors) == 1


class TestBranchesFromResult:
    def test_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)
        result = _run_result(0, "main\x1fabc123\x1f2026-04-27T22:00:00-03:00\x1fInitial commit\n", "")
        current = _run_result(0, "main\n", "")
        errors: list[str] = []
        branches = project_snapshot.branches_from_result(result, current, tmp_path, errors)
        assert len(branches) == 1
        assert branches[0]["id"] == "main"
        assert branches[0]["active"] is True

    def test_not_a_git_repo_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: False)
        result = _run_result(0, "main\x1fabc123\x1f2026-04-27T22:00:00-03:00\x1fInitial commit\n", "")
        branches = project_snapshot.branches_from_result(result, _run_result(), tmp_path, [])
        assert branches == []

    def test_failure_records_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)
        result = _run_result(1, "", "git branch failed")
        errors: list[str] = []
        branches = project_snapshot.branches_from_result(result, _run_result(), tmp_path, errors)
        assert branches == []
        assert len(errors) == 1


class TestCommitsFromResult:
    def test_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)
        result = _run_result(
            0,
            "abc123def456\x1fabc1234\x1fDev\x1f2026-04-27T22:00:00-03:00\x1fFix bug\n",
            "",
        )
        errors: list[str] = []
        commits = project_snapshot.commits_from_result(result, tmp_path, errors)
        assert len(commits) == 1
        assert commits[0]["id"] == "abc123def456"
        assert commits[0]["title"] == "Fix bug"

    def test_not_a_git_repo_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: False)
        commits = project_snapshot.commits_from_result(_run_result(), tmp_path, [])
        assert commits == []


class TestLastPushesAsync:
    async def test_with_repo_name(self, monkeypatch, tmp_path):
        async def fake_run_async(command, cwd, timeout=5):
            if command == ["gh", "api", "repos/acme/repo/events"]:
                return _run_result(
                    0,
                    json.dumps(
                        [
                            {
                                "id": "evt-1",
                                "type": "PushEvent",
                                "created_at": "2026-04-27T22:00:00Z",
                                "actor": {"login": "dev1"},
                                "payload": {
                                    "ref": "refs/heads/main",
                                    "commits": [{"sha": "abc"}],
                                },
                            }
                        ]
                    ),
                    "",
                )
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run_async", fake_run_async)
        errors: list[str] = []
        pushes = await project_snapshot.last_pushes_async(tmp_path, {"name_with_owner": "acme/repo"}, errors)
        assert len(pushes) == 1
        assert pushes[0]["type"] == "push"
        assert "main" in pushes[0]["title"]

    async def test_without_repo_name_returns_empty(self):
        pushes = await project_snapshot.last_pushes_async(Path("/tmp"), None, [])
        assert pushes == []

    async def test_api_failure_records_error(self, monkeypatch, tmp_path):
        async def fake_run_async(command, cwd, timeout=5):
            return _run_result(1, "", "api error")

        monkeypatch.setattr(session_panel, "_run_async", fake_run_async)
        errors: list[str] = []
        pushes = await project_snapshot.last_pushes_async(tmp_path, {"name_with_owner": "acme/repo"}, errors)
        assert pushes == []
        assert len(errors) == 1


class TestCommitDetail:
    def test_gh_when_available(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(0, "https://github.com/acme/repo.git\n", "")
            if command == ["gh", "api", "repos/acme/repo/commits/abc123"]:
                return _run_result(
                    0,
                    json.dumps(
                        {
                            "sha": "abc123",
                            "html_url": "https://github.com/acme/repo/commit/abc123",
                            "commit": {"message": "feat: panel", "author": {"name": "Dev"}},
                            "stats": {"additions": 2, "deletions": 1, "total": 3},
                            "files": [
                                {
                                    "filename": "panel.tsx",
                                    "status": "modified",
                                    "additions": 2,
                                    "deletions": 1,
                                    "changes": 3,
                                    "patch": "@@ patch",
                                }
                            ],
                        }
                    ),
                    "",
                )
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.commit_detail(tmp_path, "abc123")
        assert detail["source"] == "gh"
        assert detail["title"] == "feat: panel"
        assert detail["files"][0]["filename"] == "panel.tsx"

    def test_local_fallback_when_gh_unavailable(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(1, "", "no remote")
            if command == ["git", "show", "--stat", "--patch", "--format=fuller", "abc123"]:
                return _run_result(0, "patch content", "")
            if command == ["git", "show", "-s", "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%B", "abc123"]:
                return _run_result(0, "abc123\x1fabc1234\x1fDev\x1f2026-04-27T00:00:00Z\x1fLocal commit\n", "")
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.commit_detail(tmp_path, "abc123")
        assert detail["source"] == "git"
        assert detail["title"] == "Local commit"


class TestPushDetail:
    def test_found_event(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(0, "https://github.com/acme/repo.git\n", "")
            if command == ["gh", "api", "repos/acme/repo/events"]:
                return _run_result(
                    0,
                    json.dumps(
                        [
                            {
                                "id": "evt-1",
                                "type": "PushEvent",
                                "created_at": "2026-04-27T22:00:00Z",
                                "actor": {"login": "dev1"},
                                "payload": {
                                    "ref": "refs/heads/main",
                                    "size": 1,
                                    "commits": [{"sha": "abc"}],
                                },
                            }
                        ]
                    ),
                    "",
                )
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.push_detail(tmp_path, "evt-1")
        assert detail["source"] == "gh"
        assert detail["id"] == "evt-1"
        assert "main" in detail["title"]

    def test_event_not_found(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(0, "https://github.com/acme/repo.git\n", "")
            if command == ["gh", "api", "repos/acme/repo/events"]:
                return _run_result(0, json.dumps([]), "")
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.push_detail(tmp_path, "missing")
        assert "not found" in detail["error"]

    def test_no_repo_detected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_run", lambda _c, _d, timeout=5: _run_result(1, "", "no remote"))
        detail = project_snapshot.push_detail(tmp_path, "evt-1")
        assert "GitHub repository not detected" in detail["error"]


class TestPrDetail:
    def test_success(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command[0:2] == ["gh", "pr"]:
                return _run_result(
                    0,
                    json.dumps(
                        {
                            "number": 42,
                            "title": "Add feature",
                            "url": "https://github.com/acme/repo/pull/42",
                            "files": [{"filename": "feat.py"}],
                        }
                    ),
                    "",
                )
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.pr_detail(tmp_path, "42")
        assert detail["source"] == "gh"
        assert detail["title"] == "#42 Add feature"

    def test_failure_returns_error(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            return _run_result(1, "", "pr not found")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.pr_detail(tmp_path, "99")
        assert "error" in detail
        assert "pr not found" in detail["error"]


class TestBranchDetail:
    def test_success(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            if command == ["git", "log", "-1", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%B", "main"]:
                return _run_result(0, "abc123\x1fabc1234\x1fDev\x1f2026-04-27T00:00:00Z\x1fFix bug\n", "")
            if command == ["git", "log", "-1", "--stat", "--oneline", "main"]:
                return _run_result(0, "stat output", "")
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.branch_detail(tmp_path, "main")
        assert detail["type"] == "branch"
        assert detail["title"] == "main"
        assert detail["metadata"]["latest_commit"] == "abc123"

    def test_failure(self, monkeypatch, tmp_path):
        def fake_run(command, cwd, timeout=5):
            return _run_result(1, "", "git error")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        detail = project_snapshot.branch_detail(tmp_path, "main")
        assert "error" in detail


class TestProjectSnapshotAsync:
    async def test_gh_success_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)

        async def fake_run_async(command, cwd, timeout=5):
            if command[:3] == ["gh", "repo", "view"]:
                return _run_result(
                    0,
                    json.dumps(
                        {
                            "nameWithOwner": "acme/repo",
                            "url": "https://github.com/acme/repo",
                            "defaultBranchRef": {"name": "main"},
                            "pushedAt": "2026-04-27T22:12:44Z",
                        }
                    ),
                    "",
                )
            if command[:3] == ["gh", "pr", "list"]:
                return _run_result(0, "[]", "")
            if command[:2] == ["git", "branch"] and "--format" in command[2]:
                return _run_result(0, "main\x1fabc123\x1f2026-04-27 22:12:44 -0300\x1fRefine chat UI\n", "")
            if command[:2] == ["git", "log"]:
                return _run_result(
                    0,
                    "abc123\x1fabc1234\x1fDev\x1f2026-04-27T22:12:44-03:00\x1fFix bug\n",
                    "",
                )
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(0, "https://github.com/acme/repo.git\n", "")
            if command == ["git", "branch", "--show-current"]:
                return _run_result(0, "main\n", "")
            if command[:2] == ["gh", "api"]:
                return _run_result(0, "[]", "")
            return _run_result(1, "", f"unexpected: {command}")

        monkeypatch.setattr(session_panel, "_run_async", fake_run_async)
        snapshot = await project_snapshot.project_snapshot_async(tmp_path)
        assert snapshot["repo"]["source"] == "gh"
        assert snapshot["repo"]["name_with_owner"] == "acme/repo"
        assert len(snapshot["branches"]) == 1
        assert len(snapshot["commits"]) == 1

    async def test_git_fallback_when_gh_fails(self, monkeypatch, tmp_path):
        async def fake_run_async(command, cwd, timeout=5):
            if command[:3] == ["gh", "repo", "view"]:
                return _run_result(1, "", "gh not authenticated")
            if command == ["git", "remote", "get-url", "origin"]:
                return _run_result(0, "https://github.com/acme/repo.git\n", "")
            if command == ["git", "branch", "--show-current"]:
                return _run_result(0, "main\n", "")
            if command[:3] == ["gh", "pr", "list"]:
                return _run_result(1, "", "gh failed")
            if command[:2] == ["git", "branch"] and "--format" in command[2]:
                return _run_result(1, "", "git branch failed")
            if command[:2] == ["git", "log"]:
                return _run_result(1, "", "git log failed")
            if command[:2] == ["gh", "api"]:
                return _run_result(1, "", "gh api failed")
            return _run_result(1, "", f"unexpected: {command}")

        monkeypatch.setattr(session_panel, "_run_async", fake_run_async)
        snapshot = await project_snapshot.project_snapshot_async(tmp_path)
        assert snapshot["repo"]["source"] == "git"
        assert snapshot["repo"]["name_with_owner"] == "acme/repo"
        assert any("gh repo view" in error for error in snapshot["errors"])


class TestCommandError:
    def test_with_stderr(self):
        result = MagicMock()
        result.stderr = "some error"
        result.stdout = ""
        result.returncode = 1
        assert project_snapshot.command_error("git log", result) == "git log: some error"

    def test_with_stdout_fallback(self):
        result = MagicMock()
        result.stderr = ""
        result.stdout = "output error"
        result.returncode = 1
        assert project_snapshot.command_error("git log", result) == "git log: output error"

    def test_with_exit_code_only(self):
        result = MagicMock()
        result.stderr = ""
        result.stdout = ""
        result.returncode = 127
        assert project_snapshot.command_error("git log", result) == "git log: exit 127"
