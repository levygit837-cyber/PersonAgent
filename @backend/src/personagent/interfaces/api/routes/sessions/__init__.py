"""Session routes — re-exports only, zero business logic."""

from fastapi import APIRouter, Depends

from personagent.interfaces.api.routes.chat import get_db
from personagent.interfaces.api.routes.sessions._helpers import (
    _coerce_dict as _coerce_dict,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _coerce_list as _coerce_list,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _load_conversation as _load_conversation,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _now_iso as _now_iso,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _resolve_optional_workspace as _resolve_optional_workspace,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _safe_event_source as _safe_event_source,
)
from personagent.interfaces.api.routes.sessions._helpers import (
    _save_conversation as _save_conversation,
)
from personagent.interfaces.api.routes.sessions.browser_interaction import (
    register_browser_interaction_routes,
)
from personagent.interfaces.api.routes.sessions.browser_viewport import (
    _browser_worker as _browser_worker,
)
from personagent.interfaces.api.routes.sessions.browser_viewport import (
    register_browser_viewport_routes,
)
from personagent.interfaces.api.routes.sessions.cooperation import (
    register_cooperation_routes,
)
from personagent.interfaces.api.routes.sessions.panel import (
    register_panel_routes,
)
from personagent.interfaces.api.routes.sessions.workspace_data import (
    register_workspace_data_routes,
)
from personagent.interfaces.config.di_container import get_container as get_container

router = APIRouter(prefix="/sessions", tags=["sessions"])
DB_SESSION_DEPENDENCY = Depends(get_db)

register_browser_viewport_routes(router)
register_cooperation_routes(router)
register_browser_interaction_routes(router)
register_workspace_data_routes(router)
register_panel_routes(router)
