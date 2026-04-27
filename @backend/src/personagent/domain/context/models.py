"""Context domain models.

Este módulo define as entidades puras de contexto usadas pelo PersonAgent.
Seguindo os princípios da Arquitetura Clean, estas entidades não dependem
de infraestrutura (filesystem, banco, APIs externas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryFile:
    """Arquivo de memória (persona.md) carregado.

    Representa um arquivo de instruções/contexto carregado do sistema de arquivos.
    A prioridade determina a ordem de injeção no prompt (maior = mais recente).
    """

    path: Path
    content: str
    priority: int  # 1=managed, 2=user, 3=project, 4=local
    is_injected: bool = False

    @classmethod
    def create(
        cls,
        path: Path,
        content: str,
        priority: int,
        is_injected: bool = False,
    ) -> MemoryFile:
        """Cria uma instância de MemoryFile validando os inputs."""
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        if not isinstance(priority, int) or priority < 1 or priority > 4:
            raise ValueError("priority must be an integer between 1 and 4")
        return cls(
            path=Path(path).expanduser().resolve(),
            content=content,
            priority=priority,
            is_injected=is_injected,
        )


@dataclass(frozen=True, slots=True)
class SystemContext:
    """Contexto de sistema (git, environment, workspace, etc.).

    Contém informações sobre o ambiente de execução que são relevantes
    para o agente, mas não específicas ao usuário.
    """

    git_status: dict[str, Any] | None = None
    git_branch: str | None = None
    git_remote: str | None = None
    git_commit: str | None = None
    workspace_root: str = ""
    cwd: str = ""
    environment: dict[str, str] = field(default_factory=dict)
    cache_breaker: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def with_cache_breaker(self, breaker: str) -> SystemContext:
        """Retorna uma cópia com um cache breaker."""
        return type(self)(
            git_status=self.git_status,
            git_branch=self.git_branch,
            git_remote=self.git_remote,
            git_commit=self.git_commit,
            workspace_root=self.workspace_root,
            cwd=self.cwd,
            environment=self.environment,
            cache_breaker=breaker,
            timestamp=self.timestamp,
        )


@dataclass(frozen=True, slots=True)
class UserContext:
    """Contexto do usuário (persona.md, date, settings, etc.).

    Contém informações específicas do usuário e do projeto atual,
    incluindo arquivos de memória e configurações personalizadas.
    """

    claude_md: str | None = None
    memory_files: tuple[MemoryFile, ...] = ()
    current_date: str = ""
    user_settings: dict[str, Any] = field(default_factory=dict)
    project_config: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_claude_md(self) -> bool:
        """Retorna True se há conteúdo persona.md."""
        return bool(self.claude_md and self.claude_md.strip())

    @property
    def has_memory_files(self) -> bool:
        """Retorna True se há arquivos de memória."""
        return len(self.memory_files) > 0

    def with_memory_files(self, files: list[MemoryFile]) -> UserContext:
        """Retorna uma cópia com novos arquivos de memória."""
        return type(self)(
            claude_md=self.claude_md,
            memory_files=tuple(files),
            current_date=self.current_date,
            user_settings=self.user_settings,
            project_config=self.project_config,
            timestamp=self.timestamp,
        )


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    """Resultado completo da montagem de contexto."""

    system_context: SystemContext
    user_context: UserContext
    build_duration_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_context_size(self) -> int:
        """Retorna o tamanho total do contexto em caracteres."""
        import dataclasses

        system_size = len(str(dataclasses.asdict(self.system_context)))
        user_size = len(self.user_context.claude_md or "")
        memory_size = sum(len(f.content) for f in self.user_context.memory_files)
        return system_size + user_size + memory_size
