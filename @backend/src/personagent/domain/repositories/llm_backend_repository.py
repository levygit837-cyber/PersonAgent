"""Porta (interface) para o backend de inferência LLM."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from personagent.domain.models.inference_result import InferenceResult, StreamChunk


class LLMBackendRepository(ABC):
    """Interface para comunicação com o motor de inferência LLM."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> InferenceResult:
        """Executa uma completion síncrona (não-streaming)."""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = -1,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Executa uma completion com streaming de resposta."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Verifica se o backend está saudável."""
        ...

    @abstractmethod
    async def get_model_info(self) -> dict[str, Any]:
        """Retorna informações sobre o modelo carregado."""
        ...
