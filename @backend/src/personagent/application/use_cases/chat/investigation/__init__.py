"""Investigation-specific state carriers and coverage tracking.

This package holds InvestigationState, TurnCoverage, and their helpers,
extracted from messaging/state.py to keep the messaging layer thin.
"""

from __future__ import annotations

from personagent.application.use_cases.chat.investigation.state import (
    InvestigationState,
    TurnCoverage,
)

__all__ = [
    "InvestigationState",
    "TurnCoverage",
]