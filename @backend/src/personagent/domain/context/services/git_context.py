"""Git context service.

Este serviço coleta informações do repositório Git relevantes para o contexto
do agente, como branch atual, status, commits recentes, etc.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GitInfo:
    """Informações sobre o repositório Git."""

    is_git_repo: bool = False
    branch: str | None = None
    remote: str | None = None
    commit: str | None = None
    commit_message: str | None = None
    author: str | None = None
    is_dirty: bool = False
    staged_files: tuple[str, ...] = ()
    unstaged_files: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()
    root: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário."""
        return {
            "is_git_repo": self.is_git_repo,
            "branch": self.branch,
            "remote": self.remote,
            "commit": self.commit,
            "commit_message": self.commit_message,
            "author": self.author,
            "is_dirty": self.is_dirty,
            "staged_files": list(self.staged_files),
            "unstaged_files": list(self.unstaged_files),
            "untracked_files": list(self.untracked_files),
            "root": self.root,
        }


class GitContextService:
    """Serviço para coletar contexto do Git."""

    def __init__(self, workspace_root: str | Path) -> None:
        """Inicializa o serviço.

        Args:
            workspace_root: Diretório raiz do workspace.
        """
        self._workspace_root = Path(workspace_root).expanduser().resolve()

    def get_git_info(self) -> GitInfo:
        """Coleta informações do repositório Git.

        Returns:
            GitInfo com as informações coletadas.
        """
        if not self._is_git_repo():
            return GitInfo()

        branch = self._get_branch()
        remote = self._get_remote()
        commit = self._get_commit()
        commit_message = self._get_commit_message()
        author = self._get_author()
        is_dirty = self._is_dirty()
        staged_files = self._get_staged_files()
        unstaged_files = self._get_unstaged_files()
        untracked_files = self._get_untracked_files()
        root = self._get_git_root()

        return GitInfo(
            is_git_repo=True,
            branch=branch,
            remote=remote,
            commit=commit,
            commit_message=commit_message,
            author=author,
            is_dirty=is_dirty,
            staged_files=tuple(staged_files),
            unstaged_files=tuple(unstaged_files),
            untracked_files=tuple(untracked_files),
            root=str(root),
        )

    def _is_git_repo(self) -> bool:
        """Verifica se o workspace é um repositório Git."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _get_git_root(self) -> Path:
        """Retorna o diretório raiz do repositório Git."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return self._workspace_root

    def _get_branch(self) -> str | None:
        """Retorna o branch atual."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _get_remote(self) -> str | None:
        """Retorna o remote do branch atual."""
        try:
            branch = self._get_branch()
            if not branch:
                return None

            result = subprocess.run(
                ["git", "config", f"branch.{branch}.remote"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _get_commit(self) -> str | None:
        """Retorna o hash do commit atual."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _get_commit_message(self) -> str | None:
        """Retorna a mensagem do commit atual."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--pretty=%B"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                message = result.stdout.strip()
                return message[:200] if message else None  # Limitar tamanho
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _get_author(self) -> str | None:
        """Retorna o autor do commit atual."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--pretty=%an"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None

    def _is_dirty(self) -> bool:
        """Verifica se há mudanças não commitadas."""
        try:
            result = subprocess.run(
                ["git", "diff", "--quiet"],
                cwd=self._workspace_root,
                capture_output=True,
                timeout=5,
            )
            return result.returncode != 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _get_staged_files(self) -> list[str]:
        """Retorna lista de arquivos staged."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return []

    def _get_unstaged_files(self) -> list[str]:
        """Retorna lista de arquivos unstaged."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return []

    def _get_untracked_files(self) -> list[str]:
        """Retorna lista de arquivos untracked."""
        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                files = result.stdout.strip().split("\n") if result.stdout.strip() else []
                # Limitar número de arquivos
                return files[:50]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return []
