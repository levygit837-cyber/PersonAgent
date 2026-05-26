"""Tests for the tenancy primitives.

These tests pin the two invariants every other layer of the application
relies on:

* :data:`DEFAULT_TENANT_ID` is a stable UUID (never regenerated on import).
* The application-layer re-export and the domain-layer canonical
  definition stay in sync, so the value any caller sees is the same one
  Alembic seeds into the database.
* The ``Conversation`` domain entity defaults its ``tenant_id`` to the
  same constant -- otherwise the repository layer would silently write
  rows under a different tenant.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from uuid import UUID

from personagent.application.state import (
    DEFAULT_TENANT_ID as APP_DEFAULT_TENANT_ID,
)
from personagent.application.state import (
    DEFAULT_TENANT_SLUG as APP_DEFAULT_TENANT_SLUG,
)
from personagent.domain.conversation.models import Conversation
from personagent.domain.conversation.tenancy import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_SLUG,
)


def test_default_tenant_id_is_stable_uuid() -> None:
    """The constant must be a real UUID and identical across imports."""

    assert isinstance(DEFAULT_TENANT_ID, UUID)
    assert str(DEFAULT_TENANT_ID) == "00000000-0000-0000-0000-000000000001"

    # Re-importing must not regenerate the value.
    reloaded = importlib.import_module("personagent.domain.conversation.tenancy")
    assert reloaded.DEFAULT_TENANT_ID == DEFAULT_TENANT_ID


def test_application_state_reexports_the_domain_default() -> None:
    """The application-layer re-export must point at the same constant."""

    assert APP_DEFAULT_TENANT_ID is DEFAULT_TENANT_ID
    assert APP_DEFAULT_TENANT_SLUG == DEFAULT_TENANT_SLUG


def test_conversation_default_tenant_id_matches_constant() -> None:
    """Newly constructed conversations must land under the default tenant."""

    conversation = Conversation()

    assert conversation.tenant_id == DEFAULT_TENANT_ID


def test_default_tenant_in_database_bootstrap_matches_domain_constant() -> None:
    """The seed in ``database.py`` must use the same UUID as the domain.

    ``database.py`` deliberately hard-codes the tenant UUID (rather than
    importing it) to keep its bootstrap surface free of cross-layer
    imports. This test guards against the two definitions drifting.
    """

    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    database_py = (
        repo_root
        / "src"
        / "personagent"
        / "infrastructure"
        / "persistence"
        / "database.py"
    )
    source = database_py.read_text(encoding="utf-8")

    match = re.search(r'_DEFAULT_TENANT_ID_STR\s*=\s*"([^"]+)"', source)
    assert match is not None, "database.py must define _DEFAULT_TENANT_ID_STR"
    assert match.group(1) == str(DEFAULT_TENANT_ID)


def test_default_tenant_in_alembic_revision_matches_domain_constant() -> None:
    """Revision 0002 must seed the same tenant UUID we surface in code."""

    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    revision_py = (
        repo_root
        / "src"
        / "personagent"
        / "infrastructure"
        / "persistence"
        / "alembic"
        / "versions"
        / "20251124_0000_0002_multi_tenant_primitives.py"
    )
    source = revision_py.read_text(encoding="utf-8")

    match = re.search(r'_DEFAULT_TENANT_ID\s*=\s*"([^"]+)"', source)
    assert match is not None, "0002 revision must define _DEFAULT_TENANT_ID"
    assert match.group(1) == str(DEFAULT_TENANT_ID)
