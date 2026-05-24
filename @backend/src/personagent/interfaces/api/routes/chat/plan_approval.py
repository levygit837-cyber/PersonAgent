"""Plan approval endpoints (approve, continue, cancel).

Endpoint functions access ``_load_conversation_for_decision`` through
the ``_chat`` module reference so that monkeypatched ``get_container``
values inside that function are resolved at call time.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Late-binding module reference.  See module docstring for rationale.
import personagent.interfaces.api.routes.chat as _chat
from personagent.application.plan_mode import (
    normalize_plan_state,
    plan_mode_event,
    write_plan_state,
)
from personagent.interfaces.api.routes.chat.helpers import (
    DB_SESSION_DEPENDENCY,
    PlanDecisionRequest,
    _require_plan_approval,
    _update_plan_approval_artifact,
)


def register_plan_approval_routes(router: APIRouter) -> None:
    """Register plan approve, continue, and cancel endpoints."""

    @router.post("/plan/approve")
    async def approve_plan(
        request: PlanDecisionRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Approve a pending plan and return the execution instruction to inject."""

        conversation, conv_repo = await _chat._load_conversation_for_decision(
            request.conversation_id, session
        )
        state = _require_plan_approval(
            state=normalize_plan_state(conversation.metadata), request=request
        )
        plan_content = str(state.get("plan_content") or "").strip()
        if not plan_content:
            raise HTTPException(status_code=400, detail="Pending plan has no renderable content.")

        approval_id = str(state.get("approval_id") or "")
        feedback = (request.feedback or "").strip()
        injected_message = (
            "The user has approved the following plan. Implement it exactly as specified.\n\n"
            "## Approved Plan\n\n"
            f"{plan_content}\n\n"
        )
        if feedback:
            injected_message = f"{injected_message}## User Feedback\n\n{feedback}\n\n"
        injected_message = f"{injected_message}Proceed with implementation."

        state.update(
            {
                "active": False,
                "status": "approved",
                "approval_id": None,
                "feedback": feedback or None,
                "cancelled": False,
                "pending_injected_message": injected_message,
            }
        )
        write_plan_state(conversation.metadata, state)
        _update_plan_approval_artifact(conversation, approval_id, state)
        conversation.metadata["session_status"] = "idle"
        await conv_repo.update(conversation)

        return {
            **plan_mode_event(str(conversation.id), state),
            "injected_message": injected_message,
        }

    @router.post("/plan/continue")
    async def continue_plan(
        request: PlanDecisionRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Keep PlanMode active for plan revision."""

        conversation, conv_repo = await _chat._load_conversation_for_decision(
            request.conversation_id, session
        )
        state = _require_plan_approval(
            state=normalize_plan_state(conversation.metadata), request=request
        )
        approval_id = str(state.get("approval_id") or "")
        feedback = (request.feedback or "").strip()
        state.update(
            {
                "active": True,
                "status": "draft",
                "approval_id": None,
                "feedback": feedback or None,
                "cancelled": False,
            }
        )
        write_plan_state(conversation.metadata, state)
        _update_plan_approval_artifact(conversation, approval_id, state)
        conversation.metadata["session_status"] = "idle"
        await conv_repo.update(conversation)

        suggested_message = (
            f"Continue planning with this feedback:\n\n{feedback}"
            if feedback
            else "Continue planning. Revise the plan and request approval again when ready."
        )
        return {
            **plan_mode_event(str(conversation.id), state),
            "suggested_message": suggested_message,
        }

    @router.post("/plan/cancel")
    async def cancel_plan(
        request: PlanDecisionRequest,
        session: AsyncSession = DB_SESSION_DEPENDENCY,
    ) -> dict[str, Any]:
        """Cancel PlanMode without executing the plan."""

        conversation, conv_repo = await _chat._load_conversation_for_decision(
            request.conversation_id, session
        )
        state = normalize_plan_state(conversation.metadata)
        if request.approval_id and state.get("approval_id") != request.approval_id:
            raise HTTPException(
                status_code=409, detail="The plan approval does not match the current state."
            )
        approval_id = str(state.get("approval_id") or request.approval_id or "")
        state.update(
            {
                "active": False,
                "status": "cancelled",
                "approval_id": None,
                "feedback": (request.feedback or "").strip() or state.get("feedback"),
                "cancelled": True,
            }
        )
        write_plan_state(conversation.metadata, state)
        _update_plan_approval_artifact(conversation, approval_id, state)
        conversation.metadata["session_status"] = "idle"
        await conv_repo.update(conversation)

        return plan_mode_event(str(conversation.id), state)
