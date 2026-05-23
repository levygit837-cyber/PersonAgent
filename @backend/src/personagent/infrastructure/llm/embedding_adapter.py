"""OpenAI-compatible embedding adapter for local llama-server."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding endpoint cannot produce vectors."""


class OpenAICompatibleEmbeddingAdapter:
    """Calls an OpenAI-compatible `/embeddings` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        dimensions: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.dimensions = dimensions
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings."""

        if not texts:
            return []
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        try:
            response = await self._client.post("/embeddings", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError(f"Embedding request failed: {exc}") from exc

        data = response.json()
        rows = data.get("data")
        if not isinstance(rows, list):
            raise EmbeddingServiceError("Embedding response did not include a data list")

        vectors_by_index: dict[int, list[float]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = int(row.get("index") or 0)
            embedding = row.get("embedding")
            if isinstance(embedding, list):
                vectors_by_index[index] = [float(value) for value in embedding]

        vectors = [vectors_by_index.get(index, []) for index in range(len(texts))]
        if any(not vector for vector in vectors):
            raise EmbeddingServiceError("Embedding response missed one or more vectors")
        return vectors

    async def health_check(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/models")
            return {
                "status": "healthy" if response.status_code == 200 else "unhealthy",
                "status_code": response.status_code,
                "base_url": self.base_url,
                "model": self.model,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "base_url": self.base_url,
                "model": self.model,
                "error": str(exc),
            }

    async def close(self) -> None:
        await self._client.aclose()
