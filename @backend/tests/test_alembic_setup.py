"""Tests for the Alembic infrastructure.

These tests verify the *setup* without touching a live database: configuration
resolves correctly, the baseline revision is discoverable, ``env.py`` imports
cleanly, and offline SQL emission produces the expected ``alembic_version``
table. A live-Postgres test for the stamp flow lives in the integration suite
because it requires an actual server.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from personagent.infrastructure.persistence.migration_runner import (
    _alembic_ini_path,
    build_config,
)

BASELINE_REVISION = "0001_baseline"
MULTI_TENANT_REVISION = "0002_multi_tenant_primitives"


def test_alembic_ini_exists_at_backend_root() -> None:
    """``alembic.ini`` must sit next to ``pyproject.toml`` so the CLI just works."""

    ini_path = _alembic_ini_path()
    assert ini_path.is_file()
    assert (ini_path.parent / "pyproject.toml").is_file()


def test_alembic_script_directory_resolves() -> None:
    """The configured ``script_location`` must point at our versions dir."""

    config = build_config()
    script_dir = ScriptDirectory.from_config(config)
    versions = Path(script_dir.dir) / "versions"

    assert versions.is_dir()


def test_baseline_revision_is_present_in_history() -> None:
    """The baseline revision must always remain in the migration chain."""

    config = build_config()
    script_dir = ScriptDirectory.from_config(config)
    revisions = list(script_dir.walk_revisions())

    assert any(rev.revision == BASELINE_REVISION for rev in revisions), (
        f"baseline revision {BASELINE_REVISION!r} missing from versions/"
    )


def test_multi_tenant_revision_descends_from_baseline() -> None:
    """0002 must point back to 0001 so the chain is linear and well-formed."""

    config = build_config()
    script_dir = ScriptDirectory.from_config(config)
    multi_tenant = script_dir.get_revision(MULTI_TENANT_REVISION)

    assert multi_tenant is not None, (
        f"revision {MULTI_TENANT_REVISION!r} missing from versions/"
    )
    assert multi_tenant.down_revision == BASELINE_REVISION


def test_head_is_the_latest_revision() -> None:
    """Whatever the latest revision is, it must be the head of history.

    Pinned to ``MULTI_TENANT_REVISION`` today; when later phases add new
    revisions this test gets updated together with the new constant.
    """

    config = build_config()
    script_dir = ScriptDirectory.from_config(config)

    assert script_dir.get_current_head() == MULTI_TENANT_REVISION


def test_offline_upgrade_emits_alembic_version_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``alembic upgrade --sql`` against the baseline must create the bookkeeping table.

    Offline mode emits SQL to stdout without touching a real database, so
    every guarded migration must be safe to run with no inspector available.
    The 0002 migration is a regression target for that: its
    ``_has_table`` / ``_has_column`` helpers short-circuit in offline mode.
    """

    config = build_config(database_url="postgresql+psycopg://stub:stub@localhost/stub")

    command.upgrade(config, "head", sql=True)

    output = capsys.readouterr().out
    assert "CREATE TABLE alembic_version" in output
    assert re.search(r"INSERT INTO alembic_version", output) is not None
    assert BASELINE_REVISION in output
    # 0002 must produce its DDL too (the multi-tenant table and the
    # FK/index on conversations).
    assert "CREATE TABLE tenants" in output
    assert "ix_conversations_tenant_id" in output


def test_migration_runner_safe_url_strips_credentials() -> None:
    """Internal helper must never leak passwords through logs."""

    from personagent.infrastructure.persistence.migration_runner import _safe_url

    assert (
        _safe_url("postgresql+asyncpg://user:secret@db.internal:5432/app")
        == "postgresql+asyncpg://***@db.internal:5432/app"
    )
    assert _safe_url("postgresql://localhost/app") == "postgresql://localhost/app"
    assert _safe_url(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "postgresql+asyncpg://u:p@h/d",
            "postgresql+psycopg://u:p@h/d",
        ),
        ("postgresql://u:p@h/d", "postgresql://u:p@h/d"),
        ("sqlite:///./local.db", "sqlite:///./local.db"),
    ],
)
def test_to_sync_url_swaps_only_asyncpg(raw: str, expected: str) -> None:
    """Offline mode must translate the async driver to a sync equivalent."""

    from personagent.infrastructure.persistence.migration_runner import to_sync_url

    assert to_sync_url(raw) == expected
