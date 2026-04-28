from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from personagent.domain.prompts.skills import set_skill_activation
from personagent.interfaces.api.routes import chat, skills


class FakeCommandRegistry:
    def list_commands(self, _root):
        return []


class FakeContainer:
    def __init__(self, root: Path) -> None:
        self.runtime = SimpleNamespace(workspace_root=root, skill_roots=())

    def get_tool_runtime_config(self):
        return self.runtime

    def create_command_registry(self):
        return FakeCommandRegistry()


def write_skill(root: Path, name: str, description: str = "Test skill") -> Path:
    skill_dir = root / ".personagent" / "skills" / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"""---
name: {name.title()}
description: {description}
---
# {name.title()}

Use this skill.
""",
        encoding="utf-8",
    )
    return skill_file


@pytest.mark.asyncio
async def test_skills_api_lists_details_toggles_and_installs_marketplace(
    monkeypatch,
    tmp_path,
):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(workspace, "writer", "Write concise prose")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PERSONAGENT_SKILL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(skills, "get_container", lambda: FakeContainer(workspace))

    app = FastAPI()
    app.include_router(skills.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/skills", params={"workspace_root": str(workspace)})
        assert listed.status_code == 200
        assert listed.json()[0]["invocation_name"] == "writer"
        assert listed.json()[0]["enabled"] is True

        detail = await client.get("/skills/writer", params={"workspace_root": str(workspace)})
        assert detail.status_code == 200
        assert "Use this skill" in detail.json()["content"]

        disabled = await client.patch(
            "/skills/writer/activation",
            params={"workspace_root": str(workspace)},
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json() == {"invocation_name": "writer", "enabled": False}

        relisted = await client.get("/skills", params={"workspace_root": str(workspace)})
        writer = next(item for item in relisted.json() if item["invocation_name"] == "writer")
        assert writer["enabled"] is False

        marketplace = await client.get("/skills/marketplace", params={"workspace_root": str(workspace)})
        assert marketplace.status_code == 200
        assert any(item["id"] == "code-review" for item in marketplace.json())

        installed = await client.post(
            "/skills/marketplace/code-review/install",
            params={"workspace_root": str(workspace)},
        )
        assert installed.status_code == 200
        assert installed.json()["item"]["installed"] is True
        assert (home / ".personagent" / "skills" / "code-review" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_chat_commands_hide_disabled_skills(monkeypatch, tmp_path):
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(workspace, "reviewer", "Review code")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PERSONAGENT_SKILL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(chat, "get_container", lambda: FakeContainer(workspace))

    app = FastAPI()
    app.include_router(chat.router)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        visible = await client.get("/chat/commands", params={"workspace_root": str(workspace)})
        assert visible.status_code == 200
        assert [item["slash_name"] for item in visible.json()] == ["/reviewer"]

        set_skill_activation("reviewer", False)
        visible = await client.get("/chat/commands", params={"workspace_root": str(workspace)})
        assert visible.status_code == 200
        assert visible.json() == []
