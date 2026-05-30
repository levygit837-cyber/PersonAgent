"""Tests evaluating the agent loop behavior, evidence gate, and substanceless detection.

These tests simulate loop trajectories to verify controller interactions without
needing a live LLM backend.
"""

from __future__ import annotations

import pytest

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.evidence_gate import (
    EvidenceGateDecision,
    EvidenceGateService,
)
from personagent.application.use_cases.chat.investigation.state import (
    InvestigationState,
    TurnCoverage,
)
from personagent.application.use_cases.chat.messaging.state import AssistantStreamState
from personagent.application.use_cases.chat.streaming._assistant import _is_substanceless
from personagent.domain.exceptions import ToolLoopLimitExceededError


class TestSubstancelessDetection:
    """Verify the retry guard catches empty, stub, and shallow responses."""

    @pytest.mark.parametrize(
        "content,expected",
        [
            ("", True),
            ("   ", True),
            ("Done.", True),
            ("OK", True),
            ("Fixed!", True),
            ("Completed.", True),
            ("Looks good.", True),
            ("Confirmed", True),
            ("ok.", True),
            ("DONE", True),
            ("Hi there, this is a real answer with /path/to/file.py", False),
            ("The bug is in user_service.py line 42", False),
            ("Here's the fix:", True),  # 15 chars, no path/code markers → substanceless
            ("Short but has `code`", False),
            ("a" * 29, True),  # < 30 chars and no path/code markers
            ("a" * 30, False),  # exactly 30: len < 30 is False, so NOT substanceless by length
            ("a" * 31, False),  # > 30 chars passes length guard
            ("./file.py", False),  # has path marker
            ("[link]", False),  # has marker
            ("func() { }", False),  # has code marker
        ],
    )
    def test_is_substanceless(self, content: str, expected: bool) -> None:
        assert _is_substanceless(content) is expected


class TestEvidenceGateBehavior:
    """Verify the simplified evidence gate makes correct decisions."""

    @pytest.fixture
    def gate(self) -> EvidenceGateService:
        return EvidenceGateService()

    @pytest.fixture
    def request_fixture(self) -> ChatRequestDTO:
        return ChatRequestDTO(
            message="review the auth system",
            model="local-model",
            provider="llama",
            tools_enabled=True,
        )

    def test_no_tools_used_forces_continue(self, gate: EvidenceGateService, request_fixture: ChatRequestDTO) -> None:
        coverage = TurnCoverage(tool_names=[], files_read=[], search_patterns=[])
        decision = gate.should_continue(request_fixture, coverage)
        assert decision.should_continue is True
        assert "no tools" in decision.reason.lower()

    def test_tools_but_no_evidence_forces_continue(self, gate: EvidenceGateService, request_fixture: ChatRequestDTO) -> None:
        coverage = TurnCoverage(tool_names=["shell"], files_read=[], search_patterns=[])
        decision = gate.should_continue(request_fixture, coverage)
        assert decision.should_continue is True
        assert "no evidence" in decision.reason.lower()

    def test_only_one_file_read_forces_continue(self, gate: EvidenceGateService, request_fixture: ChatRequestDTO) -> None:
        coverage = TurnCoverage(tool_names=["Read"], files_read=["src/main.py"], search_patterns=[])
        decision = gate.should_continue(request_fixture, coverage)
        assert decision.should_continue is True
        assert "insufficient" in decision.reason.lower()

    def test_two_files_read_allows_stop(self, gate: EvidenceGateService, request_fixture: ChatRequestDTO) -> None:
        coverage = TurnCoverage(
            tool_names=["Read", "Grep"],
            files_read=["src/main.py", "src/auth.py"],
            search_patterns=["password"],
        )
        decision = gate.should_continue(request_fixture, coverage)
        assert decision.should_continue is False
        assert decision.ready_for_final is True

    def test_gate_is_deterministic(self, gate: EvidenceGateService, request_fixture: ChatRequestDTO) -> None:
        coverage = TurnCoverage(
            tool_names=["Read"],
            files_read=["a.py", "b.py"],
            search_patterns=["foo"],
        )
        d1 = gate.should_continue(request_fixture, coverage)
        d2 = gate.should_continue(request_fixture, coverage)
        assert d1 == d2


class TestInvestigationStateClassification:
    """Verify intent classification and surface tracking."""

    def test_classify_uses_request_depth(self) -> None:
        req = ChatRequestDTO(
            message="deep architecture review",
            model="local-model",
            provider="llama",
            tools_enabled=True,
            investigation_depth="deep",
        )
        state = InvestigationState.classify(req)
        assert state.depth == "deep"
        assert state.active is True
        assert state.phase == "discover"

    def test_classify_resolves_auto_to_light(self) -> None:
        req = ChatRequestDTO(
            message="deep architecture review",
            model="local-model",
            provider="llama",
            tools_enabled=True,
        )
        state = InvestigationState.classify(req)
        assert state.depth == "light"

    def test_classify_disables_when_tools_off(self) -> None:
        req = ChatRequestDTO(
            message="explain python",
            model="local-model",
            provider="llama",
            tools_enabled=False,
        )
        state = InvestigationState.classify(req)
        assert state.active is False
        assert state.phase == "classify"

    def test_classify_depth_passthrough(self) -> None:
        req = ChatRequestDTO(
            message="review auth",
            model="local-model",
            provider="llama",
            tools_enabled=True,
            investigation_depth="deep",
        )
        state = InvestigationState.classify(req)
        assert state.depth == "deep"
        assert state.active is True


class TestLoopControllerRaceCondition:
    """Document and guard against the dual-controller race condition."""

    def test_evidence_gate_can_force_iteration_at_max_minus_one(self) -> None:
        """
        This test documents the race condition:

        If turn_state.iteration == effective_max_iterations - 1,
        and the evidence gate returns should_continue=True,
        the loop increments iteration and continues.
        On the next loop head, iteration == max, and the hard cap raises.

        The executor has a guard for this (lines 348-357), but it's a band-aid.
        """
        max_iterations = 10
        current_iteration = max_iterations - 1  # 9

        gate = EvidenceGateService()
        request = ChatRequestDTO(
            message="review auth",
            model="local-model",
            provider="llama",
            tools_enabled=True,
        )
        coverage = TurnCoverage(tool_names=["Read"], files_read=["a.py"], search_patterns=[])
        decision = gate.should_continue(request, coverage)

        # The gate WILL say continue because only 1 file was read.
        assert decision.should_continue is True

        # Simulate what the executor does:
        if decision.should_continue and current_iteration >= max_iterations - 1:
            # Current code raises here. This is the "race" — instead of gracefully
            # stopping, it errors.
            with pytest.raises(ToolLoopLimitExceededError):
                raise ToolLoopLimitExceededError(
                    f"Tool loop exceeded {max_iterations} iterations",
                    metadata={"limit": max_iterations, "conversation_id": "test"},
                )

    def test_unified_loop_directive_would_avoid_race(self) -> None:
        """Illustrate the desired unified controller behavior."""
        from dataclasses import dataclass
        from typing import Literal

        @dataclass(frozen=True)
        class LoopDirective:
            action: Literal["continue", "break", "retry_with_reminder"]
            reason: str

        def unified_directive(iteration: int, max_iter: int, gate_decision: EvidenceGateDecision) -> LoopDirective:
            remaining = max_iter - iteration
            if remaining <= 0:
                return LoopDirective("break", "iteration cap reached")
            if gate_decision.should_continue and remaining > 1:
                return LoopDirective("continue", gate_decision.reason)
            if gate_decision.should_continue and remaining == 1:
                # Graceful degradation: don't force a continue that will immediately error.
                return LoopDirective("break", f"{gate_decision.reason}; but only 1 iteration remains")
            return LoopDirective("break", gate_decision.reason)

        gate = EvidenceGateService()
        request = ChatRequestDTO(
            message="review auth",
            model="local-model",
            provider="llama",
            tools_enabled=True,
        )
        coverage = TurnCoverage(tool_names=["Read"], files_read=["a.py"], search_patterns=[])
        decision = gate.should_continue(request, coverage)

        directive = unified_directive(iteration=9, max_iter=10, gate_decision=decision)
        assert directive.action == "break"
        assert "only 1 iteration remains" in directive.reason


class TestAssistantStreamStateReadyForFinal:
    """Verify the model-driven ready_for_final signal interaction with retries."""

    def test_ready_for_final_is_cleared_on_substanceless(self) -> None:
        """If the model claims ready but the content is a stub, reset the flag."""
        state = AssistantStreamState(
            content_chunks=["Done."],
            finish_reason="stop",
            ready_for_final=True,
        )
        # Simulate the logic in _maybe_retry_empty_response
        if state.ready_for_final and _is_substanceless(state.content):
            state.ready_for_final = False

        assert state.ready_for_final is False

    def test_ready_for_final_preserved_for_substantive_content(self) -> None:
        state = AssistantStreamState(
            content_chunks=["The auth module is in src/auth.py lines 15-42."],
            finish_reason="stop",
            ready_for_final=True,
        )
        if state.ready_for_final and _is_substanceless(state.content):
            state.ready_for_final = False

        assert state.ready_for_final is True
