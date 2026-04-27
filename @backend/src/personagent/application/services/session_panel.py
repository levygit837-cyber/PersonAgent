"""Session panel aggregation for the desktop chat UI."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from personagent.domain.models.conversation import Conversation, Message, Role

_GITHUB_REMOTE_RE = re.compile(r"(?:github\.com[:/])(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$")
_TEXT_TOKEN_DIVISOR = 4
_MAX_DETAIL_PATCH_CHARS = 80_000


@dataclass(frozen=True, slots=True)
class SessionPanelService:
    """Builds the panel snapshot from conversation metadata, Git and GitHub."""

    workspace_root: str | Path | None = None

    def panel_snapshot(self, conversation: Conversation) -> dict[str, Any]:
        workspace = self._workspace()
        project = self._project_snapshot(workspace)
        return {
            "conversation_id": str(conversation.id),
            "title": conversation.title,
            "updated_at": conversation.updated_at.isoformat(),
            "changed_files": self._changed_files(conversation, workspace),
            "sources": self._sources(conversation),
            "usage": self._usage(conversation),
            "project": project,
        }

    def project_detail(self, detail_type: str, detail_id: str) -> dict[str, Any]:
        workspace = self._workspace()
        normalized = detail_type.strip().lower()
        if normalized == "commit":
            return self._commit_detail(workspace, detail_id)
        if normalized == "push":
            return self._push_detail(workspace, detail_id)
        if normalized == "pr":
            return self._pr_detail(workspace, detail_id)
        if normalized == "branch":
            return self._branch_detail(workspace, detail_id)
        return {
            "type": normalized,
            "id": detail_id,
            "title": "Unsupported detail",
            "error": f"Unsupported project detail type: {detail_type}",
        }

    def _workspace(self) -> Path:
        raw = self.workspace_root or Path.cwd()
        path = Path(raw).expanduser().resolve()
        return path if path.exists() else Path.cwd().resolve()

    def _usage(self, conversation: Conversation) -> dict[str, Any]:
        usage = {
            "agent_output_tokens": _metric(),
            "thinking_output_tokens": _metric(),
            "tool_calls": _metric(),
            "skills_used_count": _metric(),
            "mcp_calls_count": _metric(),
            "plans_created": _metric(),
            "todos_created": _metric(),
            "subagents_used": _metric(),
        }
        seen_tools: set[str] = set()
        seen_plans: set[str] = set()
        seen_subagents: set[str] = set()

        for message in conversation.messages:
            metadata = message.metadata or {}
            if message.role == Role.ASSISTANT:
                self._add_token_usage(usage, message)
                tool_calls = message.tool_calls or []
                for call in tool_calls:
                    call_id = str(call.get("id") or "")
                    function = call.get("function") if isinstance(call, dict) else None
                    tool_name = str(function.get("name") if isinstance(function, dict) else "")
                    if call_id and call_id not in seen_tools:
                        seen_tools.add(call_id)
                        _add(usage["tool_calls"], 1)
                    if tool_name == "Skill":
                        _add(usage["skills_used_count"], 1)
                    if tool_name.startswith("mcp__"):
                        _add(usage["mcp_calls_count"], 1)
                if metadata.get("team_mode") is True:
                    agent_id = str(metadata.get("run_id") or message.timestamp.isoformat())
                    seen_subagents.add(agent_id)
            elif message.role == Role.TOOL:
                tool_id = str(message.tool_call_id or "")
                tool_name = str(metadata.get("tool_name") or "")
                if tool_id and tool_id not in seen_tools:
                    seen_tools.add(tool_id)
                    _add(usage["tool_calls"], 1)
                if tool_name == "Skill":
                    _add(usage["skills_used_count"], 1)
                if tool_name.startswith("mcp__") or metadata.get("is_mcp") is True:
                    _add(usage["mcp_calls_count"], 1)
                data = _tool_data(message)
                if data.get("type") == "plan_mode":
                    plan_id = str(data.get("plan_id") or "")
                    if plan_id and plan_id not in seen_plans:
                        seen_plans.add(plan_id)
                        _add(usage["plans_created"], 1)
                if data.get("type") == "todos" or tool_name == "TodoWrite":
                    todos = data.get("todos")
                    _add(usage["todos_created"], len(todos) if isinstance(todos, list) else 1)

        plan_state = conversation.metadata.get("plan_mode") if isinstance(conversation.metadata, dict) else None
        if isinstance(plan_state, dict) and plan_state.get("plan_id"):
            plan_id = str(plan_state["plan_id"])
            if plan_id not in seen_plans:
                _add(usage["plans_created"], 1)

        usage["subagents_used"]["value"] = len(seen_subagents)
        return usage

    def _add_token_usage(self, usage: dict[str, Any], message: Message) -> None:
        metadata = message.metadata or {}
        raw_usage = metadata.get("usage")
        exact_agent = None
        exact_thinking = None
        if isinstance(raw_usage, dict):
            exact_thinking = _first_int(
                raw_usage,
                (
                    "reasoning_tokens",
                    "thinking_tokens",
                    "thoughtsTokenCount",
                    "thoughts_token_count",
                ),
            )
            details = raw_usage.get("completion_tokens_details")
            if exact_thinking is None and isinstance(details, dict):
                exact_thinking = _first_int(details, ("reasoning_tokens",))
            candidate_tokens = _first_int(
                raw_usage,
                (
                    "candidatesTokenCount",
                    "candidates_token_count",
                    "output_tokens",
                    "completion_tokens",
                ),
            )
            exact_agent = candidate_tokens
            if (
                exact_agent is not None
                and exact_thinking is not None
                and "completion_tokens" in raw_usage
                and "candidatesTokenCount" not in raw_usage
            ):
                exact_agent = max(0, exact_agent - exact_thinking)

        if exact_agent is None:
            _add(usage["agent_output_tokens"], _estimate_tokens(message.content), estimated=True)
        else:
            _add(usage["agent_output_tokens"], exact_agent)
        reasoning = str(metadata.get("reasoning_content") or "")
        if exact_thinking is None:
            _add(usage["thinking_output_tokens"], _estimate_tokens(reasoning), estimated=True)
        else:
            _add(usage["thinking_output_tokens"], exact_thinking)

    def _changed_files(self, conversation: Conversation, workspace: Path) -> list[dict[str, Any]]:
        files: dict[str, dict[str, Any]] = {}
        for message in conversation.messages:
            if message.role != Role.TOOL:
                continue
            metadata = message.metadata or {}
            tool_name = str(metadata.get("tool_name") or "")
            if tool_name not in {"Write", "Edit"}:
                continue
            data = _tool_data(message)
            path = str(data.get("display_path") or data.get("path") or "").strip()
            if not path:
                continue
            added, removed = _diff_stats(data)
            files[path] = {
                "id": f"tool:{message.tool_call_id or path}",
                "path": str(data.get("path") or path),
                "display_path": path,
                "added_lines": added,
                "removed_lines": removed,
                "source": tool_name,
                "status": "changed",
                "diff": str(data.get("diff") or ""),
                "content": str(data.get("written_content") or data.get("new_content") or ""),
            }

        for item in self._git_changed_files(workspace):
            files.setdefault(item["display_path"], item)

        return sorted(files.values(), key=lambda item: item["display_path"])

    def _git_changed_files(self, workspace: Path) -> list[dict[str, Any]]:
        if not _is_git_repo(workspace):
            return []
        rows = []
        for mode, args in (
            ("unstaged", ["diff", "--numstat"]),
            ("staged", ["diff", "--cached", "--numstat"]),
        ):
            result = _run(["git", *args], workspace)
            if not result.ok:
                continue
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                added = _safe_int(parts[0])
                removed = _safe_int(parts[1])
                path = parts[2]
                rows.append(
                    {
                        "id": f"git:{mode}:{path}",
                        "path": str((workspace / path).resolve()),
                        "display_path": path,
                        "added_lines": added,
                        "removed_lines": removed,
                        "source": f"git:{mode}",
                        "status": mode,
                        "diff": "",
                        "content": "",
                    }
                )
        result = _run(["git", "ls-files", "--others", "--exclude-standard"], workspace)
        if result.ok:
            for path in result.stdout.splitlines()[:50]:
                rows.append(
                    {
                        "id": f"git:untracked:{path}",
                        "path": str((workspace / path).resolve()),
                        "display_path": path,
                        "added_lines": _file_line_count(workspace / path),
                        "removed_lines": 0,
                        "source": "git:untracked",
                        "status": "untracked",
                        "diff": "",
                        "content": "",
                    }
                )
        return rows

    def _sources(self, conversation: Conversation) -> list[dict[str, Any]]:
        by_url: dict[str, dict[str, Any]] = {}
        for message in conversation.messages:
            if message.role != Role.TOOL:
                continue
            metadata = message.metadata or {}
            tool_name = str(metadata.get("tool_name") or "")
            if tool_name not in {
                "WebFetch",
                "BrowserSearch",
                "BrowserOpen",
                "BrowserExtractContent",
                "BrowserGetHtml",
            }:
                continue
            data = _tool_data(message)
            for source in _sources_from_tool_data(tool_name, data):
                by_url.setdefault(source["url"], source)
        return list(by_url.values())

    def _project_snapshot(self, workspace: Path) -> dict[str, Any]:
        errors: list[str] = []
        repo = self._repo_info(workspace, errors)
        return {
            "repo": repo,
            "prs": self._last_prs(workspace, errors),
            "branches": self._branches(workspace, errors),
            "pushes": self._last_pushes(workspace, repo, errors),
            "commits": self._last_commits(workspace, errors),
            "errors": errors,
        }

    def _repo_info(self, workspace: Path, errors: list[str]) -> dict[str, Any] | None:
        result = _run(
            ["gh", "repo", "view", "--json", "nameWithOwner,url,defaultBranchRef,pushedAt"],
            workspace,
        )
        if result.ok:
            data = _json_object(result.stdout)
            default_branch = data.get("defaultBranchRef")
            return {
                "name_with_owner": data.get("nameWithOwner"),
                "url": data.get("url"),
                "default_branch": default_branch.get("name") if isinstance(default_branch, dict) else None,
                "pushed_at": data.get("pushedAt"),
                "source": "gh",
            }
        errors.append(_command_error("gh repo view", result))
        remote = _run(["git", "remote", "get-url", "origin"], workspace)
        if not remote.ok:
            return None
        name_with_owner = _owner_repo_from_remote(remote.stdout.strip())
        return {
            "name_with_owner": name_with_owner,
            "url": f"https://github.com/{name_with_owner}" if name_with_owner else remote.stdout.strip(),
            "default_branch": _git_default_branch(workspace),
            "pushed_at": None,
            "source": "git",
        }

    def _last_prs(self, workspace: Path, errors: list[str]) -> list[dict[str, Any]]:
        result = _run(
            [
                "gh",
                "pr",
                "list",
                "--limit",
                "5",
                "--state",
                "all",
                "--json",
                "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName",
            ],
            workspace,
        )
        if not result.ok:
            errors.append(_command_error("gh pr list", result))
            return []
        values = _json_list(result.stdout)
        return [
            {
                "id": str(item.get("number")),
                "type": "pr",
                "title": f"#{item.get('number')} {item.get('title')}",
                "subtitle": f"{item.get('state')} · {item.get('headRefName')} → {item.get('baseRefName')}",
                "url": item.get("url"),
                "timestamp": item.get("updatedAt") or item.get("createdAt"),
                "metadata": item,
            }
            for item in values
        ]

    def _branches(self, workspace: Path, errors: list[str]) -> list[dict[str, Any]]:
        if not _is_git_repo(workspace):
            return []
        current = _run(["git", "branch", "--show-current"], workspace).stdout.strip()
        result = _run(
            [
                "git",
                "branch",
                "--format=%(refname:short)%x1f%(objectname:short)%x1f%(committerdate:iso8601)%x1f%(subject)",
            ],
            workspace,
        )
        if not result.ok:
            errors.append(_command_error("git branch", result))
            return []
        branches = []
        for line in result.stdout.splitlines()[:20]:
            name, sha, date, subject = _split_record(line, 4)
            branches.append(
                {
                    "id": name,
                    "type": "branch",
                    "title": name,
                    "subtitle": f"{sha} · {subject}",
                    "timestamp": date,
                    "active": name == current,
                    "metadata": {"sha": sha, "subject": subject},
                }
            )
        return branches

    def _last_pushes(
        self,
        workspace: Path,
        repo: dict[str, Any] | None,
        errors: list[str],
    ) -> list[dict[str, Any]]:
        name_with_owner = (repo or {}).get("name_with_owner")
        if not name_with_owner:
            return []
        result = _run(["gh", "api", f"repos/{name_with_owner}/events"], workspace)
        if not result.ok:
            errors.append(_command_error("gh api events", result))
            return []
        events = [item for item in _json_list(result.stdout) if item.get("type") == "PushEvent"]
        pushes = []
        for item in events[:5]:
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
            actor = item.get("actor") if isinstance(item.get("actor"), dict) else {}
            ref = str(payload.get("ref") or "")
            branch = ref.removeprefix("refs/heads/")
            pushes.append(
                {
                    "id": str(item.get("id")),
                    "type": "push",
                    "title": f"Push to {branch or ref or 'repository'}",
                    "subtitle": f"{len(commits)} commits · {actor.get('login', 'unknown')}",
                    "timestamp": item.get("created_at"),
                    "url": None,
                    "metadata": {
                        "ref": ref,
                        "branch": branch,
                        "commits": commits,
                        "actor": actor,
                    },
                }
            )
        return pushes

    def _last_commits(self, workspace: Path, errors: list[str]) -> list[dict[str, Any]]:
        if not _is_git_repo(workspace):
            return []
        result = _run(["git", "log", "-10", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%s"], workspace)
        if not result.ok:
            errors.append(_command_error("git log", result))
            return []
        commits = []
        for line in result.stdout.splitlines():
            sha, short, author, date, subject = _split_record(line, 5)
            commits.append(
                {
                    "id": sha,
                    "type": "commit",
                    "title": subject,
                    "subtitle": f"{short} · {author}",
                    "timestamp": date,
                    "metadata": {"sha": sha, "short_sha": short, "author": author},
                }
            )
        return commits

    def _commit_detail(self, workspace: Path, sha: str) -> dict[str, Any]:
        repo_name = _owner_repo_from_workspace(workspace)
        if repo_name:
            remote = _run(["gh", "api", f"repos/{repo_name}/commits/{sha}"], workspace)
            if remote.ok:
                data = _json_object(remote.stdout)
                files = data.get("files") if isinstance(data.get("files"), list) else []
                commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
                message = str(commit.get("message") or "")
                return {
                    "type": "commit",
                    "id": sha,
                    "title": message.splitlines()[0] if message.splitlines() else sha,
                    "url": data.get("html_url"),
                    "metadata": {
                        "sha": data.get("sha"),
                        "author": commit.get("author"),
                        "stats": data.get("stats"),
                        "message": message,
                    },
                    "files": [
                        {
                            "filename": item.get("filename"),
                            "status": item.get("status"),
                            "additions": item.get("additions"),
                            "deletions": item.get("deletions"),
                            "changes": item.get("changes"),
                            "patch": _truncate(str(item.get("patch") or ""), _MAX_DETAIL_PATCH_CHARS // max(1, len(files))),
                        }
                        for item in files
                    ],
                    "source": "gh",
                }
        return self._local_commit_detail(workspace, sha)

    def _local_commit_detail(self, workspace: Path, sha: str) -> dict[str, Any]:
        show = _run(["git", "show", "--stat", "--patch", "--format=fuller", sha], workspace, timeout=8)
        meta = _run(["git", "show", "-s", "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%B", sha], workspace)
        full, short, author, date, message = _split_record(meta.stdout, 5) if meta.ok else (sha, sha[:7], "", "", "")
        return {
            "type": "commit",
            "id": sha,
            "title": message.splitlines()[0] if message else short,
            "metadata": {"sha": full, "short_sha": short, "author": author, "date": date, "message": message},
            "patch": _truncate(show.stdout if show.ok else show.stderr, _MAX_DETAIL_PATCH_CHARS),
            "source": "git",
            "error": None if show.ok else show.stderr,
        }

    def _push_detail(self, workspace: Path, event_id: str) -> dict[str, Any]:
        repo_name = _owner_repo_from_workspace(workspace)
        if not repo_name:
            return {"type": "push", "id": event_id, "title": "Push", "error": "GitHub repository not detected."}
        events = _run(["gh", "api", f"repos/{repo_name}/events"], workspace)
        if not events.ok:
            return {"type": "push", "id": event_id, "title": "Push", "error": events.stderr or events.stdout}
        event = next((item for item in _json_list(events.stdout) if str(item.get("id")) == event_id), None)
        if not event:
            return {"type": "push", "id": event_id, "title": "Push", "error": "Push event not found in recent GitHub events."}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
        return {
            "type": "push",
            "id": event_id,
            "title": f"Push to {str(payload.get('ref') or '').removeprefix('refs/heads/')}",
            "metadata": {
                "created_at": event.get("created_at"),
                "actor": event.get("actor"),
                "ref": payload.get("ref"),
                "size": payload.get("size"),
            },
            "commits": commits,
            "source": "gh",
        }

    def _pr_detail(self, workspace: Path, pr_number: str) -> dict[str, Any]:
        result = _run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--json",
                "number,title,state,author,createdAt,updatedAt,mergedAt,url,headRefName,baseRefName,body,commits,files,additions,deletions,changedFiles",
            ],
            workspace,
        )
        if not result.ok:
            return {"type": "pr", "id": pr_number, "title": f"PR #{pr_number}", "error": result.stderr or result.stdout}
        data = _json_object(result.stdout)
        return {
            "type": "pr",
            "id": str(data.get("number") or pr_number),
            "title": f"#{data.get('number')} {data.get('title')}",
            "url": data.get("url"),
            "metadata": data,
            "files": data.get("files") if isinstance(data.get("files"), list) else [],
            "source": "gh",
        }

    def _branch_detail(self, workspace: Path, branch: str) -> dict[str, Any]:
        log = _run(["git", "log", "-1", "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%B", branch], workspace)
        stat = _run(["git", "log", "-1", "--stat", "--oneline", branch], workspace)
        full, short, author, date, message = _split_record(log.stdout, 5) if log.ok else ("", "", "", "", "")
        return {
            "type": "branch",
            "id": branch,
            "title": branch,
            "metadata": {
                "latest_commit": full,
                "short_sha": short,
                "author": author,
                "date": date,
                "message": message,
            },
            "patch": stat.stdout if stat.ok else stat.stderr,
            "source": "git",
            "error": None if log.ok else log.stderr,
        }


@dataclass(frozen=True, slots=True)
class _RunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _run(command: list[str], cwd: Path, timeout: int = 5) -> _RunResult:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _RunResult(result.returncode, result.stdout, result.stderr)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return _RunResult(1, "", str(exc))


def _is_git_repo(workspace: Path) -> bool:
    return _run(["git", "rev-parse", "--git-dir"], workspace).ok


def _metric(value: int = 0, estimated: bool = False) -> dict[str, Any]:
    return {"value": value, "estimated": estimated}


def _add(metric: dict[str, Any], value: int, estimated: bool = False) -> None:
    metric["value"] = int(metric.get("value") or 0) + max(0, int(value or 0))
    metric["estimated"] = bool(metric.get("estimated") or estimated)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _TEXT_TOKEN_DIVISOR - 1) // _TEXT_TOKEN_DIVISOR)


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = data.get(key)
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "-":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        if value == "-":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tool_data(message: Message) -> dict[str, Any]:
    metadata = message.metadata or {}
    data = metadata.get("data")
    if isinstance(data, dict):
        return data
    if isinstance(message.content, str):
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _diff_stats(data: dict[str, Any]) -> tuple[int, int]:
    added = _safe_int(data.get("added_lines"))
    removed = _safe_int(data.get("removed_lines"))
    if added or removed:
        return added, removed
    diff = str(data.get("diff") or "")
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            added += 1
        if line.startswith("-"):
            removed += 1
    return added, removed


def _sources_from_tool_data(tool_name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if tool_name == "BrowserSearch":
        results = data.get("results")
        if isinstance(results, list):
            for index, result in enumerate(results, start=1):
                if isinstance(result, dict):
                    sources.extend(_source_from_record(tool_name, result, index))
        return sources
    sources.extend(_source_from_record(tool_name, data, 1))
    return sources


def _source_from_record(tool_name: str, data: dict[str, Any], index: int) -> list[dict[str, Any]]:
    raw_url = data.get("final_url") or data.get("url") or data.get("href")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return []
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    title = str(data.get("title") or data.get("name") or parsed.netloc)
    description = str(data.get("description") or data.get("snippet") or data.get("content") or "")
    description = " ".join(description.split())[:220]
    domain = parsed.netloc.lower()
    return [
        {
            "id": f"{tool_name}:{index}:{raw_url}",
            "title": title[:140],
            "description": description,
            "url": raw_url,
            "domain": domain,
            "favicon_url": f"https://www.google.com/s2/favicons?domain={domain}&sz=32",
            "tool_name": tool_name,
        }
    ]


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _split_record(line: str, count: int) -> tuple[str, ...]:
    parts = line.split("\x1f", count - 1)
    return (*parts, *([""] * count))[:count]


def _owner_repo_from_workspace(workspace: Path) -> str | None:
    remote = _run(["git", "remote", "get-url", "origin"], workspace)
    if not remote.ok:
        return None
    return _owner_repo_from_remote(remote.stdout.strip())


def _owner_repo_from_remote(remote: str) -> str | None:
    match = _GITHUB_REMOTE_RE.search(remote)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}"


def _git_default_branch(workspace: Path) -> str | None:
    result = _run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], workspace)
    if result.ok and "/" in result.stdout:
        return result.stdout.strip().split("/")[-1]
    result = _run(["git", "branch", "--show-current"], workspace)
    return result.stdout.strip() or None


def _command_error(label: str, result: _RunResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    return f"{label}: {detail or f'exit {result.returncode}'}"


def _file_line_count(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "\n[truncated]"
