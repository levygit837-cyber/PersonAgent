"""Unit test shared fixtures.

Prevents tests from scanning skill directories (~/.codex/skills,
~/.personagent/skills) which can load 100+ skill files and spike memory
by 2GB+ during test runs.
"""

import pytest


@pytest.fixture(autouse=True)
def patch_skill_discovery(monkeypatch):
    """Block all skill discovery in unit tests.

    Loading 100+ real skills from ~/.codex/skills spikes RAM by 2GB+.
    Unit tests should use mocked skills, not scan the filesystem.
    """
    from personagent.domain.prompts import skills

    monkeypatch.setattr(skills, "skill_roots", lambda **kwargs: ())
    monkeypatch.setattr(skills, "discover_skills", lambda **kwargs: [])
    monkeypatch.setattr(skills, "discover_enabled_skills", lambda **kwargs: [])
    monkeypatch.setattr(skills, "find_skill", lambda *args, **kwargs: None)
