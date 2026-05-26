"""Propriedades computadas do Settings."""

import json
from pathlib import Path
from typing import Any

from ._core import _split_csv, get_project_root


class SettingsPropertiesMixin:
    """Mixin com propriedades computadas de Settings."""

    @property
    def db_url(self) -> str:
        """Retorna a URL de conexão com o banco de dados."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def tool_workspace_root_path(self) -> Path:
        """Retorna o root padrão para ferramentas."""
        if self.tools_workspace_root:
            return Path(self.tools_workspace_root).expanduser()
        return get_project_root()

    @property
    def tool_allowed_root_paths(self) -> list[Path]:
        """Retorna roots permitidos para ferramentas."""
        if not self.tools_allowed_roots:
            return [self.tool_workspace_root_path]
        return [
            Path(item.strip()).expanduser()
            for item in self.tools_allowed_roots.split(",")
            if item.strip()
        ]

    @property
    def tool_web_allowed_domain_list(self) -> list[str]:
        return _split_csv(self.tools_web_allowed_domains)

    @property
    def tool_web_blocked_domain_list(self) -> list[str]:
        return _split_csv(self.tools_web_blocked_domains)

    @property
    def tool_skill_root_paths(self) -> list[Path]:
        return [Path(item).expanduser() for item in _split_csv(self.tools_skill_roots)]

    @property
    def prompt_command_root_paths(self) -> list[Path]:
        return [Path(item).expanduser() for item in _split_csv(self.prompt_command_roots)]

    @property
    def tool_mcp_server_configs(self) -> list[dict[str, Any]]:
        if not self.tools_mcp_servers_json:
            return []
        try:
            raw = json.loads(self.tools_mcp_servers_json)
        except json.JSONDecodeError:
            return []
        if isinstance(raw, dict):
            raw = raw.get("servers", [])
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]
