"""Minimal evidence gate for codebase-analysis chat turns.

The gate checks objective facts (how many files were read, how many tools
were used) and returns a decision plus an optional reminder. It does NOT
force the loop to continue — that decision is made by the executor using
the unified iteration budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from personagent.application.dto import ChatRequestDTO
from personagent.application.use_cases.chat.investigation.state import TurnCoverage

EVIDENCE_GATE_REMINDER = (
    "You have not yet gathered enough repository evidence to answer. "
    "Continue using available read/search tools before producing a final answer."
)


@dataclass(frozen=True, slots=True)
class EvidenceGateDecision:
    """Decision returned by :class:`EvidenceGateService`."""

    should_continue: bool
    reason: str
    reminder: str | None = None
    missing: tuple[str, ...] = ()
    checklist: dict[str, bool] = field(default_factory=dict)
    ready_for_final: bool = False


class EvidenceGateService:
    """Lightweight evidence sufficiency check for tool-using turns."""

    def should_continue(
        self,
        request: ChatRequestDTO,
        coverage: TurnCoverage,
    ) -> EvidenceGateDecision:
        """Return whether the model should gather more evidence.

        The gate checks only objective facts from ``TurnCoverage``:
        how many files were read, how many searches were performed,
        and whether any tools were used at all.
        """
        files_read = coverage.files_read or []
        searches_made = coverage.search_patterns or []
        tool_names = coverage.tool_names or []

        if not tool_names:
            return EvidenceGateDecision(
                should_continue=True,
                reason="no tools used",
                reminder="You have not yet used any tools. Read or search the codebase before answering.",
                checklist={"has_tool_calls": False},
            )

        if not files_read and not searches_made:
            return EvidenceGateDecision(
                should_continue=True,
                reason="no evidence gathered",
                reminder="You used tools but produced no file reads or searches. Read or search the codebase before answering.",
                checklist={"has_tool_calls": True, "has_file_read_evidence": False, "has_search_evidence": False},
            )

        if len(files_read) < 2:
            return EvidenceGateDecision(
                should_continue=True,
                reason="insufficient file reads",
                reminder="You have only read one file. Consider searching for callers, tests, and related modules before answering.",
                checklist={
                    "has_tool_calls": True,
                    "has_file_read_evidence": True,
                    "has_search_evidence": bool(searches_made),
                },
            )

        return EvidenceGateDecision(
            should_continue=False,
            reason="sufficient evidence",
            checklist={
                "has_tool_calls": True,
                "has_file_read_evidence": True,
                "has_search_evidence": bool(searches_made),
            },
            ready_for_final=True,
        )


__all__ = ["EVIDENCE_GATE_REMINDER", "EvidenceGateDecision", "EvidenceGateService"]
