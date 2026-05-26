"""Shell command path validation utilities."""

from __future__ import annotations

import shlex

from personagent.infrastructure.tools.path_safety import resolve_within_allowed_roots
from personagent.infrastructure.tools.shell_tool.classify import (
    _has_unquoted_control_operator,
    _has_unquoted_pipe,
    _split_shell_chain,
    _split_unquoted,
)


def validate_shell_path_scope(command: str, context) -> tuple[bool, str]:
    """Garante que argumentos de path do shell fiquem dentro dos roots permitidos."""
    if _has_unquoted_control_operator(command):
        return _validate_shell_chain_path_scope(command, context)

    # Handle pipe commands specially
    if _has_unquoted_pipe(command):
        return _validate_pipe_path_scope(command, context)

    return _validate_single_path_scope(command, context)


def _validate_pipe_path_scope(command: str, context) -> tuple[bool, str]:
    """Valida paths em comandos com pipes - verifica todos os segmentos."""
    parts = _split_unquoted(command, "|")

    for part in parts:
        try:
            argv = shlex.split(part.strip())
        except ValueError:
            continue
        if not argv:
            continue

        for path_arg in _path_arguments(argv):
            if path_arg == "-":
                continue
            try:
                resolve_within_allowed_roots(path_arg, context)
            except ValueError:
                return False, f"Path argument is outside allowed roots: {path_arg}"

    return True, "Path arguments are inside allowed roots."


def _validate_shell_chain_path_scope(
    command: str, context
) -> tuple[bool, str]:
    """Valida paths em cadeias com &&/|| e pipes."""
    for part in _split_shell_chain(command):
        if part in {"&&", "||"}:
            continue
        if not part:
            return False, "Empty command in shell chain."
        allowed, reason = (
            _validate_pipe_path_scope(part, context)
            if _has_unquoted_pipe(part)
            else _validate_single_path_scope(part, context)
        )
        if not allowed:
            return False, reason
    return True, "Path arguments are inside allowed roots."


def _validate_single_path_scope(command: str, context) -> tuple[bool, str]:
    try:
        argv = shlex.split(command.strip())
    except ValueError as exc:
        return False, f"Cannot parse command: {exc}"
    if not argv:
        return False, "Empty command."

    for path_arg in _path_arguments(argv):
        if path_arg == "-":
            continue
        try:
            resolve_within_allowed_roots(path_arg, context)
        except ValueError:
            return False, f"Path argument is outside allowed roots: {path_arg}"
    return True, "Path arguments are inside allowed roots."


def _path_arguments(argv: list[str]) -> list[str]:
    base = argv[0]
    args = argv[1:]
    if base in {"cat", "du", "file", "ls", "stat", "tree", "wc"}:
        return _positionals(args)
    if base in {"head", "tail"}:
        return _positionals(args, value_options={"-n", "--lines", "-c", "--bytes"})
    if base == "find":
        result: list[str] = []
        for arg in args:
            if arg.startswith("-") or arg in {"(", ")", "!"}:
                break
            result.append(arg)
        return result or ["."]
    if base in {"grep", "rg"}:
        positionals = _positionals(
            args,
            value_options={
                "-A",
                "--after-context",
                "-B",
                "--before-context",
                "-C",
                "--context",
                "-e",
                "--regexp",
                "-f",
                "--file",
                "-g",
                "--glob",
                "-m",
                "--max-count",
                "--max-depth",
                "--max-columns",
            },
        )
        return positionals[1:]
    if base == "sed":
        positionals = _positionals(
            args, value_options={"-e", "--expression", "-f", "--file"}
        )
        return positionals[1:]
    return []


def _positionals(
    args: list[str], value_options: set[str] | None = None
) -> list[str]:
    value_options = value_options or set()
    positionals: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            positionals.extend(args[index + 1 :])
            break
        if arg in value_options:
            skip_next = True
            continue
        if arg.startswith("--") and "=" in arg:
            continue
        if arg.startswith("-"):
            continue
        positionals.append(arg)
    return positionals
