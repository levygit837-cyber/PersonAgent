"""Scoring and utility helpers extracted from :mod:`personagent.application.team_chat.blackboard`.

Extracted from ``blackboard.py`` (Slice 2 of 3 — scoring & metrics). These are pure,
stateless functions that compute coherency scores, detect real blockers, identify
mutating text, extract keyword sets, compact workspace memory snapshots, and provide
numeric/date utilities.

All behavior preserved verbatim — no changes intended.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "_clamp_float",
    "_coherency_score",
    "_compact_workspace_memory",
    "_is_real_blocker_text",
    "_keyword_set",
    "_looks_mutating_text",
    "_now_iso",
]


def _coherency_score(text: str, user_input: str, execution_contract: Any) -> float:
    from personagent.application.team_chat.blackboard_claim_graph import _string_list

    text_terms = _keyword_set(text)
    if not text_terms:
        return 0.0
    target_text = user_input
    if isinstance(execution_contract, dict):
        target_text = " ".join(
            str(value)
            for value in (
                execution_contract.get("objective"),
                execution_contract.get("summary"),
                " ".join(_string_list(execution_contract.get("success_criteria"))),
            )
            if value
        ) or user_input
    target_terms = _keyword_set(target_text)
    if not target_terms:
        return 0.5
    overlap = len(text_terms & target_terms) / max(1, min(len(text_terms), len(target_terms)))
    return _clamp_float(0.25 + overlap, 0, 1)


def _is_real_blocker_text(text: str) -> bool:
    normalized = text.lower().strip()
    if not normalized:
        return False
    false_signals = (
        "vote response was not valid json",
        "partially parsed",
        "no blocker",
        "blocker=false",
        "no blocker",
        "no blocking issue",
        "no block",
        "missing domain",
        "example question",
        "missing read result",
        "missing tool_result",
        "need to execute the read tool",
        "missing read content",
        "missing automatic signaling",
        "lack of automatic signaling",
        "missing opinion-based answer text",
        "regional data scarcity",
        "missing concrete citations",
        "explicit approval token",
        "verifiable signature",
        "missing unique identifier",
        "missing standardized parser",
        "missing quantitative metrics",
        "missing asynchronous notification mechanism",
        "missing standardized metadata",
        "does not list exhaustively",
        "possible visual tags",
    )
    return not any(signal in normalized for signal in false_signals)


def _looks_mutating_text(text: str) -> bool:
    normalized = text.lower()
    return any(
        token in normalized
        for token in (
            "write",
            "edit",
            "delete",
            "remove",
            "mutating",
            "migra",
        )
    )


def _keyword_set(text: str) -> set[str]:
    stopwords = {
        "para",
        "como",
        "com",
        "uma",
        "que",
        "the",
        "and",
        "this",
        "that",
        "agent",
        "agents",
        "team",
        "mode",
        "blackboard",
    }
    return {
        word
        for word in re.findall(r"[a-zA-Z0-9_]{4,}", str(text).lower())
        if word not in stopwords
    }


def _compact_workspace_memory(snapshot: dict[str, Any]) -> dict[str, Any]:
    from personagent.application.team_chat.blackboard_claim_graph import _string_list
    from personagent.application.team_chat.blackboard_json_parsing import _normalize_coverage_matrix

    if not isinstance(snapshot, dict) or not snapshot:
        return {}
    claim_graph = snapshot.get("claim_graph") if isinstance(snapshot.get("claim_graph"), dict) else {}
    nodes = claim_graph.get("nodes") if isinstance(claim_graph, dict) else []
    if not isinstance(nodes, list) or not nodes:
        raw_nodes = snapshot.get("claim_nodes")
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
    return {
        "workspace_id": snapshot.get("workspace_id"),
        "updated_at": snapshot.get("updated_at"),
        "run_id": snapshot.get("run_id"),
        "decisions": _string_list(snapshot.get("decisions"))[-8:],
        "evidence": _string_list(snapshot.get("evidence"))[-8:],
        "coverage_matrix": _normalize_coverage_matrix(snapshot.get("coverage_matrix"))[-8:],
        "claim_nodes": [
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "text": node.get("text"),
                "agent_id": node.get("agent_id"),
                "coherency_score": node.get("coherency_score"),
            }
            for node in nodes[-16:]
            if isinstance(node, dict)
        ]
        if isinstance(nodes, list)
        else [],
    }


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
