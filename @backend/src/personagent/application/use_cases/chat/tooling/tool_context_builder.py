"""Tool execution context assembly extracted from ``chat_completion.py``.

Every chat turn that exposes tools to the LLM must build a
:class:`ToolUseContext` capturing the workspace root, the
sandbox-allowed roots, the working directory, permission mode, plan
state, and a handful of runtime limits sourced from the
:class:`ToolRuntimeConfig`. Historically this lived as three private
methods on :class:`ChatCompletionUseCase`:

* ``_build_tool_context`` -- orchestrate the whole assembly,
* ``_resolve_workspace_root`` -- resolve and validate a single root,
* ``_resolve_allowed_path`` -- resolve a per-request path against the
  sandbox roots.

They form a cohesive surface: only ``_build_tool_context`` is called
from the use case (``execute`` and ``_stream_completion_turn``); the
two ``_resolve_*`` helpers are exclusively its dependencies.  Moving
the trio out as :class:`ToolContextBuilder` shrinks the god file
without altering any input/output, error message, or side effect.

Backward compatibility:

* Same ``ToolUseContext`` shape -- field order, defaults, and
  computed values are preserved verbatim.
* Same exceptions and messages -- ``RuntimeError`` for missing
  runtime config, ``ValueError`` for non-directory workspace, invalid
  cwd, and out-of-roots paths.
* Same permission-mode validation against the
  :data:`VALID_PERMISSION_MODES` set (single source of truth; the
  legacy module imports the same value from here).
"""

from __future__ import annotations

from pathlib import Path

from personagent.application.dto import ChatRequestDTO
from personagent.application.plan_mode import (
    is_plan_mode_active,
    normalize_plan_state,
)
from personagent.application.tools.orchestrator import ToolRuntimeConfig
from personagent.application.use_cases.chat.helpers import is_relative_to
from personagent.application.use_cases.chat.messaging.state import PromptPreparation
from personagent.domain.conversation.models import Conversation
from personagent.domain.tools import ToolUseContext

VALID_PERMISSION_MODES: frozenset[str] = frozenset(
    {
        "ask_for_risk",
        "manual",
        "read_only",
        "readonly",
        "accept_edits",
        "full",
        "bypass",
        "dont_ask",
    }
)


class ToolContextBuilder:
    """Build the :class:`ToolUseContext` for a single chat turn.

    The builder owns three responsibilities:

    1. Determine the effective workspace root (the per-request
       ``tool_context.workspace_root`` wins over the default
       :class:`ToolRuntimeConfig` workspace).
    2. Determine the allowed sandbox roots (per-request
       ``allowed_roots`` wins over the config defaults but every
       path is re-resolved against the effective workspace).
    3. Resolve the working directory, the permission mode (defaulting
       to ``ask_for_risk`` when unset or invalid), and propagate the
       plan-mode state into the context.
    """

    def __init__(self, *, tool_runtime_config: ToolRuntimeConfig | None) -> None:
        self._tool_runtime_config = tool_runtime_config

    def build(
        self,
        request: ChatRequestDTO,
        conversation: Conversation,
        preparation: PromptPreparation | None = None,
    ) -> ToolUseContext:
        """Return the :class:`ToolUseContext` for the current turn."""

        if self._tool_runtime_config is None:
            raise RuntimeError("Tool runtime is not configured")

        config = self._tool_runtime_config
        raw_context = request.tool_context or {}
        raw_workspace_root = raw_context.get("workspace_root")
        workspace_root = (
            self.resolve_workspace_root(str(raw_workspace_root))
            if raw_workspace_root
            else config.workspace_root
        )
        root_scope = (workspace_root,) if raw_workspace_root else config.allowed_roots

        requested_roots = raw_context.get("allowed_roots")
        allowed_roots = root_scope
        if isinstance(requested_roots, list) and requested_roots:
            allowed_roots = tuple(
                self.resolve_allowed_path(str(path), workspace_root, root_scope)
                for path in requested_roots
            )

        raw_cwd = raw_context.get("cwd")
        cwd = (
            self.resolve_allowed_path(str(raw_cwd), workspace_root, allowed_roots)
            if raw_cwd
            else workspace_root
        )
        if not cwd.is_dir():
            raise ValueError(f"Tool cwd is not a directory: {cwd}")

        plan_state = normalize_plan_state(conversation.metadata)
        plan_active = is_plan_mode_active(conversation.metadata)
        permission_mode = (
            str(raw_context.get("permission_mode")).strip().lower()
            if raw_context.get("permission_mode")
            else str(conversation.metadata.get("permission_mode") or "ask_for_risk")
        )
        if permission_mode not in VALID_PERMISSION_MODES:
            permission_mode = "ask_for_risk"
        return ToolUseContext(
            conversation_id=str(conversation.id),
            workspace_root=workspace_root,
            cwd=cwd,
            allowed_roots=allowed_roots,
            permissions={
                "mode": permission_mode,
                "plan_mode": plan_active,
            },
            limits={
                "read_max_bytes": config.read_max_bytes,
                "read_default_limit": config.read_default_limit,
                "read_max_lines": config.read_max_lines,
                "search_timeout_ms": config.search_timeout_ms,
                "shell_timeout_ms": config.shell_timeout_ms,
                "web_timeout_ms": config.web_timeout_ms,
                "web_max_bytes": config.web_max_bytes,
                "max_tool_iterations": config.max_tool_iterations,
                "max_concurrency": config.max_concurrency,
                "result_max_chars": config.result_max_chars,
                "tool_result_storage_root": (
                    str(config.tool_result_storage_root)
                    if config.tool_result_storage_root
                    else None
                ),
                "web_allowed_domains": config.web_allowed_domains,
                "web_blocked_domains": config.web_blocked_domains,
                "web_allow_private_hosts": config.web_allow_private_hosts,
                "skill_roots": tuple(str(path) for path in config.skill_roots),
            },
            metadata={
                "request": raw_context,
                "todos": conversation.metadata.get("todos", []),
                "plan_mode": plan_state,
                "plan_mode_active": plan_active,
                "structured_output_schema": raw_context.get("structured_output_schema"),
                "browser_cooperation": conversation.metadata.get(
                    "browser_cooperation", {}
                ),
                "browser_workspace": conversation.metadata.get("browser_workspace", {}),
                "browser_target": preparation.browser_target if preparation else None,
            },
        )

    def resolve_workspace_root(self, raw_path: str) -> Path:
        """Expand and validate a workspace-root path."""

        path = Path(raw_path).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace root is not a directory: {path}")
        return path

    def resolve_allowed_path(
        self,
        raw_path: str,
        base_root: Path,
        allowed_roots: tuple[Path, ...],
    ) -> Path:
        """Resolve ``raw_path`` against ``base_root`` and validate against the sandbox."""

        path = Path(raw_path).expanduser()
        candidate = path if path.is_absolute() else base_root / path
        resolved = candidate.resolve()
        if not any(is_relative_to(resolved, root) for root in allowed_roots):
            raise ValueError(f"Tool path is outside configured roots: {raw_path}")
        return resolved


__all__ = ["ToolContextBuilder", "VALID_PERMISSION_MODES"]
