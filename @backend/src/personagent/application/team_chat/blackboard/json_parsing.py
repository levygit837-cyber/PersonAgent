"""JSON parsing helpers extracted from :mod:`personagent.application.team_chat.blackboard`.

Extracted from ``blackboard.py`` (Slice 1 of 3). These are pure, stateless functions
that handle JSON extraction from LLM outputs, markdown fence stripping, partial claim
graph parsing, and coverage matrix normalization.

All behavior preserved verbatim — no changes intended.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from typing import Any

from personagent.application.team_chat.types import TurnResult

# Temporary cross-slice imports — will be redirected in Slice 2 (_string_list) and
# Slice 3 (_clamp_float).
from personagent.application.team_chat.blackboard import _clamp_float, _string_list

__all__ = [
    "_digest",
    "_extract_complete_json_objects_from_array",
    "_normalize_coverage_matrix",
    "_parse_json_object",
    "_parse_partial_claim_graph",
    "_strip_json_fence",
    "_turn_blackboard_payload",
]


def _turn_blackboard_payload(turn: TurnResult) -> dict[str, Any]:
    summary = turn.digest or ("Reasoning-only contribution." if turn.reasoning else "No visible output.")
    payload: dict[str, Any] = {
        "summary": summary,
        "phase": turn.phase,
        "duration_ms": turn.duration_ms,
        "first_token_ms": turn.first_token_ms,
        "tool_context": turn.tool_context,
        "coherency_score": turn.coherency_score,
        "tool_calls": turn.tool_calls,
        "tool_results": turn.tool_results,
        "tool_proposals": turn.tool_proposals,
    }
    if turn.blocker:
        payload["blocker"] = turn.blocker
    structured = _parse_json_object(turn.content) if turn.content.strip().startswith(("{", "```")) else {}
    for key in ("claims", "decisions", "evidence", "blockers", "proposals", "risks", "assumptions"):
        if key in structured:
            payload[key] = structured[key]
    return payload


def _digest(content: str, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", str(content)).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rsplit(' ', 1)[0]}..."


def _parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_json_fence(content)
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        candidates.insert(0, match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else {}
    return _parse_partial_claim_graph(text)


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text


def _parse_partial_claim_graph(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    key_aliases = {
        "claims": "claims",
        "evidence": "evidence",
        "evidences": "evidence",
        "assumptions": "assumptions",
        "risks": "risks",
        "blockers": "blockers",
        "proposals": "proposals",
        "tool_results": "tool_results",
        "decisions": "decisions",
    }
    for source_key, target_key in key_aliases.items():
        items = _extract_complete_json_objects_from_array(text, source_key)
        if items:
            payload.setdefault(target_key, []).extend(items)
    coherency_match = re.search(r'"coherency_score"\s*:\s*([0-9]*\.?[0-9]+)', text)
    if coherency_match:
        with suppress(ValueError):
            payload["coherency_score"] = _clamp_float(float(coherency_match.group(1)), 0, 1)
    return payload


def _extract_complete_json_objects_from_array(text: str, key: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*\[', flags=re.I)
    for match in pattern.finditer(text):
        depth = 0
        start: int | None = None
        in_string = False
        escape = False
        for index in range(match.end(), len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
                continue
            if char == "}":
                if depth <= 0:
                    continue
                depth -= 1
                if depth == 0 and start is not None:
                    raw_object = text[start : index + 1]
                    try:
                        parsed = json.loads(raw_object)
                    except json.JSONDecodeError:
                        start = None
                        continue
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start = None
                continue
            if char == "]" and depth == 0:
                break
    return objects


def _normalize_coverage_matrix(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    matrix: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            matrix.append(
                {
                    "id": f"c{index}",
                    "question": item,
                    "expected_output": item,
                    "owner_agent_id": "",
                    "status": "open",
                    "agents": [],
                    "evidence_node_ids": [],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"c{index}").strip()
        matrix.append(
            {
                "id": item_id,
                "question": str(item.get("question") or item.get("objective") or item_id).strip(),
                "expected_output": str(item.get("expected_output") or item.get("output") or "").strip(),
                "owner_agent_id": str(item.get("owner_agent_id") or item.get("owner") or "").strip(),
                "status": str(item.get("status") or "open").strip() or "open",
                "agents": _string_list(item.get("agents")),
                "evidence_node_ids": _string_list(item.get("evidence_node_ids")),
            }
        )
    return matrix
