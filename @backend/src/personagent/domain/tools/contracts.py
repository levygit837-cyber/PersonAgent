"""Contratos de ferramentas do domínio.

Este módulo não conhece FastAPI, banco, filesystem ou llama.cpp. Ele define
as formas puras que a aplicação usa para registrar, validar e executar
ferramentas chamadas pelo modelo.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

JSONSchema = dict[str, Any]
ToolArguments = dict[str, Any]


class ToolExecutionStatus(StrEnum):
    """Estados de execução de uma ferramenta."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    PERMISSION_REQUIRED = "permission_required"


class ToolGroup(StrEnum):
    """Agrupamentos públicos de ferramentas."""

    WORKSPACE = "workspace"
    SHELL = "shell"
    WEB = "web"
    AGENT = "agent"
    PLANNING = "planning"
    TASK = "task"
    DISCOVERY = "discovery"
    OUTPUT = "output"
    LSP = "lsp"
    CONFIG = "config"
    WORKTREE = "worktree"
    MCP = "mcp"
    USER_INTERACTION = "user_interaction"
    OTHER = "other"


class ToolPermissionBehavior(StrEnum):
    """Decisão de permissão para uma chamada de ferramenta."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True, slots=True)
class ToolPermissionResult:
    """Resultado de uma verificação de permissão."""

    behavior: ToolPermissionBehavior = ToolPermissionBehavior.ALLOW
    message: str | None = None
    updated_input: ToolArguments | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        """Retorna True quando a chamada pode prosseguir."""
        return self.behavior == ToolPermissionBehavior.ALLOW


@dataclass(frozen=True, slots=True)
class ToolProgress:
    """Evento incremental de progresso de ferramenta."""

    tool_call_id: str
    tool_name: str
    status: ToolExecutionStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_stream_dict(self) -> dict[str, Any]:
        """Serializa para payload SSE."""
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_status": self.status.value,
            "tool_message": self.message,
            "tool_data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


ProgressCallback = Callable[[ToolProgress], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class ToolUseContext:
    """Contexto disponível para validação e execução de ferramentas."""

    conversation_id: str
    workspace_root: Path
    cwd: Path
    allowed_roots: tuple[Path, ...]
    permissions: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    progress_callback: ProgressCallback | None = None

    async def emit_progress(self, progress: ToolProgress) -> None:
        """Emite progresso se a execução recebeu um callback."""
        if self.progress_callback is None:
            return
        maybe_awaitable = self.progress_callback(progress)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def with_progress_callback(self, callback: ProgressCallback | None) -> ToolUseContext:
        """Retorna uma cópia do contexto com outro callback de progresso."""
        return replace(self, progress_callback=callback)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Chamada de ferramenta emitida pelo modelo."""

    id: str
    name: str
    arguments: ToolArguments = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai(cls, payload: dict[str, Any]) -> ToolCall:
        """Cria uma chamada a partir do formato OpenAI-compatible."""
        function = payload.get("function") or {}
        raw_arguments = function.get("arguments") or {}
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": raw_arguments}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            arguments = {"_raw_arguments": raw_arguments}

        return cls(
            id=str(payload.get("id") or ""),
            name=str(function.get("name") or payload.get("name") or ""),
            arguments=arguments,
            raw=payload,
        )

    def to_openai(self) -> dict[str, Any]:
        """Serializa para o formato assistant.tool_calls."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Resultado final de uma chamada de ferramenta."""

    tool_call_id: str
    tool_name: str
    content: str
    status: ToolExecutionStatus = ToolExecutionStatus.COMPLETED
    is_error: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_stream_dict(self) -> dict[str, Any]:
        """Serializa o resultado para payload SSE."""
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_status": self.status.value,
            "tool_result": self.content,
            "tool_error": self.content if self.is_error else None,
            "tool_data": self.data,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Metadados públicos de uma ferramenta."""

    name: str
    description: str
    input_schema: JSONSchema
    output_schema: JSONSchema | None = None
    aliases: tuple[str, ...] = ()
    group: str = ToolGroup.OTHER.value
    search_hint: str | None = None
    usage_prompt: str | None = None
    when_to_use: tuple[str, ...] = ()
    when_not_to_use: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    cacheable_prompt: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    max_result_size_chars: int = 20_000
    timeout_ms: int | None = None
    strict: bool = True
    should_defer: bool = False
    always_load: bool = False
    is_read_only: bool = False
    is_destructive: bool = False
    is_concurrency_safe: bool = False
    is_open_world: bool = False
    requires_user_interaction: bool = False
    is_lsp: bool = False
    is_mcp: bool = False

    def to_openai_tool(self) -> dict[str, Any]:
        """Converte a definição para schema OpenAI-compatible."""
        function: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }
        if self.strict:
            function["strict"] = True
        return {"type": "function", "function": function}

    def to_discovery_dict(self, *, enabled: bool = True) -> dict[str, Any]:
        """Serializa uma descrição compacta para ToolSearch."""
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "description": self.description,
            "group": self.group,
            "search_hint": self.search_hint,
            "usage_prompt": self.usage_prompt,
            "when_to_use": list(self.when_to_use),
            "when_not_to_use": list(self.when_not_to_use),
            "examples": list(self.examples),
            "cacheable_prompt": self.cacheable_prompt,
            "enabled": enabled,
            "should_defer": self.should_defer,
            "always_load": self.always_load,
            "is_read_only": self.is_read_only,
            "is_destructive": self.is_destructive,
            "is_concurrency_safe": self.is_concurrency_safe,
            "is_open_world": self.is_open_world,
            "requires_user_interaction": self.requires_user_interaction,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


ToolHandler = Callable[[ToolArguments, ToolUseContext, ToolCall], Awaitable[ToolResult]]
ToolPredicate = Callable[[ToolArguments], bool]
ToolValidator = Callable[[ToolArguments, ToolUseContext], Awaitable[ToolPermissionResult | None]]
ToolPermissionChecker = Callable[[ToolArguments, ToolUseContext], Awaitable[ToolPermissionResult]]
ToolClassifierInput = Callable[[ToolArguments], Any]


class Tool(Protocol):
    """Interface runtime para ferramentas."""

    definition: ToolDefinition

    async def call(
        self,
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        """Executa a ferramenta."""
        ...

    def is_enabled(self) -> bool:
        """Indica se a ferramenta está disponível."""
        ...

    def is_concurrency_safe(self, arguments: ToolArguments) -> bool:
        """Indica se a chamada pode executar em paralelo."""
        ...

    def is_read_only(self, arguments: ToolArguments) -> bool:
        """Indica se a chamada é somente leitura."""
        ...

    def is_destructive(self, arguments: ToolArguments) -> bool:
        """Indica se a chamada é destrutiva."""
        ...

    async def validate_input(
        self, arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        """Valida valores de entrada antes da permissão."""
        ...

    async def check_permissions(
        self, arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult:
        """Verifica permissões para a chamada."""
        ...

    def to_auto_classifier_input(self, arguments: ToolArguments) -> Any:
        """Representação compacta para classificadores de segurança."""
        ...
