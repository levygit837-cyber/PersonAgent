"""Prompt builder, context, and command registry mixin."""

from personagent.application.use_cases.build_context import BuildContextUseCase
from personagent.domain.llm_backend.repositories import LLMBackendRepository
from personagent.domain.prompts.commands import CommandRegistry
from personagent.domain.prompts.services import PromptBuilder, PromptContextAnalyzer
from personagent.infrastructure.persistence.context import InMemoryContextRepository


class _PromptContextMixin:
    def get_prompt_builder(self) -> PromptBuilder:
        """Retorna o builder dinâmico de system prompts."""
        if self._prompt_builder is None:
            self._prompt_builder = PromptBuilder(permission_mode="manual")
        return self._prompt_builder

    def create_prompt_context_analyzer(
        self,
        llm_backend: LLMBackendRepository,
    ) -> PromptContextAnalyzer:
        backend_key = id(llm_backend)
        analyzer = self._prompt_context_analyzers.get(backend_key)
        if analyzer is None:
            analyzer = PromptContextAnalyzer(
                llm_backend,
                timeout_seconds=self._settings.prompt_context_analysis_timeout_seconds,
                long_timeout_seconds=self._settings.prompt_context_analysis_long_timeout_seconds,
                failure_cooldown_seconds=(
                    self._settings.prompt_context_analysis_failure_cooldown_seconds
                ),
                long_context_chars=self._settings.prompt_context_analysis_long_context_chars,
                max_payload_chars=self._settings.prompt_context_analysis_max_payload_chars,
            )
            self._prompt_context_analyzers[backend_key] = analyzer
        return analyzer

    def create_command_registry(self) -> CommandRegistry:
        return CommandRegistry(extra_roots=self._settings.prompt_command_root_paths)

    def get_context_repository(self) -> InMemoryContextRepository:
        """Return the in-memory context cache for the main chat."""
        if self._context_repository is None:
            self._context_repository = InMemoryContextRepository()
        return self._context_repository

    def create_build_context_use_case(self, workspace_root: str) -> BuildContextUseCase:
        """Cria um use case de contexto para o workspace selecionado."""
        from personagent.infrastructure.persistence.memory import (
            FileSystemMemoryRepository,
        )
        return BuildContextUseCase(
            workspace_root=workspace_root,
            context_repository=self.get_context_repository(),
            enable_persona_md=True,
            memory_repository=FileSystemMemoryRepository(),
        )
