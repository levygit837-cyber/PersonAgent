"""Process manager mixin."""

from personagent.infrastructure.llm.process_manager import (
    EmbeddingServerProcessManager,
    LlamaServerProcessManager,
)


class _ProcessMixin:
    def get_process_manager(self) -> LlamaServerProcessManager:
        """Retorna o gerenciador de processo do llama-server."""
        if self._process_manager is None:
            self._process_manager = LlamaServerProcessManager()
        return self._process_manager

    def get_embedding_process_manager(self) -> EmbeddingServerProcessManager:
        """Retorna o gerenciador do servidor local de embeddings."""
        if self._embedding_process_manager is None:
            self._embedding_process_manager = EmbeddingServerProcessManager()
        return self._embedding_process_manager
