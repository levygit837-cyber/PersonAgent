"""Shell tool factory."""

from __future__ import annotations

import asyncio
import json
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
from personagent.infrastructure.tools.shell_tool.classify import (
    _READ_ONLY_MODES,
    _WRITE_ALLOWED_MODES,
    classify_read_only_shell,
    critical_shell_command_reason,
)
from personagent.infrastructure.tools.shell_tool.validate import validate_shell_path_scope


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

        from personagent.infrastructure.tools.shell_tool.classify import (
            _matches_explicit_shell_allow,
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
        raw_max_chars = context.limits.get("result_max_chars")
        max_chars = int(raw_max_chars) if raw_max_chars is not None else None

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
        is_concurrency_safe=lambda args: classify_read_only_shell(
            str(args.get("command") or "")
        )[0],
        is_read_only=lambda args: classify_read_only_shell(
            str(args.get("command") or "")
        )[0],
        validate_input=validate,
        check_permissions=check_permissions,
        to_auto_classifier_input=lambda args: args.get("command", ""),
    )


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


def _cap_output(value: str, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0:
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n[Output truncated.]"
