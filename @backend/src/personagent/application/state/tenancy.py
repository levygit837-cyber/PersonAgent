"""Tenancy primitives surfaced from the application layer.

These values originate in :mod:`personagent.domain.models.tenancy` -- the
domain layer owns the canonical tenant id so that domain models can carry
``tenant_id`` without taking a dependency on the application layer.

This module re-exports the constants so callers in the application /
interfaces layers can import them from a single location alongside the
other state primitives (:class:`RequestContext`, :class:`AppState`).
"""

from __future__ import annotations

from personagent.domain.conversation.tenancy import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_SLUG,
)

__all__ = ["DEFAULT_TENANT_ID", "DEFAULT_TENANT_SLUG"]
