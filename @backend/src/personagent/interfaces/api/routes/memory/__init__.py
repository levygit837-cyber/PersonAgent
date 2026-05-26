"""FastAPI memory management routes."""

from __future__ import annotations

# Import submodules to register routes on the shared router
from personagent.interfaces.api.routes.memory import crud, operational  # noqa: F401
from personagent.interfaces.api.routes.memory._router import (
    CONTAINER_DEPENDENCY as CONTAINER_DEPENDENCY,
)
from personagent.interfaces.api.routes.memory._router import (
    EVENT_LIMIT_QUERY as EVENT_LIMIT_QUERY,
)
from personagent.interfaces.api.routes.memory._router import (
    MEMORY_REPO_DEPENDENCY as MEMORY_REPO_DEPENDENCY,
)
from personagent.interfaces.api.routes.memory._router import (
    MEMORY_TYPE_QUERY as MEMORY_TYPE_QUERY,
)
from personagent.interfaces.api.routes.memory._router import (
    PRIVATE_SCOPE_QUERY as PRIVATE_SCOPE_QUERY,
)
from personagent.interfaces.api.routes.memory._router import (
    get_memory_repo as get_memory_repo,
)
from personagent.interfaces.api.routes.memory._router import router as router
from personagent.interfaces.api.routes.memory.models import (
    MemoryCreateRequest as MemoryCreateRequest,
)
from personagent.interfaces.api.routes.memory.models import (
    MemoryListResponse as MemoryListResponse,
)
from personagent.interfaces.api.routes.memory.models import (
    MemoryResponse as MemoryResponse,
)
from personagent.interfaces.api.routes.memory.models import (
    MemoryUpdateRequest as MemoryUpdateRequest,
)
from personagent.interfaces.api.routes.memory.models import (
    OperationalRecallRequest as OperationalRecallRequest,
)
from personagent.interfaces.api.routes.memory.models import (
    OperationalReindexRequest as OperationalReindexRequest,
)
