"""Session routes — re-exports only, zero business logic."""

from fastapi import APIRouter, Depends

from personagent.adapters.api.routes.chat import get_db
from personagent.adapters.api.routes.sessions.browser.interaction import (
    register_browser_interaction_routes,
)
from personagent.adapters.api.routes.sessions.browser.viewport import (
    _browser_worker as _browser_worker,
)
from personagent.adapters.api.routes.sessions.browser.viewport import (
    register_browser_viewport_routes,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _coerce_dict as _coerce_dict,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _coerce_list as _coerce_list,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _load_conversation as _load_conversation,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _now_iso as _now_iso,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _resolve_optional_workspace as _resolve_optional_workspace,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _safe_event_source as _safe_event_source,
)
from personagent.adapters.api.routes.sessions.panel.helpers import (
    _save_conversation as _save_conversation,
)
from personagent.adapters.api.routes.sessions.panel.panel import (
    register_panel_routes,
)
from personagent.adapters.api.routes.sessions.workspace.cooperation import (
    register_cooperation_routes,
)
from personagent.adapters.api.routes.sessions.workspace.data import (
    register_workspace_data_routes,
)
from personagent.adapters.composition import get_container as get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)

register_browser_viewport_routes(router)
register_cooperation_routes(router)
register_browser_interaction_routes(router)
register_workspace_data_routes(router)
register_panel_routes(router)
