"""Estado estruturado do PlanMode.

O PlanMode é persistido em ``Conversation.metadata`` para manter a primeira
versão sem migração de banco. Este módulo centraliza compatibilidade com o
boolean legado e o contrato visual usado pelo frontend.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

PLAN_MODE_METADATA_KEY = "plan_mode"
PENDING_TOOL_APPROVAL_KEY = "pending_tool_approval"
PENDING_USER_QUESTION_KEY = "pending_user_question"


def new_plan_id() -> str:
    return f"plan_{uuid4().hex}"


def new_plan_approval_id() -> str:
    return f"plan_approval_{uuid4().hex}"


def new_tool_approval_id() -> str:
    return f"tool_approval_{uuid4().hex}"


def empty_plan_state() -> dict[str, Any]:
    return {
        "active": False,
        "status": "inactive",
        "plan_id": None,
        "plan_content": "",
        "approval_id": None,
        "feedback": None,
        "cancelled": False,
    }


def normalize_plan_state(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Retorna o estado estruturado, aceitando o boolean legado."""

    raw = (metadata or {}).get(PLAN_MODE_METADATA_KEY)
    state = empty_plan_state()
    if isinstance(raw, bool):
        state["active"] = raw
        state["status"] = "draft" if raw else "inactive"
        if raw:
            state["plan_id"] = new_plan_id()
        return state
    if isinstance(raw, dict):
        state.update(deepcopy(raw))
        state["active"] = bool(state.get("active"))
        state["cancelled"] = bool(state.get("cancelled"))
        state["status"] = str(state.get("status") or ("draft" if state["active"] else "inactive"))
        state["plan_content"] = str(state.get("plan_content") or "")
        return state
    return state


def is_plan_mode_active(metadata: dict[str, Any] | None) -> bool:
    return bool(normalize_plan_state(metadata).get("active"))


def activate_plan_mode_if_requested(
    metadata: dict[str, Any], *, requested: bool
) -> dict[str, Any] | None:
    """Ativa o PlanMode estruturalmente quando o backend solicita.

    Retorna o estado normalizado se uma ativação ocorreu, ou ``None`` se
    já estava ativo ou não foi requisitado.
    """
    if not requested:
        return None
    state = normalize_plan_state(metadata)
    if state["active"]:
        return None
    state.update(
        {
            "active": True,
            "status": "draft",
            "plan_id": new_plan_id(),
            "plan_content": "",
            "approval_id": None,
            "feedback": None,
            "cancelled": False,
        }
    )
    write_plan_state(metadata, state)
    return state


def auto_finalize_plan_mode(
    metadata: dict[str, Any], assistant_content: str
) -> dict[str, Any] | None:
    """Converte um plano draft em pedido de aprovação automaticamente.

    Usado quando o modelo termina o turno em PlanMode sem chamar ExitPlanMode.
    Retorna o estado normalizado se a finalização ocorreu, ou ``None``.
    """
    state = normalize_plan_state(metadata)
    if not state["active"] or state.get("status") != "draft":
        return None
    state.update(
        {
            "status": "awaiting_approval",
            "plan_content": str(assistant_content or "").strip(),
            "approval_id": new_plan_approval_id(),
            "feedback": None,
            "cancelled": False,
        }
    )
    write_plan_state(metadata, state)
    return state


def write_plan_state(metadata: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    metadata[PLAN_MODE_METADATA_KEY] = normalize_plan_state({PLAN_MODE_METADATA_KEY: state})
    return metadata[PLAN_MODE_METADATA_KEY]


def plan_mode_event(
    conversation_id: str,
    state: dict[str, Any],
    event: str = "plan_mode_changed",
) -> dict[str, Any]:
    normalized = normalize_plan_state({PLAN_MODE_METADATA_KEY: state})
    return {
        "event": event,
        "conversation_id": conversation_id,
        "approval_id": normalized.get("approval_id"),
        "plan_id": normalized.get("plan_id"),
        "plan_content": normalized.get("plan_content") or "",
        "plan_status": normalized.get("status"),
        "plan_active": normalized.get("active"),
        "feedback": normalized.get("feedback"),
        "cancelled": normalized.get("cancelled"),
    }


def planning_instructions(plan_id: str | None) -> str:
    identifier = plan_id or new_plan_id()
    return (
        "Entered Plan Mode.\n\n"
        f"Plan artifact: {identifier}\n\n"
        "PlanMode rules:\n"
        "- You may inspect the workspace, search code, read files, and ask clarifying questions.\n"
        "- You must not mutate workspace files, persistent tasks, shell state, or project state.\n"
        "- The only writable artifact is the plan itself.\n"
        "- When the plan is ready, call ExitPlanMode with the full markdown plan.\n"
        "- Do not implement the plan until the user explicitly approves it."
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
