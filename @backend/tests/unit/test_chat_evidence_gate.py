from __future__ import annotations

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.evidence_gate import EvidenceGateService
from personagent.domain.conversation.models import Conversation, Message, Role

_CODE_METADATA = {
    "prompt_profile": {"primary_mode": "research", "secondary_modes": []},
    "agent_states": ["context_discovery", "runtime_validation"],
}


def test_gate_continues_codebase_analysis_without_repository_evidence() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Analyze this codebase bug"))
    conversation.add_message(Message(role=Role.ASSISTANT, content="The issue is obvious."))

    decision = EvidenceGateService().should_continue_investigation(
        ChatRequestDTO(message="Analyze this codebase bug"),
        conversation,
        {"evidence_gate_continuations": 0},
        _CODE_METADATA,
    )

    assert decision.should_continue is True
    assert "has_tool_calls" in decision.missing
    assert decision.reminder is not None


def test_gate_allows_when_core_search_test_and_manifest_evidence_present() -> None:
    conversation = Conversation()
    conversation.add_message(
        Message(role=Role.USER, content="Fix the failing dependency test in this repo")
    )
    conversation.add_message(
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[{"id": "1", "function": {"name": "Grep"}}],
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            metadata={
                "tool_name": "Grep",
                "data": {
                    "type": "search_results",
                    "matches": [
                        "src/app/service.py",
                        "tests/test_service.py",
                        "pyproject.toml",
                    ],
                },
            },
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            metadata={
                "tool_name": "Read",
                "data": {"type": "file_read", "display_path": "src/app/service.py"},
            },
        )
    )

    decision = EvidenceGateService().should_continue_investigation(
        ChatRequestDTO(message="Fix the failing dependency test in this repo"),
        conversation,
        {"evidence_gate_continuations": 0},
        _CODE_METADATA,
    )

    assert decision.should_continue is False
    assert decision.reason == "evidence checklist satisfied"


def test_gate_stops_at_retry_cap() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Analyze this codebase bug"))

    decision = EvidenceGateService(max_continuations=2).should_continue_investigation(
        ChatRequestDTO(message="Analyze this codebase bug"),
        conversation,
        {"evidence_gate_continuations": 2},
        _CODE_METADATA,
    )

    assert decision.should_continue is False
    assert decision.reason == "evidence gate retry cap reached"


def test_light_depth_has_no_minimum_evidence() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Analyze this codebase bug"))
    conversation.add_message(Message(role=Role.ASSISTANT, content="The issue is obvious."))

    decision = EvidenceGateService().should_continue_investigation(
        ChatRequestDTO(message="Analyze this codebase bug", investigation_depth="light"),
        conversation,
        {"evidence_gate_continuations": 0},
        _CODE_METADATA,
    )

    assert decision.should_continue is False
    assert decision.reason == "investigation depth has no minimum evidence expectations"


def test_deep_depth_requires_callers_tests_config_and_adjacent_modules() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Analyze this codebase bug"))
    conversation.add_message(
        Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "1", "function": {"name": "Grep"}}])
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            metadata={
                "tool_name": "Grep",
                "data": {
                    "type": "search_results",
                    "matches": ["src/app/service.py", "src/app/helpers.py"],
                },
            },
        )
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            metadata={
                "tool_name": "Read",
                "data": {"type": "file_read", "display_path": "src/app/service.py"},
            },
        )
    )

    decision = EvidenceGateService(max_continuations=5).should_continue_investigation(
        ChatRequestDTO(message="Analyze this codebase bug", investigation_depth="deep"),
        conversation,
        {"evidence_gate_continuations": 0},
        _CODE_METADATA,
    )

    assert decision.should_continue is True
    assert "has_test_evidence" in decision.missing
    assert "has_manifest_evidence" in decision.missing
    assert "has_adjacent_module_evidence" not in decision.missing


def test_exhaustive_depth_accepts_broad_cross_surface_evidence() -> None:
    conversation = Conversation()
    conversation.add_message(Message(role=Role.USER, content="Analyze this codebase bug"))
    conversation.add_message(
        Message(role=Role.ASSISTANT, content="", tool_calls=[{"id": "1", "function": {"name": "Shell"}}])
    )
    conversation.add_message(
        Message(
            role=Role.TOOL,
            content="{}",
            metadata={
                "tool_name": "Shell",
                "data": {
                    "type": "shell_command",
                    "command": "rg -n 'Service|service' src tests pyproject.toml",
                },
            },
        )
    )
    for path in ("src/app/service.py", "src/app/helpers.py", "tests/test_service.py", "pyproject.toml"):
        conversation.add_message(
            Message(
                role=Role.TOOL,
                content="{}",
                metadata={
                    "tool_name": "Read",
                    "data": {"type": "file_read", "display_path": path},
                },
            )
        )

    decision = EvidenceGateService(max_continuations=5).should_continue_investigation(
        ChatRequestDTO(message="Analyze this codebase bug", investigation_depth="exhaustive"),
        conversation,
        {"evidence_gate_continuations": 0},
        _CODE_METADATA,
    )

    assert decision.should_continue is False
    assert decision.reason == "evidence checklist satisfied"
