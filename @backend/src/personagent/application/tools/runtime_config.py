"""Configuração do runtime de ferramentas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_TOOL_ITERATIONS = 8
MAX_TOOL_ITERATIONS_HARD_CAP = 20


@dataclass(frozen=True, slots=True)
class ToolRuntimeConfig:
    """Limites e diretórios usados pela execução de ferramentas."""

    workspace_root: Path
    allowed_roots: tuple[Path, ...]
    max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS
    max_concurrency: int = 4
    read_max_bytes: int = 128_000
    read_default_limit: int = 1_000
    read_max_lines: int = 1_000
    search_timeout_ms: int = 15_000
    shell_timeout_ms: int = 10_000
    web_timeout_ms: int = 15_000
    web_max_bytes: int = 512_000
    result_max_chars: int = 20_000
    tool_result_storage_root: Path | None = None
    web_allowed_domains: tuple[str, ...] = ()
    web_blocked_domains: tuple[str, ...] = ("localhost", "127.0.0.1", "0.0.0.0")
    skill_roots: tuple[Path, ...] = ()
    lsp_enabled: bool = False

    @classmethod
    def from_values(
        cls,
        *,
        workspace_root: str | Path,
        allowed_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        max_tool_iterations: int | None = DEFAULT_MAX_TOOL_ITERATIONS,
        max_concurrency: int = 4,
        read_max_bytes: int = 128_000,
        read_default_limit: int = 1_000,
        read_max_lines: int = 1_000,
        search_timeout_ms: int = 15_000,
        shell_timeout_ms: int = 10_000,
        web_timeout_ms: int = 15_000,
        web_max_bytes: int = 512_000,
        result_max_chars: int = 20_000,
        tool_result_storage_root: str | Path | None = None,
        web_allowed_domains: list[str] | tuple[str, ...] | None = None,
        web_blocked_domains: list[str] | tuple[str, ...] | None = None,
        skill_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        lsp_enabled: bool = False,
    ) -> ToolRuntimeConfig:
        """Normaliza valores vindos de settings/env."""
        root = Path(workspace_root).expanduser().resolve()
        roots = tuple(Path(path).expanduser().resolve() for path in (allowed_roots or (root,)))
        return cls(
            workspace_root=root,
            allowed_roots=roots,
            max_tool_iterations=_bounded_tool_iterations(max_tool_iterations),
            max_concurrency=max(1, max_concurrency),
            read_max_bytes=max(1, read_max_bytes),
            read_default_limit=max(1, read_default_limit),
            read_max_lines=max(1, read_max_lines),
            search_timeout_ms=max(1, search_timeout_ms),
            shell_timeout_ms=max(1, shell_timeout_ms),
            web_timeout_ms=max(1, web_timeout_ms),
            web_max_bytes=max(1, web_max_bytes),
            result_max_chars=max(1, result_max_chars),
            tool_result_storage_root=(
                Path(tool_result_storage_root).expanduser().resolve()
                if tool_result_storage_root
                else None
            ),
            web_allowed_domains=tuple(item.lower() for item in (web_allowed_domains or ())),
            web_blocked_domains=tuple(
                item.lower()
                for item in (web_blocked_domains or ("localhost", "127.0.0.1", "0.0.0.0"))
            ),
            skill_roots=tuple(Path(path).expanduser().resolve() for path in (skill_roots or ())),
            lsp_enabled=bool(lsp_enabled),
        )


def _bounded_tool_iterations(value: int | None) -> int:
    if value is None:
        return DEFAULT_MAX_TOOL_ITERATIONS
    return min(MAX_TOOL_ITERATIONS_HARD_CAP, max(1, int(value)))


__all__ = ["DEFAULT_MAX_TOOL_ITERATIONS", "MAX_TOOL_ITERATIONS_HARD_CAP", "ToolRuntimeConfig"]
