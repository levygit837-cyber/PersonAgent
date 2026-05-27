from __future__ import annotations

import re
from pathlib import Path


def project_slug_from_workspace(workspace_root: str | None) -> str:
    if not workspace_root:
        return "default"
    name = Path(workspace_root).name
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).lower() or "default"
