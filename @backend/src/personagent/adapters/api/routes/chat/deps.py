"""Shared route dependencies to break parent↔child circular imports."""

from __future__ import annotations

from personagent.adapters.api.routes.chat.helpers import get_db as get_db
from personagent.adapters.composition import get_container as get_container

__all__ = ["get_db", "get_container"]
