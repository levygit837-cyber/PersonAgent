"""Conversation-derived data builders for the session panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personagent.application.services import session_panel
from personagent.domain.models.conversation import Conversation, Message, Role


async def changed_files_async(conversation: Conversation, workspace: Path) -> list[dict[str, Any]]:
    return changed_files(conversation, workspace)


async def sources_async(conversation: Conversation) -> list[dict[str, Any]]:
    return sources(conversation)


async def usage_async(conversation: Conversation) -> dict[str, Any]:
    return usage(conversation)


async def memory_summary_async(conversation: Conversation) -> dict[str, Any]:
    return memory_summary(conversation)


def changed_files(conversation: Conversation, workspace: Path) -> list[dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for message in conversation.messages:
        if message.role != Role.TOOL:
            continue
        metadata = message.metadata or {}
        tool_name = str(metadata.get("tool_name") or "")
        if tool_name not in {"Write", "Edit"}:
            continue
        data = session_panel._tool_data(message)
        path = str(data.get("display_path") or data.get("path") or "").strip()
        if not path:
            continue
        added, removed = session_panel._diff_stats(data)
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

    for item in git_changed_files(workspace):
        files.setdefault(item["display_path"], item)

    return sorted(files.values(), key=lambda item: item["display_path"])


def git_changed_files(workspace: Path) -> list[dict[str, Any]]:
    if not session_panel._is_git_repo(workspace):
        return []
    rows = []
    for mode, args in (
        ("unstaged", ["diff", "--numstat"]),
        ("staged", ["diff", "--cached", "--numstat"]),
    ):
        result = session_panel._run(["git", *args], workspace)
        if not result.ok:
            continue
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added = session_panel._safe_int(parts[0])
            removed = session_panel._safe_int(parts[1])
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
    result = session_panel._run(["git", "ls-files", "--others", "--exclude-standard"], workspace)
    if result.ok:
        for path in result.stdout.splitlines()[:50]:
            rows.append(
                {
                    "id": f"git:untracked:{path}",
                    "path": str((workspace / path).resolve()),
                    "display_path": path,
                    "added_lines": session_panel._file_line_count(workspace / path),
                    "removed_lines": 0,
                    "source": "git:untracked",
                    "status": "untracked",
                    "diff": "",
                    "content": "",
                }
            )
    return rows


def sources(conversation: Conversation) -> list[dict[str, Any]]:
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
            "BrowserListTabs",
            "BrowserExtractContent",
            "BrowserGetHtml",
        }:
            continue
        data = session_panel._tool_data(message)
        for source in session_panel._sources_from_tool_data(tool_name, data):
            by_url.setdefault(source["url"], source)
    return list(by_url.values())


def usage(conversation: Conversation) -> dict[str, Any]:
    metrics = {
        "context_tokens": session_panel._metric(),
        "agent_output_tokens": session_panel._metric(),
        "thinking_output_tokens": session_panel._metric(),
        "tool_calls": session_panel._metric(),
        "skills_used_count": session_panel._metric(),
        "mcp_calls_count": session_panel._metric(),
        "plans_created": session_panel._metric(),
        "todos_created": session_panel._metric(),
        "subagents_used": session_panel._metric(),
    }
    seen_tools: set[str] = set()
    seen_plans: set[str] = set()
    seen_subagents: set[str] = set()

    for message in conversation.messages:
        metadata = message.metadata or {}
        if message.role == Role.ASSISTANT:
            add_token_usage(metrics, message)
            tool_calls = message.tool_calls or []
            for call in tool_calls:
                call_id = str(call.get("id") or "")
                function = call.get("function") if isinstance(call, dict) else None
                tool_name = str(function.get("name") if isinstance(function, dict) else "")
                if call_id and call_id not in seen_tools:
                    seen_tools.add(call_id)
                    session_panel._add(metrics["tool_calls"], 1)
                if tool_name == "Skill":
                    session_panel._add(metrics["skills_used_count"], 1)
                if tool_name.startswith("mcp__"):
                    session_panel._add(metrics["mcp_calls_count"], 1)
            if metadata.get("team_mode") is True:
                agent_id = str(metadata.get("run_id") or message.timestamp.isoformat())
                seen_subagents.add(agent_id)
        elif message.role == Role.TOOL:
            tool_id = str(message.tool_call_id or "")
            tool_name = str(metadata.get("tool_name") or "")
            if tool_id and tool_id not in seen_tools:
                seen_tools.add(tool_id)
                session_panel._add(metrics["tool_calls"], 1)
            if tool_name == "Skill":
                session_panel._add(metrics["skills_used_count"], 1)
            if tool_name.startswith("mcp__") or metadata.get("is_mcp") is True:
                session_panel._add(metrics["mcp_calls_count"], 1)
            data = session_panel._tool_data(message)
            if data.get("type") == "plan_mode":
                plan_id = str(data.get("plan_id") or "")
                if plan_id and plan_id not in seen_plans:
                    seen_plans.add(plan_id)
                    session_panel._add(metrics["plans_created"], 1)
            if data.get("type") == "todos" or tool_name == "TodoWrite":
                todos = data.get("todos")
                session_panel._add(metrics["todos_created"], len(todos) if isinstance(todos, list) else 1)

    plan_state = conversation.metadata.get("plan_mode") if isinstance(conversation.metadata, dict) else None
    if isinstance(plan_state, dict) and plan_state.get("plan_id"):
        plan_id = str(plan_state["plan_id"])
        if plan_id not in seen_plans:
            session_panel._add(metrics["plans_created"], 1)

    metrics["subagents_used"]["value"] = len(seen_subagents)
    return metrics


def add_token_usage(usage: dict[str, Any], message: Message) -> None:
    metadata = message.metadata or {}
    raw_usage = metadata.get("usage")
    exact_agent = None
    exact_thinking = None
    if isinstance(raw_usage, dict):
        exact_thinking = session_panel._first_int(
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
            exact_thinking = session_panel._first_int(details, ("reasoning_tokens",))
        candidate_tokens = session_panel._first_int(
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
        session_panel._add(usage["agent_output_tokens"], session_panel._estimate_tokens(message.content), estimated=True)
    else:
        session_panel._add(usage["agent_output_tokens"], exact_agent)
    reasoning = str(metadata.get("reasoning_content") or "")
    if exact_thinking is None:
        session_panel._add(usage["thinking_output_tokens"], session_panel._estimate_tokens(reasoning), estimated=True)
    else:
        session_panel._add(usage["thinking_output_tokens"], exact_thinking)

    context_tokens = session_panel._first_int(
        metadata,
        (
            "context_tokens_after_turn_estimated",
            "context_tokens_estimated",
            "prompt_tokens_estimated",
        ),
    )
    context_tokens_source = None
    if context_tokens is None and isinstance(raw_usage, dict):
        context_tokens, context_tokens_source = session_panel._first_int_with_key(
            raw_usage,
            (
                "prompt_tokens",
                "input_tokens",
                "promptTokenCount",
            ),
        )
    if context_tokens is not None:
        usage["context_tokens"]["value"] = max(
            int(usage["context_tokens"].get("value") or 0),
            context_tokens,
        )
        usage["context_tokens"]["estimated"] = context_tokens_source not in (
            "prompt_tokens",
            "input_tokens",
            "promptTokenCount",
        )


def memory_summary(conversation: Conversation) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_recalls": 0,
        "rag_used": 0,
        "classic_used": 0,
        "omitted": 0,
        "avg_latency_ms": 0,
        "budget_used": 0,
        "budget_tokens": 0,
        "most_used": [],
    }
    latency_values: list[int] = []
    by_key: dict[str, dict[str, Any]] = {}

    for message in conversation.messages:
        if message.role != Role.ASSISTANT:
            continue
        trace = session_panel._memory_trace(message)
        if not trace:
            continue
        trace_summary = trace.get("summary") if isinstance(trace.get("summary"), dict) else {}
        total_used = session_panel._safe_int(trace_summary.get("total_used"))
        if total_used <= 0:
            continue
        summary["total_recalls"] += 1
        summary["rag_used"] += session_panel._safe_int(trace_summary.get("rag_count"))
        summary["classic_used"] += session_panel._safe_int(trace_summary.get("classic_count"))
        summary["omitted"] += session_panel._safe_int(trace_summary.get("omitted_count"))
        summary["budget_used"] += session_panel._safe_int(trace_summary.get("budget_used"))
        summary["budget_tokens"] += session_panel._safe_int(trace_summary.get("budget_tokens"))
        latency = session_panel._safe_int(trace_summary.get("latency_ms"))
        if latency > 0:
            latency_values.append(latency)

        message_id = message.timestamp.isoformat()
        for item in session_panel._memory_trace_items(trace, "classic"):
            key = str(item.get("path") or item.get("name") or item.get("snippet") or "classic")
            entry = by_key.setdefault(
                f"classic:{key}",
                {
                    "id": f"classic:{key}",
                    "source": "classic",
                    "label": session_panel._compact_memory_label(key),
                    "count": 0,
                    "paths": [],
                    "evidence": [],
                    "messages": [],
                },
            )
            session_panel._memory_entry_add(entry, item.get("path"), item.get("snippet"), message_id)

        for item in session_panel._memory_trace_items(trace, "operational"):
            source_ids = item.get("source_ids") if isinstance(item.get("source_ids"), list) else []
            paths = item.get("paths") if isinstance(item.get("paths"), list) else []
            key = str((source_ids or paths or [item.get("summary") or "rag"])[0])
            label = str((paths or [item.get("summary") or key])[0])
            entry = by_key.setdefault(
                f"rag:{key}",
                {
                    "id": f"rag:{key}",
                    "source": "rag",
                    "label": session_panel._compact_memory_label(label),
                    "count": 0,
                    "paths": [],
                    "evidence": [],
                    "messages": [],
                },
            )
            evidence = item.get("evidence")
            session_panel._memory_entry_add(
                entry,
                paths[0] if paths else None,
                evidence[0] if isinstance(evidence, list) and evidence else item.get("summary"),
                message_id,
            )

    if latency_values:
        summary["avg_latency_ms"] = int(sum(latency_values) / len(latency_values))
    summary["most_used"] = sorted(
        by_key.values(),
        key=lambda item: (-session_panel._safe_int(item.get("count")), str(item.get("label") or "")),
    )[:8]
    return summary
