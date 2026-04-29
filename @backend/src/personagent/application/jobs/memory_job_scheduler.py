"""Scheduler de jobs de memória usando APScheduler.

Wrapper sobre AsyncIOScheduler para processamento assíncrono
de tarefas de memória (extração, consolidação, sync).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from personagent.application.jobs.memory_job import JobType, MemoryJob

logger = structlog.get_logger(__name__)


class MemoryJobScheduler:
    """Gerencia jobs de memória em background.

    Suporta:
    - Event-triggered jobs (extract_memories após turn)
    - Cron-triggered jobs (auto_dream a cada 24h)
    """

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._handlers: dict[JobType, Any] = {}

    def initialize(self) -> None:
        """Inicializa o scheduler."""
        self._scheduler = AsyncIOScheduler()
        logger.info("memory_job_scheduler_initialized")

    def register_handler(self, job_type: JobType, handler: Any) -> None:
        """Registra um handler para um tipo de job.

        Args:
            job_type: Tipo de job.
            handler: Função ou callable que processa o job.
        """
        self._handlers[job_type] = handler
        logger.info("memory_job_handler_registered", job_type=str(job_type))

    def start(self) -> None:
        """Inicia o scheduler."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")
        self._scheduler.start()
        logger.info("memory_job_scheduler_started")

    def shutdown(self) -> None:
        """Desliga o scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown()
            logger.info("memory_job_scheduler_shutdown")

    async def submit_job(self, job: MemoryJob) -> str:
        """Submete um job para execução imediata (fire-and-forget).

        Args:
            job: Job a executar.

        Returns:
            ID do job.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")

        self._scheduler.add_job(
            self._execute_job,
            args=[job],
            id=job.id,
            replace_existing=True,
        )
        logger.info(
            "memory_job_submitted",
            job_id=job.id,
            job_type=str(job.type),
        )
        return job.id

    def schedule_cron(
        self,
        job_type: JobType,
        cron_expr: str,
        timezone: str = "UTC",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Agenda um job recorrente via cron.

        Args:
            job_type: Tipo de job.
            cron_expr: Expressão cron.
            timezone: Timezone.
            payload: Payload opcional.

        Returns:
            ID do job agendado.
        """
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")

        job_id = f"cron_{job_type}_{uuid.uuid4().hex[:8]}"
        job = MemoryJob(
            id=job_id,
            type=job_type,
            conversation_id=None,
            project_slug="*",
            payload=payload or {},
        )

        self._scheduler.add_job(
            self._execute_job,
            trigger=CronTrigger.from_crontab(cron_expr, timezone=timezone),
            id=job_id,
            args=[job],
            replace_existing=True,
        )
        logger.info(
            "memory_job_scheduled",
            job_id=job_id,
            job_type=str(job_type),
            cron=cron_expr,
        )
        return job_id

    async def _execute_job(self, job: MemoryJob) -> None:
        """Executa um job chamando o handler registrado.

        Args:
            job: Job a executar.
        """
        handler = self._handlers.get(job.type)
        if handler is None:
            logger.warning(
                "memory_job_no_handler",
                job_id=job.id,
                job_type=str(job.type),
            )
            return

        job.mark_running()
        try:
            result = await handler(job)
            job.mark_completed(result=result)
            logger.info(
                "memory_job_completed",
                job_id=job.id,
                job_type=str(job.type),
            )
        except Exception as exc:
            job.mark_failed(str(exc))
            logger.exception(
                "memory_job_failed",
                job_id=job.id,
                job_type=str(job.type),
                error=str(exc),
            )
