"""Workflow scheduler using APScheduler for cron-based triggers."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from personagent.application.workflows.runner import WorkflowRunner
    from personagent.application.workflows.store import WorkflowStore

logger = structlog.get_logger(__name__)


class WorkflowScheduler:
    """Manages scheduled workflow executions using APScheduler."""

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._runner: WorkflowRunner | None = None
        self._store: WorkflowStore | None = None

    def initialize(
        self,
        runner: WorkflowRunner,
        store: WorkflowStore,
    ) -> None:
        """Initialize the scheduler with dependencies."""
        self._runner = runner
        self._store = store
        self._scheduler = AsyncIOScheduler()
        logger.info("workflow_scheduler_initialized")

    async def load_scheduled_workflows(self) -> None:
        """Load all workflows with cron triggers and schedule them."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")

        # Get all workflows
        workflows = await self._store.list(limit=1000, offset=0)

        for workflow in workflows:
            graph = workflow.graph or {}
            nodes = graph.get("nodes", [])

            # Find trigger node
            for node in nodes:
                if node.get("type") == "trigger":
                    config = node.get("config", {})
                    trigger_mode = config.get("trigger_mode", "manual")

                    if trigger_mode == "cron":
                        cron_expr = config.get("cron_expression", "")
                        timezone = config.get("timezone", "America/Sao_Paulo")

                        if cron_expr:
                            job_id = f"workflow_{workflow.id}"
                            self._scheduler.add_job(
                                self._execute_scheduled_workflow,
                                trigger=CronTrigger.from_crontab(cron_expr, timezone=timezone),
                                id=job_id,
                                args=[str(workflow.id)],
                                replace_existing=True,
                            )
                            logger.info(
                                "scheduled_workflow_loaded",
                                workflow_id=str(workflow.id),
                                cron=cron_expr,
                                timezone=timezone,
                            )
                    break

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")
        self._scheduler.start()
        logger.info("workflow_scheduler_started")

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown()
            logger.info("workflow_scheduler_shutdown")

    async def _execute_scheduled_workflow(self, workflow_id: str) -> None:
        """Execute a scheduled workflow run."""
        if self._runner is None or self._store is None:
            raise RuntimeError("Scheduler not initialized")

        from personagent.application.workflows import parse_workflow_document

        try:
            workflow = await self._store.get(uuid.UUID(workflow_id))
            if workflow is None:
                logger.warning("scheduled_workflow_not_found", workflow_id=workflow_id)
                return

            document = parse_workflow_document(workflow.graph or {})

            # Collect all events
            trace_events = []
            final_output = None
            error_message = None
            status = "completed"

            async for event in self._runner.execute(
                workflow_id=workflow_id,
                title=workflow.title,
                document=document,
                run_input="",  # Cron runs use default payload
            ):
                trace_events.append(event)
                if event.get("event") == "workflow_run_completed":
                    final_output = event.get("output")
                elif event.get("event") == "node_error":
                    status = "failed"
                    error_message = event.get("error")

            # Persist the run
            await self._persist_run(
                workflow_id=workflow_id,
                trigger_mode="cron",
                status=status,
                input={},
                output=final_output,
                trace_events=trace_events,
                error_message=error_message,
            )

            logger.info(
                "scheduled_workflow_completed",
                workflow_id=workflow_id,
                status=status,
            )

        except Exception as exc:
            logger.exception("scheduled_workflow_failed", workflow_id=workflow_id)
            await self._persist_run(
                workflow_id=workflow_id,
                trigger_mode="cron",
                status="failed",
                input={},
                output=None,
                trace_events=[],
                error_message=str(exc),
            )

    async def _persist_run(
        self,
        workflow_id: str,
        trigger_mode: str,
        status: str,
        input: dict | None,
        output: dict | None,
        trace_events: list[dict],
        error_message: str | None = None,
    ) -> None:
        """Persist a workflow run to the database."""
        # This requires a session - we need to get one from the store
        # For now, we'll log the attempt
        logger.info(
            "persist_run_attempt",
            workflow_id=workflow_id,
            trigger_mode=trigger_mode,
            status=status,
        )

    async def schedule_workflow(self, workflow_id: str, cron_expr: str, timezone: str) -> None:
        """Schedule or reschedule a workflow."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")

        job_id = f"workflow_{workflow_id}"
        self._scheduler.add_job(
            self._execute_scheduled_workflow,
            trigger=CronTrigger.from_crontab(cron_expr, timezone=timezone),
            id=job_id,
            args=[workflow_id],
            replace_existing=True,
        )
        logger.info(
            "workflow_scheduled",
            workflow_id=workflow_id,
            cron=cron_expr,
            timezone=timezone,
        )

    async def unschedule_workflow(self, workflow_id: str) -> None:
        """Remove a workflow from the scheduler."""
        if self._scheduler is None:
            raise RuntimeError("Scheduler not initialized")

        job_id = f"workflow_{workflow_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("workflow_unscheduled", workflow_id=workflow_id)
        except Exception:
            # Job might not exist
            pass


# Global scheduler instance
_scheduler_instance: WorkflowScheduler | None = None


def get_scheduler() -> WorkflowScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = WorkflowScheduler()
    return _scheduler_instance
