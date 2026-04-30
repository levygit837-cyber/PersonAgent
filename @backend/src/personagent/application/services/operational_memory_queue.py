"""RabbitMQ handoff for asynchronous operational-memory indexing."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class OperationalMemoryQueue:
    """Small aio-pika adapter used by the memory outbox pipeline."""

    def __init__(
        self,
        *,
        url: str,
        exchange_name: str,
        queue_name: str,
        prefetch: int = 8,
    ) -> None:
        self._url = url
        self._exchange_name = exchange_name
        self._queue_name = queue_name
        self._prefetch = max(1, prefetch)
        self._connection: Any | None = None
        self._channel: Any | None = None
        self._exchange: Any | None = None

    async def publish(self, message: dict[str, Any]) -> None:
        aio_pika = await _aio_pika()
        exchange = await self._ensure_exchange()
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(message, ensure_ascii=False, default=str).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=self._queue_name,
        )

    async def consume(
        self,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        channel = await self._ensure_channel()
        queue = await channel.declare_queue(self._queue_name, durable=True)
        await queue.bind(await self._ensure_exchange(), routing_key=self._queue_name)

        async with queue.iterator() as iterator:
            async for message in iterator:
                async with message.process(requeue=False):
                    payload = json.loads(message.body.decode("utf-8"))
                    await handler(payload)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._exchange = None

    async def _ensure_exchange(self) -> Any:
        channel = await self._ensure_channel()
        if self._exchange is None:
            self._exchange = await channel.declare_exchange(
                self._exchange_name,
                type="direct",
                durable=True,
            )
            queue = await channel.declare_queue(self._queue_name, durable=True)
            await queue.bind(self._exchange, routing_key=self._queue_name)
        return self._exchange

    async def _ensure_channel(self) -> Any:
        aio_pika = await _aio_pika()
        if self._connection is None or self._connection.is_closed:
            self._connection = await aio_pika.connect_robust(self._url)
        if self._channel is None or self._channel.is_closed:
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=self._prefetch)
        return self._channel


async def _aio_pika() -> Any:
    try:
        import aio_pika
    except ImportError as exc:  # pragma: no cover - depends on optional environment setup
        raise RuntimeError("aio-pika is required when MEMORY_QUEUE_ENABLED=true") from exc
    return aio_pika
