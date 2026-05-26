"""Unit tests for the extracted conversation_panel_data module."""

from __future__ import annotations

from personagent.application.services.session import conversation_panel_data as cpd
from personagent.application.services.session import session_panel
from personagent.domain.conversation.models import Conversation, Message, Role


def _run_result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return session_panel._RunResult(returncode, stdout, stderr)


class TestChangedFiles:
    def test_aggregates_write_and_edit_tool_results(self, tmp_path):
        conversation = Conversation(title="Files")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_1",
                metadata={
                    "tool_name": "Write",
                    "data": {
                        "type": "file_write",
                        "path": str(tmp_path / "app.py"),
                        "display_path": "app.py",
                        "diff": "--- a/app.py\n+++ b/app.py\n-old\n+new",
                        "added_lines": 1,
                        "removed_lines": 1,
                    },
                },
            )
        )

        result = cpd.changed_files(conversation, tmp_path)

        assert len(result) == 1
        assert result[0]["display_path"] == "app.py"
        assert result[0]["added_lines"] == 1
        assert result[0]["removed_lines"] == 1
        assert result[0]["source"] == "Write"

    def test_skips_non_write_edit_tools(self, tmp_path):
        conversation = Conversation(title="Files")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_1",
                metadata={
                    "tool_name": "Read",
                    "data": {"type": "file_read", "path": "readme.md"},
                },
            )
        )

        result = cpd.changed_files(conversation, tmp_path)
        assert result == []

    def test_falls_back_to_diff_parsing_for_line_counts(self, tmp_path):
        conversation = Conversation(title="Files")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_1",
                metadata={
                    "tool_name": "Edit",
                    "data": {
                        "type": "file_edit",
                        "display_path": "app.py",
                        "diff": "@@ -1,2 +1,2 @@\n-old\n+new\n+another",
                    },
                },
            )
        )

        result = cpd.changed_files(conversation, tmp_path)

        assert result[0]["added_lines"] == 2
        assert result[0]["removed_lines"] == 1


class TestGitChangedFiles:
    def test_returns_empty_when_not_git_repo(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: False)
        result = cpd.git_changed_files(tmp_path)
        assert result == []

    def test_parses_unstaged_and_staged_diffs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)

        def fake_run(command, cwd, timeout=5):
            if command == ["git", "diff", "--numstat"]:
                return _run_result(0, "3\t1\tunstaged.py\n", "")
            if command == ["git", "diff", "--cached", "--numstat"]:
                return _run_result(0, "5\t2\tstaged.py\n", "")
            if command == ["git", "ls-files", "--others", "--exclude-standard"]:
                return _run_result(0, "", "")
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        result = cpd.git_changed_files(tmp_path)

        assert len(result) == 2
        statuses = {r["status"] for r in result}
        assert statuses == {"unstaged", "staged"}

    def test_includes_untracked_files(self, monkeypatch, tmp_path):
        monkeypatch.setattr(session_panel, "_is_git_repo", lambda _p: True)
        (tmp_path / "new.py").write_text("line1\nline2\n")

        def fake_run(command, cwd, timeout=5):
            if command == ["git", "diff", "--numstat"]:
                return _run_result(0, "", "")
            if command == ["git", "diff", "--cached", "--numstat"]:
                return _run_result(0, "", "")
            if command == ["git", "ls-files", "--others", "--exclude-standard"]:
                return _run_result(0, "new.py\n", "")
            return _run_result(1, "", "unexpected")

        monkeypatch.setattr(session_panel, "_run", fake_run)
        result = cpd.git_changed_files(tmp_path)

        untracked = [r for r in result if r["status"] == "untracked"]
        assert len(untracked) == 1
        assert untracked[0]["added_lines"] == 2


class TestSources:
    def test_aggregates_web_fetch_sources(self):
        conversation = Conversation(title="Sources")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_web",
                metadata={
                    "tool_name": "WebFetch",
                    "data": {
                        "type": "web_fetch",
                        "url": "https://example.com/docs",
                        "title": "Example Docs",
                        "description": "Reference page",
                    },
                },
            )
        )

        result = cpd.sources(conversation)

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/docs"
        assert result[0]["domain"] == "example.com"

    def test_deduplicates_by_url(self):
        conversation = Conversation(title="Sources")
        for _ in range(2):
            conversation.add_message(
                Message(
                    role=Role.TOOL,
                    content="{}",
                    tool_call_id="call_web",
                    metadata={
                        "tool_name": "WebFetch",
                        "data": {
                            "type": "web_fetch",
                            "url": "https://example.com/docs",
                            "title": "Example Docs",
                        },
                    },
                )
            )

        result = cpd.sources(conversation)
        assert len(result) == 1

    def test_skips_non_browser_tools(self):
        conversation = Conversation(title="Sources")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_read",
                metadata={
                    "tool_name": "Read",
                    "data": {"type": "file_read", "path": "readme.md"},
                },
            )
        )

        result = cpd.sources(conversation)
        assert result == []


class TestUsage:
    def test_aggregates_token_usage_from_assistant(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={
                    "usage": {
                        "completion_tokens": 12,
                        "completion_tokens_details": {"reasoning_tokens": 4},
                    },
                    "reasoning_content": "hidden analysis",
                },
            )
        )

        result = cpd.usage(conversation)

        assert result["agent_output_tokens"] == {"value": 8, "estimated": False}
        assert result["thinking_output_tokens"] == {"value": 4, "estimated": False}

    def test_estimates_when_exact_usage_missing(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="short",
                metadata={},
            )
        )

        result = cpd.usage(conversation)

        assert result["agent_output_tokens"]["estimated"] is True
        assert result["agent_output_tokens"]["value"] > 0

    def test_counts_tool_calls(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                tool_calls=[
                    {"id": "call_1", "function": {"name": "Write", "arguments": "{}"}},
                ],
                metadata={},
            )
        )
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_1",
                metadata={"tool_name": "Write", "data": {}},
            )
        )

        result = cpd.usage(conversation)

        # Same tool_id seen in both assistant and tool messages counts once
        assert result["tool_calls"]["value"] == 1

    def test_counts_plans_and_todos(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_plan",
                metadata={
                    "tool_name": "TodoWrite",
                    "data": {"type": "plan_mode", "plan_id": "plan-1"},
                },
            )
        )
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                tool_call_id="call_todo",
                metadata={
                    "tool_name": "TodoWrite",
                    "data": {"type": "todos", "todos": [{"content": "Task 1"}]},
                },
            )
        )

        result = cpd.usage(conversation)

        assert result["plans_created"]["value"] == 1
        # TodoWrite tool calls count as at least 1 todo each
        assert result["todos_created"]["value"] == 2

    def test_counts_skills_and_mcp(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                tool_calls=[
                    {"id": "call_1", "function": {"name": "Skill", "arguments": "{}"}},
                    {"id": "call_2", "function": {"name": "mcp__some_tool", "arguments": "{}"}},
                ],
                metadata={},
            )
        )

        result = cpd.usage(conversation)

        assert result["skills_used_count"]["value"] == 1
        assert result["mcp_calls_count"]["value"] == 1

    def test_counts_subagents_from_team_mode(self):
        conversation = Conversation(title="Usage")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={"team_mode": True, "run_id": "run-1"},
            )
        )

        result = cpd.usage(conversation)

        assert result["subagents_used"]["value"] == 1


class TestAddTokenUsage:
    def test_exact_agent_and_thinking_tokens(self):
        usage = {
            "agent_output_tokens": session_panel._metric(),
            "thinking_output_tokens": session_panel._metric(),
            "context_tokens": session_panel._metric(),
        }
        message = Message(
            role=Role.ASSISTANT,
            content="answer",
            metadata={
                "usage": {
                    "completion_tokens": 12,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                },
            },
        )

        cpd.add_token_usage(usage, message)

        assert usage["agent_output_tokens"] == {"value": 8, "estimated": False}
        assert usage["thinking_output_tokens"] == {"value": 4, "estimated": False}

    def test_context_tokens_from_metadata(self):
        usage = {
            "agent_output_tokens": session_panel._metric(),
            "thinking_output_tokens": session_panel._metric(),
            "context_tokens": session_panel._metric(),
        }
        message = Message(
            role=Role.ASSISTANT,
            content="answer",
            metadata={"context_tokens_estimated": 1500},
        )

        cpd.add_token_usage(usage, message)

        assert usage["context_tokens"]["value"] == 1500
        assert usage["context_tokens"]["estimated"] is True


class TestMemorySummary:
    def test_aggregates_memory_trace(self):
        conversation = Conversation(title="Memory")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={
                    "memory_trace": {
                        "classic": [
                            {
                                "path": "/tmp/memory/python_pref.md",
                                "name": "python_pref.md",
                                "snippet": "I prefer Python.",
                            }
                        ],
                        "operational": [
                            {
                                "type": "decision",
                                "summary": "Keep memory visible.",
                                "evidence": ["Trace evidence"],
                                "paths": ["src/app.py"],
                                "source_ids": ["mem-1"],
                            }
                        ],
                        "summary": {
                            "total_used": 2,
                            "classic_count": 1,
                            "rag_count": 1,
                            "omitted_count": 3,
                            "budget_used": 50,
                            "budget_tokens": 1200,
                            "latency_ms": 20,
                        },
                    }
                },
            )
        )

        result = cpd.memory_summary(conversation)

        assert result["total_recalls"] == 1
        assert result["classic_used"] == 1
        assert result["rag_used"] == 1
        assert result["omitted"] == 3
        assert result["avg_latency_ms"] == 20
        assert result["budget_used"] == 50
        assert result["budget_tokens"] == 1200
        sources = {item["source"] for item in result["most_used"]}
        assert sources == {"classic", "rag"}

    def test_empty_conversation_returns_zeros(self):
        conversation = Conversation(title="Empty")
        result = cpd.memory_summary(conversation)

        assert result["total_recalls"] == 0
        assert result["most_used"] == []

    def test_ignores_non_assistant_messages(self):
        conversation = Conversation(title="Memory")
        conversation.add_message(
            Message(
                role=Role.USER,
                content="question",
                metadata={
                    "memory_trace": {
                        "summary": {"total_used": 5},
                    }
                },
            )
        )

        result = cpd.memory_summary(conversation)
        assert result["total_recalls"] == 0

    def test_skips_traces_with_zero_total_used(self):
        conversation = Conversation(title="Memory")
        conversation.add_message(
            Message(
                role=Role.ASSISTANT,
                content="answer",
                metadata={
                    "memory_trace": {
                        "summary": {"total_used": 0},
                    }
                },
            )
        )

        result = cpd.memory_summary(conversation)
        assert result["total_recalls"] == 0
