"""Mock embedding adapter for stress testing — bypasses HTTP entirely."""

from __future__ import annotations

import asyncio
import hashlib
import time


class MockEmbeddingAdapter:
    """Deterministic mock embedding with configurable latency.

    Returns stable vectors based on content hash so recall scoring is realistic.
    """

    def __init__(
        self,
        *,
        latency_ms: float = 50,
        dimensions: int = 1024,
    ) -> None:
        self.latency_ms = latency_ms
        self.dimensions = dimensions
        self._call_count = 0
        self._total_texts = 0
        self._call_latencies: list[float] = []

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def total_texts_embedded(self) -> int:
        return self._total_texts

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        start = time.perf_counter()
        await asyncio.sleep(self.latency_ms / 1000)
        self._call_count += 1
        self._total_texts += len(texts)
        elapsed = (time.perf_counter() - start) * 1000
        self._call_latencies.append(elapsed)

        return [self._text_to_vector(text) for text in texts]

    async def health_check(self) -> dict[str, str]:
        return {"status": "healthy", "provider": "mock_embedding"}

    async def close(self) -> None:
        pass

    def reset(self) -> None:
        self._call_count = 0
        self._total_texts = 0
        self._call_latencies.clear()

    def _text_to_vector(self, text: str) -> list[float]:
        """Deterministic vector from content hash — same text → same vector."""
        digest = hashlib.sha256(text.encode()).hexdigest()
        values = [int(digest[i: i + 2], 16) / 255.0 for i in range(0, len(digest), 2)]
        while len(values) < self.dimensions:
            values.extend(values)
        return values[: self.dimensions]
