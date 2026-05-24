"""FastAPI chat routes package."""

from fastapi import APIRouter

from personagent.infrastructure.persistence.database import AsyncSessionLocal as AsyncSessionLocal
from personagent.interfaces.api.routes.chat.completion import (
    _answer_pending_user_question as _answer_pending_user_question,
)
from personagent.interfaces.api.routes.chat.completion import (
    _approve_pending_tool_call as _approve_pending_tool_call,
)
from personagent.interfaces.api.routes.chat.completion import (
    _create_chat_use_case as _create_chat_use_case,
)
from personagent.interfaces.api.routes.chat.completion import (
    _load_conversation_for_decision as _load_conversation_for_decision,
)
from personagent.interfaces.api.routes.chat.completion import (
    register_completion_routes,
)
from personagent.interfaces.api.routes.chat.completion import (
    resolve_context_workspace_root as resolve_context_workspace_root,
)
from personagent.interfaces.api.routes.chat.completion import (
    resolve_model as resolve_model,
)
from personagent.interfaces.api.routes.chat.helpers import get_db as get_db
from personagent.interfaces.api.routes.chat.models_listing import register_model_listing_routes
from personagent.interfaces.api.routes.chat.plan_approval import register_plan_approval_routes
from personagent.interfaces.api.routes.chat.team_chat import (
    _team_trace_event_for_storage as _team_trace_event_for_storage,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    load_team_memory_snapshot as load_team_memory_snapshot,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_blackboard_event as persist_team_blackboard_event,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_memory_snapshot as persist_team_memory_snapshot,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_run as persist_team_run,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    persist_team_run_started as persist_team_run_started,
)
from personagent.interfaces.api.routes.chat.team_chat import (
    register_team_chat_routes,
)
from personagent.interfaces.api.routes.chat.tool_approval import register_tool_approval_routes
from personagent.interfaces.config.di_container import get_container as get_container

router = APIRouter(prefix="/chat", tags=["chat"])

register_model_listing_routes(router)
register_plan_approval_routes(router)
register_tool_approval_routes(router)
register_team_chat_routes(router)
register_completion_routes(router)
