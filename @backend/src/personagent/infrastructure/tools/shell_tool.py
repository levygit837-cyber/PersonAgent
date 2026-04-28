"""Ferramenta shell com política read-only conservadora."""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil

from personagent.domain.exceptions import ShellCommandFailedError, ShellTimeoutError
from personagent.domain.tools import (
    Tool,
    ToolArguments,
    ToolCall,
    ToolDefinition,
    ToolExecutionStatus,
    ToolGroup,
    ToolPermissionBehavior,
    ToolPermissionResult,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    build_tool,
)
from personagent.infrastructure.tools.path_safety import resolve_within_allowed_roots

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


def create_shell_tool() -> Tool:
    """Cria a ferramenta shell."""

    async def validate(
        arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.DENY,
                message="shell requires a non-empty 'command' string.",
            )
        cwd = arguments.get("cwd")
        if cwd is not None:
            try:
                resolved = resolve_within_allowed_roots(str(cwd), context)
            except ValueError as exc:
                return ToolPermissionResult(
                    behavior=ToolPermissionBehavior.DENY,
                    message=str(exc),
                )
            if not resolved.is_dir():
                return ToolPermissionResult(
                    behavior=ToolPermissionBehavior.DENY,
                    message=f"cwd is not a directory: {cwd}",
                )
        return None

    async def check_permissions(
        arguments: ToolArguments,
        context: ToolUseContext,
    ) -> ToolPermissionResult:
        command = str(arguments.get("command") or "")
        critical_reason = critical_shell_command_reason(command)
        if critical_reason:
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.DENY,
                message=f"shell command denied: {critical_reason}",
                metadata={"classifier": "shell_safety_v2", "reason": critical_reason},
            )

        read_only, reason = classify_read_only_shell(command)
        if read_only:
            in_scope, scope_reason = validate_shell_path_scope(command, context)
            if in_scope:
                return ToolPermissionResult(
                    behavior=ToolPermissionBehavior.ALLOW,
                    updated_input=arguments,
                    metadata={"classifier": "shell_safety_v2", "mode": "read_only"},
                )
            reason = scope_reason

        mode = str(context.permissions.get("mode") or "manual").strip().lower()
        if mode in _READ_ONLY_MODES:
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.DENY,
                message=f"shell command denied in read-only mode. {reason}",
                metadata={"classifier": "shell_safety_v2", "reason": reason, "mode": mode},
            )

        if _matches_explicit_shell_allow(command, context) or mode in _WRITE_ALLOWED_MODES:
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.ALLOW,
                updated_input=arguments,
                metadata={"classifier": "shell_safety_v2", "mode": mode},
            )

        return ToolPermissionResult(
            behavior=ToolPermissionBehavior.ASK,
            message=(
                f"permission_required: shell command may modify state or access paths outside "
                f"the current workspace. {reason}"
            ),
            metadata={"classifier": "shell_safety_v2", "reason": reason, "mode": mode},
        )

    async def handler(
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        command = str(arguments["command"])
        shell = shutil.which("bash") or shutil.which("sh")
        if shell is None:
            return ToolResult(
                tool_call_id=call.id,
                tool_name="shell",
                content="Command not found: bash or sh",
                status=ToolExecutionStatus.ERROR,
                is_error=True,
            )

        cwd = resolve_within_allowed_roots(
            str(arguments.get("cwd") or "."),
            context,
        )
        timeout_ms = _bounded_timeout(
            arguments.get("timeout_ms"),
            default=int(context.limits.get("shell_timeout_ms", 10_000)),
        )
        max_chars = int(context.limits.get("result_max_chars", 20_000))

        await context.emit_progress(
            ToolProgress(
                tool_call_id=call.id,
                tool_name="shell",
                status=ToolExecutionStatus.RUNNING,
                message="Running...",
                data={"command": command, "cwd": str(cwd)},
            )
        )

        shell_args = (
            [shell, "-o", "pipefail", "-c", command]
            if shell.endswith("bash")
            else [shell, "-c", command]
        )
        process = await asyncio.create_subprocess_exec(
            *shell_args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        output = _cap_output(
            "\n".join(
                part
                for part in (
                    stdout_text.rstrip(),
                    stderr_text.rstrip(),
                )
                if part
            ),
            max_chars,
        )
        data = {
            "type": "shell",
            "command": command,
            "cwd": str(cwd),
            "stdout": _cap_output(stdout_text, max_chars),
            "stderr": _cap_output(stderr_text, max_chars),
            "return_code": process.returncode,
            "timed_out": timed_out,
            "content": output or "(No output)",
        }
        status = (
            ToolExecutionStatus.ERROR
            if timed_out or (process.returncode not in (0, None))
            else ToolExecutionStatus.COMPLETED
        )
        metadata = {}
        if timed_out:
            metadata["error"] = ShellTimeoutError(
                f"Shell command timed out after {timeout_ms}ms.",
                metadata={
                    "command": command,
                    "cwd": str(cwd),
                    "timeout_ms": timeout_ms,
                },
            ).to_envelope()
        elif status == ToolExecutionStatus.ERROR:
            metadata["error"] = ShellCommandFailedError(
                f"Shell command exited with code {process.returncode}.",
                metadata={
                    "command": command,
                    "cwd": str(cwd),
                    "return_code": process.returncode,
                },
            ).to_envelope()
        return ToolResult(
            tool_call_id=call.id,
            tool_name="shell",
            content=json.dumps(data, ensure_ascii=False),
            status=status,
            is_error=status == ToolExecutionStatus.ERROR,
            data=data,
            metadata=metadata,
        )

    return build_tool(
        definition=ToolDefinition(
            name="shell",
            description=(
                "Run a shell command in the workspace. Safe read-only commands auto-run; "
                "write/exec/network commands require permission unless permission mode or "
                "explicit shell rules allow them. Critical commands are denied."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional workspace-relative working directory.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 60000,
                        "description": "Execution timeout in milliseconds.",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            metadata={"category": "shell", "read_only_policy": "v2"},
            group=ToolGroup.SHELL.value,
            search_hint="shell bash command terminal read-only",
            max_result_size_chars=20_000,
            is_read_only=False,
        ),
        handler=handler,
        is_concurrency_safe=lambda args: classify_read_only_shell(str(args.get("command") or ""))[
            0
        ],
        is_read_only=lambda args: classify_read_only_shell(str(args.get("command") or ""))[0],
        validate_input=validate,
        check_permissions=check_permissions,
        to_auto_classifier_input=lambda args: args.get("command", ""),
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
    if any(token in stripped for token in dangerous_tokens) or _has_shell_expansion(stripped):
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


def _matches_explicit_shell_allow(command: str, context: ToolUseContext) -> bool:
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
            _classify_pipe_command(part) if _has_unquoted_pipe(part) else _classify_simple_part(part)
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


def _classify_single_command(argv: list[str], allow_pipe_output: bool = False) -> tuple[bool, str]:
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


def _validate_pipe_path_scope(command: str, context: ToolUseContext) -> tuple[bool, str]:
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
    command: str, context: ToolUseContext
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


def validate_shell_path_scope(command: str, context: ToolUseContext) -> tuple[bool, str]:
    """Garante que argumentos de path do shell fiquem dentro dos roots permitidos."""
    if _has_unquoted_control_operator(command):
        return _validate_shell_chain_path_scope(command, context)

    # Handle pipe commands specially
    if _has_unquoted_pipe(command):
        return _validate_pipe_path_scope(command, context)

    return _validate_single_path_scope(command, context)


def _validate_single_path_scope(command: str, context: ToolUseContext) -> tuple[bool, str]:
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
        positionals = _positionals(args, value_options={"-e", "--expression", "-f", "--file"})
        return positionals[1:]
    return []


def _positionals(args: list[str], value_options: set[str] | None = None) -> list[str]:
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


def _bounded_timeout(value: object, *, default: int) -> int:
    try:
        if value is None:
            timeout = default
        elif isinstance(value, int | float | str | bytes | bytearray):
            timeout = int(value)
        else:
            timeout = default
    except (TypeError, ValueError):
        timeout = default
    return max(1, min(timeout, 60_000))


def _cap_output(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n[Output truncated.]"
