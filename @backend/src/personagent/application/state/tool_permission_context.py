"""Tool permission context.

Expande o ToolUseContext existente com contexto de aplicação
para validação mais rica de permissões de ferramentas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personagent.domain.tools import ToolUseContext


@dataclass(slots=True)
class ToolPermissionContext:
    """Contexto expandido para validação de permissões de ferramentas.

    Combina o ToolUseContext do domínio com contexto de aplicação
    para permitir validações mais sofisticadas.
    """

    base_context: ToolUseContext
    app_state: dict[str, Any]
    system_context: dict[str, Any]
    user_context: dict[str, Any]
    tool_name: str
    tool_arguments: dict[str, Any]

    @classmethod
    def from_tool_use_context(
        cls,
        tool_use_context: ToolUseContext,
        app_state: dict[str, Any],
        system_context: dict[str, Any],
        user_context: dict[str, Any],
        tool_name: str,
        tool_arguments: dict[str, Any],
    ) -> ToolPermissionContext:
        """Cria um ToolPermissionContext a partir de um ToolUseContext.

        Args:
            tool_use_context: Contexto base do domínio.
            app_state: Estado da aplicação.
            system_context: Contexto de sistema.
            user_context: Contexto de usuário.
            tool_name: Nome da ferramenta.
            tool_arguments: Argumentos da ferramenta.

        Returns:
            ToolPermissionContext expandido.
        """
        return cls(
            base_context=tool_use_context,
            app_state=app_state,
            system_context=system_context,
            user_context=user_context,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    @property
    def conversation_id(self) -> str:
        """Retorna o ID da conversa."""
        return str(self.base_context.conversation_id)

    @property
    def workspace_root(self) -> Path:
        """Retorna o diretório raiz do workspace."""
        return self.base_context.workspace_root

    @property
    def cwd(self) -> Path:
        """Retorna o diretório de trabalho atual."""
        return self.base_context.cwd

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        """Retorna os diretórios permitidos."""
        return self.base_context.allowed_roots

    @property
    def permission_mode(self) -> str:
        """Retorna o modo de permissão."""
        return str(self.app_state.get("permission_mode", "manual"))

    @property
    def is_git_repo(self) -> bool:
        """Retorna se é um repositório Git."""
        return bool(self.system_context.get("is_git_repo", False))

    @property
    def git_branch(self) -> str | None:
        """Retorna o branch Git atual."""
        return self.system_context.get("git_branch")

    @property
    def has_claude_md(self) -> bool:
        """Retorna se há persona.md."""
        return bool(self.user_context.get("claude_md"))

    def is_tool_allowed(self) -> bool:
        """Verifica se a ferramenta está na allowlist."""
        allowed_tools = self.app_state.get("allowed_tools", set())
        return self.tool_name in allowed_tools

    def get_tool_permission(self) -> str:
        """Retorna a permissão específica da ferramenta."""
        tool_permissions = self.app_state.get("tool_permissions", {})
        return str(tool_permissions.get(self.tool_name, "ask"))

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário."""
        return {
            "conversation_id": self.conversation_id,
            "workspace_root": str(self.workspace_root),
            "cwd": str(self.cwd),
            "allowed_roots": [str(r) for r in self.allowed_roots],
            "permission_mode": self.permission_mode,
            "is_git_repo": self.is_git_repo,
            "git_branch": self.git_branch,
            "has_claude_md": self.has_claude_md,
            "tool_name": self.tool_name,
            "tool_allowed": self.is_tool_allowed(),
            "tool_permission": self.get_tool_permission(),
        }
