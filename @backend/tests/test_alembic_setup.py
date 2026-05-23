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


def test_baseline_revision_is_present_and_is_the_head() -> None:
    """The baseline revision must exist and be the current head of history."""

    config = build_config()
    script_dir = ScriptDirectory.from_config(config)
    revisions = list(script_dir.walk_revisions())

    assert any(rev.revision == BASELINE_REVISION for rev in revisions), (
        f"baseline revision {BASELINE_REVISION!r} missing from versions/"
    )
    assert script_dir.get_current_head() == BASELINE_REVISION


def test_offline_upgrade_emits_alembic_version_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``alembic upgrade --sql`` against the baseline must create the bookkeeping table.

    This is the smoke test that the env.py module imports without side effects
    and that offline mode (no database connection) is wired correctly. Alembic
    writes the generated SQL to ``sys.stdout`` in ``--sql`` mode, so we read
    it back via ``capsys`` rather than poking at internals.
    """

    config = build_config(database_url="postgresql+psycopg://stub:stub@localhost/stub")

    command.upgrade(config, "head", sql=True)

    output = capsys.readouterr().out
    assert "CREATE TABLE alembic_version" in output
    # Baseline migration itself is a no-op; the only artifact should be the
    # version bookkeeping row.
    assert re.search(r"INSERT INTO alembic_version", output) is not None
    assert BASELINE_REVISION in output


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
