"""Markdown prompt commands and slash command expansion."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personagent.domain.prompts.frontmatter import (
    as_bool,
    as_string_list,
    parse_markdown_frontmatter,
)


@dataclass(frozen=True, slots=True)
class PromptCommand:
    """A user-invocable Markdown prompt command."""

    name: str
    body: str
    path: Path
    description: str = ""
    allowed_tools: tuple[str, ...] = ()
    model: str | None = None
    argument_hint: str | None = None
    disable_model_invocation: bool = False
    when_to_use: str | None = None
    context: str = "inline"
    effort: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def slash_name(self) -> str:
        return f"/{self.name}"

    def expand(self, raw_arguments: str) -> str:
        """Expand $ARGUMENTS, positional tokens, and named key=value tokens."""

        expanded = self.body.replace("$ARGUMENTS", raw_arguments)
        try:
            tokens = shlex.split(raw_arguments)
        except ValueError:
            tokens = raw_arguments.split()
        for index, value in enumerate(tokens, start=1):
            expanded = expanded.replace(f"${index}", value)
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                expanded = expanded.replace(f"${key}", value)
        return expanded.strip()

    def to_inventory_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slash_name": self.slash_name,
            "description": self.description,
            "argument_hint": self.argument_hint,
            "allowed_tools": list(self.allowed_tools),
            "model": self.model,
            "disable_model_invocation": self.disable_model_invocation,
            "when_to_use": self.when_to_use,
            "context": self.context,
            "effort": self.effort,
            "path": str(self.path),
        }


@dataclass(frozen=True, slots=True)
class SlashCommandResolution:
    """Resolved slash command content for prompt injection."""

    command: PromptCommand
    raw_arguments: str
    expanded_prompt: str

    def reminder(self) -> str:
        return (
            "# Slash Command Context\n\n"
            f"Command: {self.command.slash_name}\n"
            f"Arguments: {self.raw_arguments or '(none)'}\n"
            f"Source: {self.command.path}\n\n"
            "The user invoked a slash command. Treat the command content below as "
            "additional user intent for this turn, while preserving the live system "
            "prompt, tool policy, memory, and safety constraints.\n\n"
            f"{self.expanded_prompt}"
        )

    def metadata(self) -> dict[str, Any]:
        data = self.command.to_inventory_dict()
        data.update({"arguments": self.raw_arguments})
        return data


@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    """A local PersonAgent command with Claude-style slash invocation semantics."""

    name: str
    description: str
    argument_hint: str | None = None
    allowed_tools: tuple[str, ...] = ()
    model: str | None = None
    effort: str | None = None
    should_query: bool = True
    ui_action: str | None = None

    @property
    def slash_name(self) -> str:
        return f"/{self.name}"

    @property
    def path(self) -> str:
        return f"builtin:{self.name}"

    def reminder(self, raw_arguments: str) -> str:
        query_policy = (
            "This command should continue through the model for this turn."
            if self.should_query
            else "This command is primarily a local UI/runtime action; if it reaches the model, "
            "explain the local action instead of inventing unsupported behavior."
        )
        return (
            "# Built-in Slash Command Context\n\n"
            f"Command: {self.slash_name}\n"
            f"Arguments: {raw_arguments or '(none)'}\n"
            f"UI action: {self.ui_action or '(none)'}\n"
            f"Query policy: {query_policy}\n\n"
            "The user invoked a supported PersonAgent built-in command. Apply only the "
            "behavior that exists in PersonAgent's runtime, tools, and UI surfaces."
        )

    def to_inventory_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slash_name": self.slash_name,
            "description": self.description,
            "argument_hint": self.argument_hint,
            "allowed_tools": list(self.allowed_tools),
            "model": self.model,
            "effort": self.effort,
            "should_query": self.should_query,
            "ui_action": self.ui_action,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class BuiltinCommandResolution:
    command: BuiltinCommand
    raw_arguments: str

    def reminder(self) -> str:
        return self.command.reminder(self.raw_arguments)

    def metadata(self) -> dict[str, Any]:
        data = self.command.to_inventory_dict()
        data.update({"arguments": self.raw_arguments})
        return data


class CommandRegistry:
    """Loads Markdown prompt commands from PersonAgent command roots."""

    def __init__(self, extra_roots: list[str | Path] | None = None) -> None:
        self._extra_roots = tuple(Path(root).expanduser() for root in extra_roots or ())

    def list_commands(self, workspace_root: str | Path | None = None) -> list[PromptCommand]:
        commands: dict[str, PromptCommand] = {}
        for root in self._candidate_roots(workspace_root):
            for path in _iter_command_files(root):
                command = _load_command(path, root)
                if command is not None:
                    commands.setdefault(command.name, command)
        return sorted(commands.values(), key=lambda item: item.name)

    def resolve(
        self,
        message: str,
        workspace_root: str | Path | None = None,
    ) -> SlashCommandResolution | None:
        parsed = parse_slash_invocation(message)
        if parsed is None:
            return None
        name, raw_arguments = parsed
        command = next(
            (item for item in self.list_commands(workspace_root) if item.name == name),
            None,
        )
        if command is None:
            return None
        return SlashCommandResolution(
            command=command,
            raw_arguments=raw_arguments,
            expanded_prompt=command.expand(raw_arguments),
        )

    def _candidate_roots(self, workspace_root: str | Path | None) -> tuple[Path, ...]:
        roots: list[Path] = []
        if workspace_root:
            workspace = Path(workspace_root).expanduser()
            roots.append(workspace / ".personagent" / "commands")
        roots.extend(
            [
                Path.cwd() / ".personagent" / "commands",
                Path.home() / ".personagent" / "commands",
            ]
        )
        roots.extend(self._extra_roots)
        seen: set[Path] = set()
        unique: list[Path] = []
        for root in roots:
            try:
                resolved = root.resolve()
            except OSError:
                continue
            if resolved not in seen:
                seen.add(resolved)
                unique.append(resolved)
        return tuple(unique)


class CommandService:
    """Unified slash command service for prompt commands, skills, and local built-ins."""

    def __init__(self, registry: CommandRegistry | None = None) -> None:
        self.registry = registry or CommandRegistry()

    def list_prompt_commands(
        self,
        workspace_root: str | Path | None = None,
    ) -> list[PromptCommand]:
        return self.registry.list_commands(workspace_root)

    def resolve_prompt_command(
        self,
        message: str,
        workspace_root: str | Path | None = None,
    ) -> SlashCommandResolution | None:
        return self.registry.resolve(message, workspace_root)

    def list_builtin_commands(self) -> list[BuiltinCommand]:
        return sorted(BUILTIN_COMMANDS.values(), key=lambda item: item.name)

    def resolve_builtin(self, message: str) -> BuiltinCommandResolution | None:
        parsed = parse_slash_invocation(message)
        if parsed is None:
            return None
        name, raw_arguments = parsed
        command = BUILTIN_COMMANDS.get(name)
        if command is None:
            return None
        return BuiltinCommandResolution(command=command, raw_arguments=raw_arguments)


BUILTIN_COMMANDS: dict[str, BuiltinCommand] = {
    "plan": BuiltinCommand(
        name="plan",
        description="Enter planning flow before making changes.",
        allowed_tools=("EnterPlanMode", "ExitPlanMode", "TodoWrite"),
    ),
    "memory": BuiltinCommand(
        name="memory",
        description="Inspect or work with PersonAgent memory for the active workspace.",
        argument_hint="[search terms]",
    ),
    "mcp": BuiltinCommand(
        name="mcp",
        description="Inspect MCP servers, resources, and authentication state.",
        argument_hint="[server or resource]",
        allowed_tools=("ListMcpResourcesTool", "ReadMcpResourceTool", "McpAuth"),
    ),
    "skills": BuiltinCommand(
        name="skills",
        description="List or inspect enabled skills.",
        argument_hint="[skill name]",
        allowed_tools=("Skill", "ToolSearch"),
        should_query=False,
        ui_action="skills_workspace",
    ),
    "permissions": BuiltinCommand(
        name="permissions",
        description="Inspect tool permission policy for the current turn.",
        argument_hint="[tool name]",
        allowed_tools=("Config",),
        should_query=False,
        ui_action="permissions",
    ),
    "model": BuiltinCommand(
        name="model",
        description="Inspect or change the selected model in the UI.",
        argument_hint="[provider/model]",
        should_query=False,
        ui_action="model_picker",
    ),
    "effort": BuiltinCommand(
        name="effort",
        description="Inspect or change reasoning effort in the UI.",
        argument_hint="[low|medium|high|xhigh|max]",
        should_query=False,
        ui_action="reasoning_picker",
    ),
    "context": BuiltinCommand(
        name="context",
        description="Inspect model-visible context for the next turn.",
        allowed_tools=("Read", "Glob", "Grep", "LSP"),
    ),
    "clear": BuiltinCommand(
        name="clear",
        description="Start a clean chat session in the UI.",
        should_query=False,
        ui_action="clear_chat",
    ),
    "compact": BuiltinCommand(
        name="compact",
        description="Request context compaction for a long conversation.",
        ui_action="compact_context",
    ),
    "diff": BuiltinCommand(
        name="diff",
        description="Inspect current workspace changes.",
        allowed_tools=("shell", "Read", "Grep"),
    ),
    "files": BuiltinCommand(
        name="files",
        description="Inspect files or directories in the active workspace.",
        argument_hint="[path]",
        allowed_tools=("Read", "Glob", "Grep", "LSP"),
    ),
    "branch": BuiltinCommand(
        name="branch",
        description="Inspect git branch and worktree state.",
        allowed_tools=("shell",),
    ),
    "usage": BuiltinCommand(
        name="usage",
        description="Inspect live token and tool usage for the session.",
        should_query=False,
        ui_action="usage_status",
    ),
    "status": BuiltinCommand(
        name="status",
        description="Summarize workspace, git, tools, and session state.",
        allowed_tools=("shell", "Config"),
        should_query=False,
        ui_action="local_status",
    ),
    "doctor": BuiltinCommand(
        name="doctor",
        description="Run a local health check of PersonAgent runtime surfaces.",
        allowed_tools=("shell", "Config", "ToolSearch", "ListMcpResourcesTool"),
    ),
    "help": BuiltinCommand(
        name="help",
        description="Show supported slash commands and command usage.",
        should_query=False,
        ui_action="command_help",
    ),
}


def parse_slash_invocation(message: str) -> tuple[str, str] | None:
    """Parse a `/command args` message.

    Nested command identifiers are allowed so `.personagent/commands/review/code.md`
    can be invoked as `/review/code`.
    """

    stripped = message.strip()
    if not stripped.startswith("/") or stripped == "/":
        return None
    head, _, tail = stripped[1:].partition(" ")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", head):
        return None
    return head, tail.strip()


def _iter_command_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _load_command(path: Path, root: Path) -> PromptCommand | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    frontmatter, body = parse_markdown_frontmatter(content)
    if not body.strip():
        return None
    relative = path.relative_to(root).with_suffix("")
    name = relative.as_posix()
    description = str(frontmatter.get("description") or body.strip().splitlines()[0])[:160]
    return PromptCommand(
        name=name,
        body=body,
        path=path,
        description=description,
        allowed_tools=as_string_list(frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools")),
        model=_optional_str(frontmatter.get("model")),
        argument_hint=_optional_str(
            frontmatter.get("argument-hint") or frontmatter.get("argument_hint")
        ),
        disable_model_invocation=as_bool(
            frontmatter.get("disable-model-invocation")
            or frontmatter.get("disable_model_invocation")
        ),
        when_to_use=_optional_str(frontmatter.get("when_to_use") or frontmatter.get("when-to-use")),
        context=str(frontmatter.get("context") or "inline"),
        effort=_optional_str(frontmatter.get("effort") or frontmatter.get("reasoning")),
        metadata=frontmatter,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
