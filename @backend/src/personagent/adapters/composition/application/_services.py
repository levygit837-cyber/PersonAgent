"""Application services mixin."""

from personagent.application.services import (
    NextStepSuggestionService,
    SessionMemoryService,
    SessionTitleService,
)
from personagent.domain.llm_backend.repositories import LLMBackendRepository


class _ServicesMixin:
    def create_session_memory_service(
        self,
        llm_backend: LLMBackendRepository | None = None,
    ) -> SessionMemoryService:
        return SessionMemoryService(llm_backend)

    def create_next_step_suggestion_service(
        self,
        llm_backend: LLMBackendRepository,
    ) -> NextStepSuggestionService:
        return NextStepSuggestionService(llm_backend)

    def get_session_title_service(self) -> SessionTitleService | None:
        """Return the cached/LLM-backed session title verifier."""
        if not self._settings.chat_session_title_checks_enabled:
            return None
        if self._session_title_service is None:
            primary_provider = self._settings.chat_session_title_primary_provider
            fallback_provider = self._settings.chat_session_title_fallback_provider
            self._session_title_service = SessionTitleService(
                primary_llm_backend=self.get_llm_backend(primary_provider),
                fallback_llm_backend=self.get_llm_backend(fallback_provider),
                primary_provider=primary_provider,
                primary_model=self._settings.chat_session_title_primary_model,
                fallback_provider=fallback_provider,
                fallback_model=self._settings.chat_session_title_fallback_model,
                batch_size=self._settings.chat_session_title_batch_size,
                scan_limit=self._settings.chat_session_title_scan_limit,
                max_history_chars=self._settings.chat_session_title_max_history_chars,
                duplicate_check_interval_seconds=(
                    self._settings.chat_session_title_duplicate_check_interval_seconds
                ),
                similarity_threshold=self._settings.chat_session_title_similarity_threshold,
            )
        return self._session_title_service
