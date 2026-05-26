"""Dependency injection composition root."""

from personagent.adapters.composition.container import (
    DIContainer,
    get_container,
    reset_container,
)

__all__ = ["DIContainer", "get_container", "reset_container"]
