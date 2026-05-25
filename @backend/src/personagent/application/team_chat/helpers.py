"""Pure helpers and constants shared by team-chat orchestrator and phase collaborators.

Lives at module level so that orchestrator AND the four phase collaborators
(`AgentTurnRunner`, `ConsensusPhase`, `CoordinatorPhase`, `FinalSynthesis`)
can import from one place without circular dependencies.

Before this module existed, every collaborator imported these helpers from
``orchestrator`` lazily (inside method bodies) to avoid the cycle
``orchestrator -> collaborator -> orchestrator``. That worked but violated
the "imports at top" rule and made the dependency graph harder to read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from personagent.application.team_chat.blackboard import (
    _Blackboard,
)
from personagent.application.team_chat.blackboard_json_parsing import (
    _clamp_float,
    _digest,
    _parse_json_object,
)
from personagent.application.team_chat.blackboard_scoring import (
    _coherency_score,
    _now_iso,
)
from personagent.application.team_chat.contracts import (
    TeamAgentConfig,
    TeamChatRequest,
    TeamConfig,
)
from personagent.application.team_chat.types import (
    BlackboardEntry,
    TurnResult,
)
from personagent.application.tools import ToolRuntimeConfig
from personagent.domain.models.conversation import Conversation
from personagent.domain.prompts.prompt import shared_runtime_policy_overlay
from personagent.domain.prompts.sections.states import render_agent_state_policy
from personagent.domain.tools import ToolExecutionStatus, ToolResult, ToolUseContext

# Phase constants — used by orchestrator and collaborators.
INDEPENDENT_PHASE = "independent_round"
BLACKBOARD_PHASE = "blackboard_publish"
DEBATE_PHASE = "debate_round"
VOTE_PHASE = "vote"
EXECUTION_CONTRACT_PHASE = "execution_contract"
COORDINATOR_PLANNING_PHASE = "coordinator_planning"
COORDINATOR_PHASE = "coordinator_final"
TOOL_PHASE_PLAN = "plan_tools"
TOOL_PHASE_READ = "read_tools"
TOOL_PHASE_MUTATING_PROPOSAL = "mutating_proposal"
TOOL_PHASE_AUDIT = "tool_audit"

CLAIM_TYPES = ("claim", "evidence", "assumption", "risk", "blocker", "proposal", "tool_result", "decision")
MUTATING_TOOL_NAMES = {"Write", "Edit", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskClose", "TaskAppendOutput"}


def _agent_system_prompt(
    request: TeamChatRequest,
    team: TeamConfig,
    agent: TeamAgentConfig,
) -> str:
    base = request.system_prompt or "You are part of a collaborative PersonAgent team."
    return (
        f"{base}\n\n"
        f"Team mode is active. Team: {team.name}. You are {agent.name}, role: {agent.role}.\n"
        f"{agent.system_prompt}\n"
        f"{_team_policy_overlay()}\n"
        "Tool policy: guarded autonomy. Read-only investigation can be autonomous; destructive "
        "or mutating actions must be proposed on the blackboard and require team coordination.\n"
        "Never claim to be the final answer. Your output is one blackboard contribution."
    )


def _team_policy_overlay() -> str:
    return "\n\n".join(
        (
            shared_runtime_policy_overlay(
                todo_available=True,
                parallel_tools_available=True,
            ),
            render_agent_state_policy(
                (
                    "intake",
                    "context_discovery",
                    "tool_execution",
                    "debug_recovery",
                    "runtime_validation",
                    "memory_recall",
                    "user_checkpoint",
                    "finalization",
                )
            ),
        )
    )


def _blackboard_event(
    run_id: str,
    conversation_id: Any,
    entry: BlackboardEntry,
) -> dict[str, Any]:
    return {
        "event": "blackboard_event",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        **entry.to_event_payload(),
    }


def _blackboard_snapshot_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "blackboard_snapshot",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": BLACKBOARD_PHASE,
        "snapshot": blackboard.snapshot(),
        "created_at": _now_iso(),
    }


def _claim_graph_delta_event(
    run_id: str,
    conversation_id: Any,
    entry: BlackboardEntry,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "claim_graph_delta",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": entry.round_index,
        "phase": entry.phase,
        "agent_id": entry.agent.id,
        "agent_name": entry.agent.name,
        "agent_role": entry.agent.role,
        "sequence": entry.sequence,
        "delta": blackboard.claim_delta_for(entry),
        "created_at": _now_iso(),
    }


def _coverage_matrix_event(
    run_id: str,
    conversation_id: Any,
    round_index: int,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    matrix = blackboard.coverage_matrix()
    covered = sum(1 for item in matrix if item.get("status") == "covered")
    return {
        "event": "coverage_matrix",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": BLACKBOARD_PHASE,
        "coverage_matrix": matrix,
        "coverage_complete": covered,
        "coverage_total": len(matrix),
        "created_at": _now_iso(),
    }


def _coherency_score_event(
    run_id: str,
    conversation_id: Any,
    turn: TurnResult,
    blackboard: _Blackboard,
) -> dict[str, Any]:
    return {
        "event": "coherency_score",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": turn.round_index,
        "phase": turn.phase,
        "agent_id": turn.agent.id,
        "agent_name": turn.agent.name,
        "agent_role": turn.agent.role,
        "coherency_score": turn.coherency_score,
        "coherency": blackboard.coherency_summary(),
        "created_at": _now_iso(),
    }


def _runtime_context(request: TeamChatRequest) -> str:
    context: dict[str, Any] = {}
    if request.workspace_root:
        context["workspace_root"] = request.workspace_root
    if request.tool_context:
        context["tool_context"] = request.tool_context
    if not context:
        return "No workspace context was provided."
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))[:1200]


def _agent_tool_context(
    request: TeamChatRequest,
    run_id: str,
    agent: TeamAgentConfig,
    round_index: int,
    phase: str,
) -> dict[str, Any]:
    context = dict(request.tool_context or {})
    context.update(
        {
            "team_run_id": run_id,
            "run_id": run_id,
            "workspace_id": _workspace_id(request),
            "agent_id": agent.id,
            "agent_name": agent.name,
            "round": round_index,
            "phase": phase,
            "tool_policy": "guarded_autonomy",
            "tool_phase": phase,
        }
    )
    if request.workspace_root:
        context.setdefault("workspace_root", request.workspace_root)
        context.setdefault("cwd", request.workspace_root)
        context.setdefault("allowed_roots", [request.workspace_root])
    return context


def _tool_use_context_from_request(
    *,
    request: TeamChatRequest,
    conversation: Conversation,
    raw_context: dict[str, Any],
    config: ToolRuntimeConfig,
) -> ToolUseContext:
    raw_workspace_root = raw_context.get("workspace_root") or request.workspace_root
    workspace_root = (
        Path(str(raw_workspace_root)).expanduser().resolve()
        if raw_workspace_root
        else config.workspace_root.resolve()
    )
    root_scope = (workspace_root,) if raw_workspace_root else config.allowed_roots
    requested_roots = raw_context.get("allowed_roots")
    allowed_roots = root_scope
    if isinstance(requested_roots, list) and requested_roots:
        allowed_roots = tuple(
            _resolve_allowed_path(str(path), workspace_root, root_scope)
            for path in requested_roots
        )
    raw_cwd = raw_context.get("cwd")
    cwd = _resolve_allowed_path(str(raw_cwd), workspace_root, allowed_roots) if raw_cwd else workspace_root
    metadata = {
        "team_mode": True,
        "team_run_id": raw_context.get("team_run_id"),
        "workspace_id": raw_context.get("workspace_id"),
        "agent_id": raw_context.get("agent_id"),
        "agent_name": raw_context.get("agent_name"),
        "round": raw_context.get("round"),
        "phase": raw_context.get("phase"),
        "tool_phase": raw_context.get("tool_phase"),
        "request": raw_context,
    }
    return ToolUseContext(
        conversation_id=str(conversation.id),
        workspace_root=workspace_root,
        cwd=cwd,
        allowed_roots=allowed_roots,
        permissions={
            "mode": "team_guarded_autonomy",
            "team_mode": True,
            "agent_id": raw_context.get("agent_id"),
            "mutating_requires_consensus": True,
        },
        limits={
            "read_max_bytes": config.read_max_bytes,
            "read_default_limit": config.read_default_limit,
            "read_max_lines": config.read_max_lines,
            "search_timeout_ms": config.search_timeout_ms,
            "shell_timeout_ms": config.shell_timeout_ms,
            "web_timeout_ms": config.web_timeout_ms,
            "web_max_bytes": config.web_max_bytes,
            "max_tool_iterations": config.max_tool_iterations,
            "max_concurrency": config.max_concurrency,
            "result_max_chars": config.result_max_chars,
            "tool_result_storage_root": (
                str(config.tool_result_storage_root) if config.tool_result_storage_root else None
            ),
            "web_allowed_domains": config.web_allowed_domains,
            "web_blocked_domains": config.web_blocked_domains,
            "skill_roots": tuple(str(path) for path in config.skill_roots),
        },
        metadata=metadata,
    )


def _resolve_allowed_path(
    raw_path: str,
    base_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    path = Path(raw_path).expanduser()
    candidate = path if path.is_absolute() else base_root / path
    resolved = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise ValueError(f"Tool path is outside configured roots: {raw_path}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _tool_phase_event(
    run_id: str,
    conversation_id: Any,
    agent: TeamAgentConfig,
    round_index: int,
    phase: str,
    tool_phase: str,
    *,
    calls: list[dict[str, Any]] | None = None,
    results: list[dict[str, Any]] | None = None,
    proposals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "event": "tool_phase",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "round": round_index,
        "phase": phase,
        "tool_phase": tool_phase,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_role": agent.role,
        "calls": calls or [],
        "results": results or [],
        "proposals": proposals or [],
        "created_at": _now_iso(),
    }


def _tool_proposal(raw_call: dict[str, Any], *, reason: str) -> dict[str, Any]:
    function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    name = str(function.get("name") or raw_call.get("name") or "tool")
    return {
        "tool_call": raw_call,
        "tool_call_id": str(raw_call.get("id") or ""),
        "tool_name": name,
        "reason": reason,
        "summary": f"{name} requires Coordinator consensus before execution: {reason}",
        "mutating": True,
    }


def _tool_result_payload(result: ToolResult) -> dict[str, Any]:
    result_summary = result.data.get("content") if isinstance(result.data, dict) else result.content
    return {
        "tool_call_id": result.tool_call_id,
        "tool_name": result.tool_name,
        "status": result.status.value
        if isinstance(result.status, ToolExecutionStatus)
        else str(result.status),
        "is_error": result.is_error,
        "content": _digest(result.content, 900),
        "summary": _digest(str(result_summary or ""), 400),
        "data": result.data,
        "metadata": result.metadata,
    }


def _unique_tool_call_ids(
    tool_calls: list[dict[str, Any]],
    *,
    round_index: int,
    agent_id: str,
) -> list[dict[str, Any]]:
    unique_calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, tool_call in enumerate(tool_calls):
        original_id = str(tool_call.get("id") or "").strip()
        candidate = original_id or f"team-tool-{round_index}-{agent_id}-{index}"
        if candidate in seen:
            candidate = f"{candidate}-{index}"
        seen.add(candidate)
        next_call = dict(tool_call)
        next_call["id"] = candidate
        extra = next_call.get("extra_content")
        next_extra = dict(extra) if isinstance(extra, dict) else {}
        next_extra.update({"agent_id": agent_id, "round": round_index, "original_tool_call_id": original_id or None})
        next_call["extra_content"] = next_extra
        unique_calls.append(next_call)
    return unique_calls


def _turn_text(content: str, reasoning: str) -> str:
    return content.strip()


def _claim_graph_output_contract() -> str:
    return (
        "Return one compact JSON object only, no markdown fence, no prose outside JSON. "
        "Use keys: claims, evidence, assumptions, risks, blockers, proposals, decisions, "
        "coherency_score. Publish at most 6 total list items. Each item must include text, "
        "confidence, and coverage; optional supports, contradicts, depends_on. "
        "Use proposals for mutating/destructive tool actions. Keep every text under 220 chars."
    )


def _turn_coherency_score(content: str, user_input: str, blackboard: _Blackboard) -> float:
    structured = _parse_json_object(content) if content.strip().startswith(("{", "```")) else {}
    raw = structured.get("coherency_score")
    if isinstance(raw, (int, float)):
        return round(_clamp_float(raw, 0, 1), 3)
    return round(_coherency_score(content, user_input, blackboard.snapshot().get("execution_contract")), 3)


def _workspace_id(request: TeamChatRequest) -> str | None:
    raw = request.tool_context.get("workspace_id") if isinstance(request.tool_context, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    root = request.workspace_root or (
        request.tool_context.get("workspace_root")
        if isinstance(request.tool_context, dict)
        else None
    )
    if isinstance(root, str) and root.strip():
        return str(Path(root).expanduser().resolve())
    return None


def _cancelled_event(run_id: str, conversation_id: Any) -> dict[str, Any]:
    return {
        "event": "team_run_cancelled",
        "run_id": run_id,
        "conversation_id": str(conversation_id),
        "created_at": _now_iso(),
    }


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _apply_workspace_metadata(
    conversation: Conversation,
    workspace_root: str | None,
    tool_context: dict[str, Any] | None,
) -> None:
    value = workspace_root or (tool_context or {}).get("workspace_root")
    if isinstance(value, str) and value.strip():
        conversation.metadata["workspace_root"] = value.strip()
