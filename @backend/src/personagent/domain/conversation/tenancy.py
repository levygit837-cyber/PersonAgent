"""Tenancy primitives -- pure domain values.

This module lives in the domain layer so other domain models (e.g.
:class:`Conversation`) can carry a ``tenant_id`` without violating Clean
Architecture boundaries by reaching up into the application layer.

Single-tenant installs are modeled as the *default tenant*; its UUID is
hard-coded here so that backups, fixtures, and cross-instance
comparisons stay deterministic. Alembic revision ``0002`` creates the
matching row in the ``tenants`` table.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

DEFAULT_TENANT_ID: Final[UUID] = UUID("00000000-0000-0000-0000-000000000001")
"""UUID of the single tenant present in every fresh database."""

DEFAULT_TENANT_SLUG: Final[str] = "default"
"""Human-readable slug for the default tenant."""


__all__ = ["DEFAULT_TENANT_ID", "DEFAULT_TENANT_SLUG"]
