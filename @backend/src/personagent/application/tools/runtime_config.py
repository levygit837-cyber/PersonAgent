"""Configuração do runtime de ferramentas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from personagent.infrastructure.artifacts import DEFAULT_ARTIFACT_ROOT

DEFAULT_MAX_TOOL_ITERATIONS: int | None = None
"""Default operator-imposed tool iteration limit.

``None`` means the operator does not enforce a cap; the chat loop still applies
``SAFETY_TOOL_ITERATION_CEILING`` to prevent runaway iterations when neither the
operator nor the request supplies a value.
"""

SAFETY_TOOL_ITERATION_CEILING: int = 50
"""Hard ceiling enforced by the chat completion loop when no other cap is set.

This exists so that a model that keeps emitting tool calls cannot loop
indefinitely. Explicit ``max_tool_iterations`` values on the request or runtime
config take precedence over this fallback.
"""


def resolve_effective_tool_iterations(
    *,
    request_max: int | None,
    config_max: int | None,
    safety_ceiling: int = SAFETY_TOOL_ITERATION_CEILING,
) -> int:
    """Pick the effective tool iteration cap for a chat turn.

    Priority: explicit request value > operator-imposed config value > safety
    ceiling. The result is always a positive integer to guarantee the loop is
    bounded.
    """

    for candidate in (request_max, config_max):
        if candidate is None:
            continue
        bounded = max(1, int(candidate))
        return bounded
    return max(1, int(safety_ceiling))


@dataclass(frozen=True, slots=True)
class ToolRuntimeConfig:
    """Limites e diretórios usados pela execução de ferramentas."""

    workspace_root: Path
    allowed_roots: tuple[Path, ...]
    max_tool_iterations: int | None = DEFAULT_MAX_TOOL_ITERATIONS
    max_concurrency: int = 4
    read_max_bytes: int = 10_000_000
    read_default_limit: int = 10_000
    read_max_lines: int = 100_000
    search_timeout_ms: int = 15_000
    shell_timeout_ms: int = 10_000
    web_timeout_ms: int = 15_000
    web_max_bytes: int = 10_000_000
    result_max_chars: int | None = None
    tool_result_storage_root: Path | None = DEFAULT_ARTIFACT_ROOT
    web_allowed_domains: tuple[str, ...] = ()
    web_blocked_domains: tuple[str, ...] = ("localhost", "127.0.0.1", "0.0.0.0")
    web_allow_private_hosts: bool = False
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
        read_max_bytes: int = 10_000_000,
        read_default_limit: int = 10_000,
        read_max_lines: int = 100_000,
        search_timeout_ms: int = 15_000,
        shell_timeout_ms: int = 10_000,
        web_timeout_ms: int = 15_000,
        web_max_bytes: int = 10_000_000,
        result_max_chars: int | None = None,
        tool_result_storage_root: str | Path | None = None,
        web_allowed_domains: list[str] | tuple[str, ...] | None = None,
        web_blocked_domains: list[str] | tuple[str, ...] | None = None,
        web_allow_private_hosts: bool = False,
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
            result_max_chars=_optional_positive_int(result_max_chars),
            tool_result_storage_root=(
                Path(tool_result_storage_root).expanduser().resolve()
                if tool_result_storage_root
                else DEFAULT_ARTIFACT_ROOT.expanduser().resolve()
            ),
            web_allowed_domains=tuple(item.lower() for item in (web_allowed_domains or ())),
            web_blocked_domains=tuple(
                item.lower()
                for item in (
                    web_blocked_domains
                    if web_blocked_domains is not None
                    else ("localhost", "127.0.0.1", "0.0.0.0")
                )
            ),
            web_allow_private_hosts=bool(web_allow_private_hosts),
            skill_roots=tuple(Path(path).expanduser().resolve() for path in (skill_roots or ())),
            lsp_enabled=bool(lsp_enabled),
        )


def _bounded_tool_iterations(value: int | None) -> int | None:
    if value is None:
        return None
    return max(1, int(value))


def _optional_positive_int(value: int | None) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    if parsed <= 0:
        return None
    return parsed


__all__ = [
    "DEFAULT_MAX_TOOL_ITERATIONS",
    "SAFETY_TOOL_ITERATION_CEILING",
    "ToolRuntimeConfig",
    "resolve_effective_tool_iterations",
]
