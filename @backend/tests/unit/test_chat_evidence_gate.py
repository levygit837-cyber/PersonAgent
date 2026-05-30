from __future__ import annotations

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.evidence_gate import EvidenceGateService
from personagent.application.use_cases.chat.investigation.state import TurnCoverage


def test_gate_continues_when_no_tools_used() -> None:
    coverage = TurnCoverage()
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.should_continue is True
    assert decision.reason == "no tools used"
    assert decision.reminder is not None


def test_gate_continues_when_no_evidence_gathered() -> None:
    coverage = TurnCoverage(tool_names=["Grep"])
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.should_continue is True
    assert decision.reason == "no evidence gathered"
    assert decision.reminder is not None


def test_gate_continues_with_only_one_file_read() -> None:
    coverage = TurnCoverage(tool_names=["Read"], files_read=["src/app/service.py"])
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.should_continue is True
    assert decision.reason == "insufficient file reads"
    assert decision.reminder is not None


def test_gate_allows_when_sufficient_evidence() -> None:
    coverage = TurnCoverage(
        tool_names=["Grep", "Read"],
        files_read=["src/app/service.py", "tests/test_service.py"],
        search_patterns=["def service"],
    )
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.should_continue is False
    assert decision.reason == "sufficient evidence"
    assert decision.ready_for_final is True


def test_gate_allows_with_two_files_and_no_search() -> None:
    coverage = TurnCoverage(
        tool_names=["Read"],
        files_read=["src/app/service.py", "src/app/helpers.py"],
    )
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.should_continue is False
    assert decision.reason == "sufficient evidence"


def test_gate_returns_checklist() -> None:
    coverage = TurnCoverage(
        tool_names=["Grep", "Read"],
        files_read=["src/app/service.py", "tests/test_service.py"],
        search_patterns=["def service"],
    )
    decision = EvidenceGateService().should_continue(
        ChatRequestDTO(message="Analyze this codebase bug"),
        coverage,
    )

    assert decision.checklist["has_tool_calls"] is True
    assert decision.checklist["has_file_read_evidence"] is True
    assert decision.checklist["has_search_evidence"] is True
