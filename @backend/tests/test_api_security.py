from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from personagent.infrastructure.config.settings import get_settings
from personagent.interfaces.api.main import create_app
from personagent.interfaces.api.routes import security as security_routes
from personagent.interfaces.api.security import (
    install_local_auth,
    read_or_create_local_token,
    validate_startup_security,
)


@pytest.mark.asyncio
async def test_protected_api_requires_local_token() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/workspace/projects")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_protected_api_accepts_valid_local_token() -> None:
    app = create_app()
    token = read_or_create_local_token(
        Path(get_settings().personagent_local_auth_token_path).expanduser()
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-PersonAgent-Client": "desktop-electron",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/workspace/projects", headers=headers)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_protected_api_accepts_configured_permanent_local_token(tmp_path) -> None:
    class Settings:
        app_env = "development"
        personagent_local_auth_enabled = True
        personagent_local_auth_token = "local-dev-token"
        personagent_local_auth_token_path = str(tmp_path / "local_auth_token")
        personagent_cors_allowed_origins = None

    from fastapi import FastAPI

    app = FastAPI()
    install_local_auth(app, Settings())

    @app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    headers = {
        "Authorization": "Bearer local-dev-token",
        "X-PersonAgent-Client": "desktop-electron",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/protected", headers=headers)

    assert response.status_code == 200
    assert (tmp_path / "local_auth_token").read_text(encoding="utf-8").strip() == "local-dev-token"


@pytest.mark.asyncio
async def test_action_approval_route_does_not_mint_approvals() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(security_routes.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/security/action-approvals",
            json={"action_kind": "workspace.git_push", "arguments": {"workspace_root": "/tmp/repo"}},
        )

    assert response.status_code == 403
    assert "desktop confirmation" in response.json()["detail"]


def test_weak_postgres_password_is_rejected_outside_development() -> None:
    class Settings:
        app_env = "production"
        secret_key = "production-secret"
        postgres_password = "personagent_secret"

    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        validate_startup_security(Settings())
