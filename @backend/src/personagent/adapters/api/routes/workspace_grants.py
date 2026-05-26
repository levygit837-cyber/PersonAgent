"""Workspace grant registry for user-selected local roots."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from personagent.infrastructure.settings.settings import Settings, get_settings


def workspace_id_for_root(root: Path) -> str:
    resolved = root.expanduser().resolve()
    digest = sha256(str(resolved).encode("utf-8")).hexdigest()[:24]
    return f"wks_{digest}"


def register_workspace_grant(
    root: str | Path,
    *,
    source: str = "api",
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    resolved = Path(root).expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"Workspace root does not exist or is not a directory: {resolved}")

    grants = _load_grants(settings)
    now = datetime.now(UTC).isoformat()
    workspace_id = workspace_id_for_root(resolved)
    existing = grants.get(workspace_id) if isinstance(grants.get(workspace_id), dict) else {}
    grant = {
        "workspace_id": workspace_id,
        "root": str(resolved),
        "source": source,
        "created_at": str(existing.get("created_at") or now),
        "last_used_at": now,
    }
    grants[workspace_id] = grant
    _save_grants(settings, grants)
    return grant


def resolve_workspace_root(
    *,
    workspace_id: str | None = None,
    workspace_root: str | Path | None = None,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    if workspace_id:
        grant = _load_grants(settings).get(workspace_id)
        if not isinstance(grant, dict) or not grant.get("root"):
            raise ValueError(f"Unknown workspace_id: {workspace_id}")
        root = Path(str(grant["root"])).expanduser().resolve()
        _touch_grant(settings, workspace_id)
        return root

    if workspace_root:
        root = Path(workspace_root).expanduser().resolve()
        if _is_config_allowed_root(root, settings) or _has_grant_for_root(root, settings):
            return root
        raise ValueError(f"Workspace root is not granted: {root}")

    return settings.tool_workspace_root_path.expanduser().resolve()


def is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_config_allowed_root(root: Path, settings: Settings) -> bool:
    return any(is_path_inside(root, allowed.expanduser().resolve()) for allowed in settings.tool_allowed_root_paths)


def _has_grant_for_root(root: Path, settings: Settings) -> bool:
    resolved = root.expanduser().resolve()
    return any(
        isinstance(grant, dict) and Path(str(grant.get("root", ""))).expanduser().resolve() == resolved
        for grant in _load_grants(settings).values()
    )


def _touch_grant(settings: Settings, workspace_id: str) -> None:
    grants = _load_grants(settings)
    grant = grants.get(workspace_id)
    if not isinstance(grant, dict):
        return
    grant["last_used_at"] = datetime.now(UTC).isoformat()
    grants[workspace_id] = grant
    _save_grants(settings, grants)


def _grant_path(settings: Settings) -> Path:
    raw_path = getattr(settings, "personagent_workspace_grants_path", None)
    return Path(raw_path or "~/.cache/personagent/workspace_grants.json").expanduser()


def _load_grants(settings: Settings) -> dict[str, Any]:
    path = _grant_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_grants(settings: Settings, grants: dict[str, Any]) -> None:
    path = _grant_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        path.parent.chmod(0o700)
    path.write_text(json.dumps(grants, ensure_ascii=False, indent=2), encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)
