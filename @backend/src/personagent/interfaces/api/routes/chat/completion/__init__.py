"""Chat completion endpoints and shared use-case helpers."""

from personagent.interfaces.api.routes.chat.completion.resolvers import (
    resolve_context_workspace_root as resolve_context_workspace_root,
)
from personagent.interfaces.api.routes.chat.completion.resolvers import (
    resolve_model as resolve_model,
)
from personagent.interfaces.api.routes.chat.completion.routes import (
    register_completion_routes as register_completion_routes,
)
from personagent.interfaces.api.routes.chat.completion.use_case import (
    _answer_pending_user_question as _answer_pending_user_question,
)
from personagent.interfaces.api.routes.chat.completion.use_case import (
    _approve_pending_tool_call as _approve_pending_tool_call,
)
from personagent.interfaces.api.routes.chat.completion.use_case import (
    _create_chat_use_case as _create_chat_use_case,
)
from personagent.interfaces.api.routes.chat.completion.use_case import (
    _load_conversation_for_decision as _load_conversation_for_decision,
)
