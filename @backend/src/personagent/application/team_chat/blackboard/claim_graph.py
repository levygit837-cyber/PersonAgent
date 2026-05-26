"""Claim graph analysis extracted from :mod:`personagent.application.team_chat.blackboard`.

Extracted from ``blackboard.py`` (Slice 3 of 3 — claim graph). Contains the
``ClaimGraphAnalyzer`` class that handles claim extraction, normalization,
deduplication, novelty scoring, and coverage tracking, plus three supporting
module-level functions.

All behavior preserved verbatim — no changes intended.
"""

from __future__ import annotations

from typing import Any

from personagent.application.team_chat.blackboard.json_parsing import (
    _clamp_float,
    _digest,
    _parse_json_object,
    _string_list,
)
from personagent.application.team_chat.blackboard.scoring import (
    _coherency_score,
    _keyword_set,
    _looks_mutating_text,
)

__all__ = [
    "ClaimGraphAnalyzer",
    "_claim_signature",
    "_novelty_score",
]

CLAIM_TYPES = ("claim", "evidence", "assumption", "risk", "blocker", "proposal", "tool_result", "decision")


class ClaimGraphAnalyzer:
    """Extracts, normalizes, deduplicates, and scores claim nodes from agent turns."""

    def __init__(
        self,
        *,
        claim_nodes: list[dict[str, Any]],
        claim_signatures: set[str],
        duplicates: list[dict[str, Any]],
        coverage_matrix: list[dict[str, Any]],
        agent_novelty_scores: dict[str, list[float]],
    ) -> None:
        self._claim_nodes = claim_nodes
        self._claim_signatures = claim_signatures
        self._duplicates = duplicates
        self._coverage_matrix = coverage_matrix
        self._agent_novelty_scores = agent_novelty_scores

    def set_coverage_matrix(self, coverage_matrix: list[dict[str, Any]]) -> None:
        """Update the coverage matrix reference after it is replaced externally."""
        self._coverage_matrix = coverage_matrix

    # -- public entry point ---------------------------------------------------

    def claim_nodes_from_turn(
        self,
        entry: Any,  # _BlackboardEntry
        turn: Any,  # _TurnResult
        *,
        user_input: str,
        execution_contract: dict[str, Any],
    ) -> list[dict[str, Any]]:
        structured = _parse_json_object(turn.content) if turn.content.strip().startswith(("{", "```")) else {}
        nodes: list[dict[str, Any]] = []
        for claim_type in CLAIM_TYPES:
            raw_items = structured.get(f"{claim_type}s") or structured.get(claim_type)
            nodes.extend(
                self._normalize_claim_items(
                    raw_items,
                    claim_type=claim_type,
                    entry=entry,
                    turn=turn,
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        for result in turn.tool_results:
            result_text = str(result.get("summary") or result.get("content") or result.get("tool_name") or "")
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="tool_result",
                    text=result_text,
                    confidence=0.8 if not result.get("is_error") else 0.2,
                    extra={
                        "tool_call_id": result.get("tool_call_id"),
                        "tool_name": result.get("tool_name"),
                        "coverage": [str(item.get("id")) for item in self._coverage_matrix if item.get("id")],
                    },
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        for proposal in turn.tool_proposals:
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="proposal",
                    text=str(proposal.get("summary") or proposal.get("tool_name") or "Mutating tool proposal"),
                    confidence=0.6,
                    extra={"mutating": True, "tool_call": proposal},
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        mutating_proposal_text = (
            "A mutating action was requested by the user and remains a proposal only; "
            "it must not execute until the Coordinator or consensus explicitly approves it."
        )
        mutating_proposal_signature = _claim_signature(mutating_proposal_text)
        if (
            _looks_mutating_text(user_input)
            and not any(node.get("type") == "proposal" and node.get("mutating") for node in nodes)
            and (
                not mutating_proposal_signature
                or mutating_proposal_signature not in self._claim_signatures
            )
        ):
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type="proposal",
                    text=mutating_proposal_text,
                    confidence=0.65,
                    extra={
                        "mutating": True,
                        "coverage": self._infer_coverage_for_claim(user_input, turn.agent.id),
                    },
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        if not nodes and not (turn.blocker or turn.digest):
            return []
        if not nodes:
            fallback_type = "blocker" if turn.blocker else "claim"
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type=fallback_type,
                    text=turn.blocker or turn.digest,
                    confidence=0.3 if turn.blocker else 0.55,
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        accepted: list[dict[str, Any]] = []
        for index, node in enumerate(nodes, start=1):
            text = str(node.get("text") or "").strip()
            signature = _claim_signature(text)
            novelty_score = _novelty_score(text, self._claim_nodes)
            status = "active"
            if signature and signature in self._claim_signatures:
                status = "duplicate"
                duplicate_reason = "exact_signature"
            elif novelty_score < 0.35:
                status = "duplicate"
                duplicate_reason = "semantic_overlap"
            else:
                duplicate_reason = ""
            if status == "duplicate":
                duplicate = {
                    "id": f"n{entry.sequence}.{index}",
                    "agent_id": turn.agent.id,
                    "text": text[:500],
                    "sequence": entry.sequence,
                    "reason": duplicate_reason,
                    "novelty_score": round(novelty_score, 3),
                }
                self._duplicates.append(duplicate)
            elif signature:
                self._claim_signatures.add(signature)
            node.update(
                {
                    "id": f"n{entry.sequence}.{index}",
                    "status": status,
                    "novelty_score": round(novelty_score, 3),
                    "duplicate_reason": duplicate_reason or None,
                }
            )
            self._agent_novelty_scores.setdefault(turn.agent.id, []).append(novelty_score)
            self._claim_nodes.append(node)
            accepted.append(node)
        return accepted

    # -- private methods ------------------------------------------------------

    def _normalize_claim_items(
        self,
        raw_items: Any,
        *,
        claim_type: str,
        entry: Any,
        turn: Any,
        user_input: str = "",
        execution_contract: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if raw_items is None:
            return []
        if isinstance(raw_items, (str, int, float, bool)):
            raw_items = [raw_items]
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            return []
        nodes: list[dict[str, Any]] = []
        for raw in raw_items:
            if isinstance(raw, dict):
                text = str(raw.get("text") or raw.get("summary") or raw.get("claim") or raw.get("content") or "").strip()
                confidence = _clamp_float(raw.get("confidence", turn.coherency_score), 0, 1)
                extra = {
                    "depends_on": _string_list(raw.get("depends_on")),
                    "supports": _string_list(
                        raw.get("supports")
                        or raw.get("support")
                        or raw.get("supported_by")
                        or raw.get("evidence")
                        or raw.get("evidence_ids")
                    ),
                    "contradicts": _string_list(
                        raw.get("contradicts")
                        or raw.get("conflicts")
                        or raw.get("conflicts_with")
                        or raw.get("opposes")
                    ),
                    "coverage": _string_list(
                        raw.get("coverage")
                        or raw.get("covers")
                        or raw.get("coverage_ids")
                        or raw.get("coverage_id")
                        or raw.get("coverage_matrix_ids")
                        or raw.get("cm")
                    ),
                }
            else:
                text = str(raw).strip()
                confidence = turn.coherency_score
                extra = {}
            if not text:
                continue
            if not extra.get("coverage"):
                extra["coverage"] = self._infer_coverage_for_claim(text, turn.agent.id)
                if extra["coverage"]:
                    extra["coverage_inferred"] = True
            if claim_type == "proposal" and _looks_mutating_text(text):
                extra["mutating"] = True
            nodes.append(
                self._claim_node(
                    entry=entry,
                    turn=turn,
                    claim_type=claim_type,
                    text=text,
                    confidence=confidence,
                    extra=extra,
                    user_input=user_input,
                    execution_contract=execution_contract,
                )
            )
        return nodes

    def _claim_node(
        self,
        *,
        entry: Any,
        turn: Any,
        claim_type: str,
        text: str,
        confidence: float,
        extra: dict[str, Any] | None = None,
        user_input: str = "",
        execution_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = extra or {}
        coherency = _coherency_score(text, user_input, execution_contract or {})
        if turn.coherency_score > 0:
            coherency = max(coherency, turn.coherency_score * 0.6)
        if extra.get("coverage"):
            coherency = max(coherency, 0.68)
        if claim_type in {"evidence", "decision", "tool_result"}:
            coherency = max(coherency, 0.7)
        return {
            "type": claim_type if claim_type in CLAIM_TYPES else "claim",
            "text": _digest(text, 700),
            "agent_id": turn.agent.id,
            "agent_name": turn.agent.name,
            "round": entry.round_index,
            "phase": entry.phase,
            "confidence": round(_clamp_float(confidence, 0, 1), 3),
            "coherency_score": round(_clamp_float(coherency, 0, 1), 3),
            "depends_on": extra.get("depends_on", []),
            "supports": extra.get("supports", []),
            "contradicts": extra.get("contradicts", []),
            "coverage": extra.get("coverage", []),
            **{key: value for key, value in extra.items() if key not in {"depends_on", "supports", "contradicts", "coverage"}},
        }

    def _infer_coverage_for_claim(self, text: str, agent_id: str) -> list[str]:
        if not self._coverage_matrix:
            return []
        claim_terms = _keyword_set(text)
        matches: list[tuple[int, str]] = []
        for item in self._coverage_matrix:
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            item_text = f"{item_id} {item.get('question', '')} {item.get('expected_output', '')}"
            item_terms = _keyword_set(item_text)
            score = len(claim_terms & item_terms)
            if str(item.get("owner_agent_id") or "").strip() == agent_id:
                score += 2
            if score > 0:
                matches.append((score, item_id))
        matches.sort(reverse=True)
        return [item_id for _, item_id in matches[:2]]

    def update_coverage(self, nodes: list[dict[str, Any]]) -> None:
        if not self._coverage_matrix:
            return
        for item in self._coverage_matrix:
            item_text = f"{item.get('id', '')} {item.get('question', '')} {item.get('expected_output', '')}"
            item_terms = _keyword_set(item_text)
            if not item_terms:
                continue
            for node in nodes:
                if node.get("status") == "duplicate":
                    continue
                explicit = {value.lower() for value in _string_list(node.get("coverage"))}
                node_terms = _keyword_set(str(node.get("text") or ""))
                item_id = str(item.get("id") or "").lower()
                node_type = str(node.get("type") or "claim")
                generic_match = (
                    (item_id == "requirements" and node_type in {"claim", "evidence", "assumption"})
                    or (item_id == "risks" and node_type in {"risk", "blocker"})
                    or (item_id == "implementation" and node_type in {"claim", "proposal", "decision", "tool_result"})
                    or (item_id == "coherence" and node_type in {"claim", "evidence", "decision"})
                )
                matched = item_id in explicit or bool(item_terms & node_terms) or generic_match
                if not matched:
                    continue
                item["status"] = "covered"
                item.setdefault("agents", [])
                if node.get("agent_id") not in item["agents"]:
                    item["agents"].append(node.get("agent_id"))
                item.setdefault("evidence_node_ids", [])
                if node.get("id") not in item["evidence_node_ids"]:
                    item["evidence_node_ids"].append(node.get("id"))


# -- Module-level claim graph helpers ------------------------------------------


def _claim_signature(text: str) -> str:
    terms = sorted(_keyword_set(text))
    return " ".join(terms[:18])


def _novelty_score(text: str, existing_nodes: list[dict[str, Any]]) -> float:
    terms = _keyword_set(text)
    if not terms:
        return 0.0
    max_overlap = 0.0
    for node in existing_nodes:
        if node.get("status") == "duplicate":
            continue
        other_terms = _keyword_set(str(node.get("text") or ""))
        if not other_terms:
            continue
        overlap = len(terms & other_terms) / max(1, len(terms | other_terms))
        max_overlap = max(max_overlap, overlap)
    return _clamp_float(1.0 - max_overlap, 0.0, 1.0)
