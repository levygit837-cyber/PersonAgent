"""Factory para construir ferramentas com defaults seguros."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from personagent.domain.tools.contracts import (
    ToolArguments,
    ToolCall,
    ToolClassifierInput,
    ToolDefinition,
    ToolHandler,
    ToolPermissionBehavior,
    ToolPermissionChecker,
    ToolPermissionResult,
    ToolPredicate,
    ToolResult,
    ToolUseContext,
    ToolValidator,
)


@dataclass(frozen=True, slots=True)
class BuiltTool:
    """Implementação concreta de Tool produzida por build_tool."""

    definition: ToolDefinition
    handler: ToolHandler
    enabled: bool = True
    concurrency_safe: ToolPredicate | None = None
    read_only: ToolPredicate | None = None
    destructive: ToolPredicate | None = None
    input_validator: ToolValidator | None = None
    permission_checker: ToolPermissionChecker | None = None
    classifier_input: ToolClassifierInput | None = None

    async def call(
        self,
        arguments: ToolArguments,
        context: ToolUseContext,
        call: ToolCall,
    ) -> ToolResult:
        """Executa a ferramenta."""
        return await self.handler(arguments, context, call)

    def is_enabled(self) -> bool:
        """Retorna se a ferramenta está habilitada."""
        return self.enabled

    def is_concurrency_safe(self, arguments: ToolArguments) -> bool:
        """Default fail-closed: não assume paralelismo seguro."""
        if self.concurrency_safe is None:
            return bool(self.definition.is_concurrency_safe)
        return bool(self.concurrency_safe(arguments))

    def is_read_only(self, arguments: ToolArguments) -> bool:
        """Default fail-closed: não assume somente leitura."""
        if self.read_only is None:
            return bool(self.definition.is_read_only)
        return bool(self.read_only(arguments))

    def is_destructive(self, arguments: ToolArguments) -> bool:
        """Default seguro: não marca como destrutivo sem override explícito."""
        if self.destructive is None:
            return bool(self.definition.is_destructive)
        return bool(self.destructive(arguments))

    async def validate_input(
        self, arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult | None:
        """Executa validação opcional de entrada."""
        if self.input_validator is None:
            return None
        return await self.input_validator(arguments, context)

    async def check_permissions(
        self, arguments: ToolArguments, context: ToolUseContext
    ) -> ToolPermissionResult:
        """Default permissivo; ferramentas de risco devem sobrescrever."""
        if self.permission_checker is None:
            return ToolPermissionResult(
                behavior=ToolPermissionBehavior.ALLOW,
                updated_input=arguments,
            )
        return await self.permission_checker(arguments, context)

    def to_auto_classifier_input(self, arguments: ToolArguments) -> Any:
        """Default: pula classificador."""
        if self.classifier_input is None:
            return ""
        return self.classifier_input(arguments)


def build_tool(
    *,
    definition: ToolDefinition,
    handler: ToolHandler,
    enabled: bool = True,
    is_concurrency_safe: ToolPredicate | None = None,
    is_read_only: ToolPredicate | None = None,
    is_destructive: ToolPredicate | None = None,
    validate_input: ToolValidator | None = None,
    check_permissions: ToolPermissionChecker | None = None,
    to_auto_classifier_input: ToolClassifierInput | None = None,
) -> BuiltTool:
    """Cria uma ferramenta completa com defaults centralizados."""
    return BuiltTool(
        definition=definition,
        handler=handler,
        enabled=enabled,
        concurrency_safe=is_concurrency_safe,
        read_only=is_read_only,
        destructive=is_destructive,
        input_validator=validate_input,
        permission_checker=check_permissions,
        classifier_input=to_auto_classifier_input,
    )
