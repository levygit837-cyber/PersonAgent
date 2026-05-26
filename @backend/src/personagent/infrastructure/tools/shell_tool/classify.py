"""Shell command classification and parsing utilities."""

from __future__ import annotations

import shlex

_READ_ONLY_COMMANDS = {
    "cat",
    "du",
    "echo",
    "file",
    "find",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "sort",
    "stat",
    "tail",
    "tree",
    "wc",
    "whereis",
    "which",
}
_READ_ONLY_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
}
_SHELL_META_TOKENS = ("|", ">", "<", ";", "&&", "||", "$(", "`", "\n")
_WRITE_ALLOWED_MODES = {"accept_edits", "full", "bypass", "dont_ask"}
_READ_ONLY_MODES = {"read_only", "readonly"}
_CRITICAL_PATTERNS = (
    "rm -rf /",
    "rm -rf -- /",
    "sudo ",
    "su ",
    "mkfs",
    "dd ",
    "mount ",
    "umount ",
    "shutdown",
    "reboot",
    "systemctl ",
    "chmod -R 777 /",
    "chown -R ",
    ":(){",
)


def classify_read_only_shell(command: str) -> tuple[bool, str]:
    """Classifica comandos simples como read-only ou bloqueados.

    Permite pipes entre comandos read-only seguros (ex: find ... | head).
    """
    stripped = command.strip()
    if not stripped:
        return False, "Empty command."

    # Check for dangerous shell meta tokens (excluding |, && and || which we handle specially)
    dangerous_tokens = (">", "<", ";", "$(", "`", "\n")
    if any(token in stripped for token in dangerous_tokens) or _has_shell_expansion(
        stripped
    ):
        return False, "Shell operators, redirects and substitutions are not allowed."

    if _has_unquoted_control_operator(stripped):
        return _classify_shell_chain(stripped)

    # Handle pipes specially - allow safe read-only pipe chains
    if _has_unquoted_pipe(stripped):
        return _classify_pipe_command(stripped)

    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return False, f"Cannot parse command: {exc}"
    if not argv:
        return False, "Empty command."

    return _classify_single_command(argv)


def critical_shell_command_reason(command: str) -> str | None:
    """Return a hard-deny reason for commands that should never be approved."""
    normalized = " ".join(command.strip().split())
    lowered = normalized.lower()
    for pattern in _CRITICAL_PATTERNS:
        if pattern in lowered:
            return f"critical pattern matched: {pattern.strip()}"
    if lowered.startswith("rm -rf /") or lowered.startswith("rm -fr /"):
        return "recursive removal from filesystem root"
    if "curl " in lowered and " | sh" in lowered:
        return "remote shell installer pattern"
    if "wget " in lowered and " | sh" in lowered:
        return "remote shell installer pattern"
    return None


def _matches_explicit_shell_allow(command: str, context) -> bool:

    rules = context.permissions.get("shell_execute") or context.permissions.get(
        "shell_allow_patterns"
    )
    if not isinstance(rules, list):
        return False
    stripped = command.strip()
    for raw_rule in rules:
        rule = str(raw_rule).strip()
        if not rule:
            continue
        if rule.endswith("*") and stripped.startswith(rule[:-1]):
            return True
        if stripped == rule:
            return True
    return False


def _classify_shell_chain(command: str) -> tuple[bool, str]:
    """Classifica cadeias read-only separadas por && ou ||."""
    parts = _split_shell_chain(command)
    if len(parts) < 2:
        return False, "Invalid shell chain syntax."

    for part in parts:
        if part in {"&&", "||"}:
            continue
        if not part:
            return False, "Empty command in shell chain."
        allowed, reason = (
            _classify_pipe_command(part)
            if _has_unquoted_pipe(part)
            else _classify_simple_part(part)
        )
        if not allowed:
            return False, f"Shell chain segment blocked: {reason}"

    return True, "Command chain classified as read-only."


def _classify_simple_part(command: str) -> tuple[bool, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"Cannot parse command: {exc}"
    if not argv:
        return False, "Empty command."
    return _classify_single_command(argv)


def _classify_pipe_command(command: str) -> tuple[bool, str]:
    """Classifica comandos com pipes permitindo apenas chains read-only seguras."""
    parts = _split_unquoted(command, "|")

    if len(parts) < 2:
        return False, "Invalid pipe syntax."

    # Validate each command in the pipe chain
    for part in parts:
        if not part:
            return False, "Empty command in pipe chain."
        try:
            argv = shlex.split(part)
        except ValueError as exc:
            return False, f"Cannot parse command in pipe: {exc}"
        if not argv:
            return False, "Empty command in pipe chain."

        allowed, reason = _classify_single_command(argv, allow_pipe_output=True)
        if not allowed:
            return False, f"Pipe segment blocked: {reason}"

    return True, "Command chain classified as read-only."


def _split_shell_chain(command: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    length = len(command)

    while index < length:
        char = command[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            index += 1
            continue
        if char in "\"'":
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            current.append(char)
            index += 1
            continue
        if quote is None and command[index : index + 2] in {"&&", "||"}:
            parts.append("".join(current).strip())
            parts.append(command[index : index + 2])
            current = []
            index += 2
            continue
        current.append(char)
        index += 1

    parts.append("".join(current).strip())
    return parts


def _split_unquoted(command: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False

    for char in command:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char in "\"'":
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            current.append(char)
            continue
        if quote is None and char == separator:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)

    parts.append("".join(current).strip())
    return parts


def _has_unquoted_control_operator(command: str) -> bool:
    return any(part in {"&&", "||"} for part in _split_shell_chain(command))


def _has_unquoted_pipe(command: str) -> bool:
    return len(_split_unquoted(command, "|")) > 1


def _has_shell_expansion(command: str) -> bool:
    """Detecta expansões que podem contornar a validação estática de paths."""
    quote: str | None = None
    escaped = False
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char in "\"'":
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            index += 1
            continue
        if quote != "'" and char == "$":
            return True
        if quote is None and command[index : index + 2] == "&&":
            index += 2
            continue
        if quote is None and char in {"&", "{", "}"}:
            return True
        index += 1
    return False


def _classify_single_command(
    argv: list[str], allow_pipe_output: bool = False
) -> tuple[bool, str]:
    """Classifica um único comando (sem pipes)."""
    base = argv[0]
    if base not in _READ_ONLY_COMMANDS:
        return False, f"Command '{base}' is not in the read-only allowlist."

    if base == "git":
        if len(argv) < 2:
            return False, "git requires a read-only subcommand."
        subcommand = argv[1]
        if subcommand not in _READ_ONLY_GIT_SUBCOMMANDS:
            return False, f"git {subcommand} is not in the read-only allowlist."

    if base == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in argv):
        return False, "sed -i mutates files."

    if base == "find":
        blocked_find_flags = {
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fls",
            "-fprint",
            "-fprintf",
        }
        for arg in argv:
            if arg in blocked_find_flags:
                return False, f"find {arg} may mutate files or run commands."

    if base == "head":
        # head is safe as pipe output, but also check for file arguments
        pass

    if base == "tail" and "-F" in argv:
        return False, "tail -F (follow with retry) is not allowed."

    if base == "wc":
        # wc is safe for counting
        pass

    return True, "Command classified as read-only."
