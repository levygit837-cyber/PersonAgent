"""Unit tests for MemoryJobScheduler."""

from __future__ import annotations

import pytest

from personagent.application.jobs.memory_job import JobStatus, JobType, MemoryJob
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler


class TestMemoryJobScheduler:
    """Tests for MemoryJobScheduler."""

    @pytest.fixture
    def scheduler(self):
        """Create a MemoryJobScheduler instance."""
        return MemoryJobScheduler()

    def test_initialize(self, scheduler):
        """Test initialization."""
        scheduler.initialize()
        assert scheduler._scheduler is not None

    def test_register_handler(self, scheduler):
        """Test handler registration."""
        scheduler.initialize()
        handler = lambda job: {"result": "ok"}
        scheduler.register_handler(JobType.EXTRACT_MEMORIES, handler)
        assert JobType.EXTRACT_MEMORIES in scheduler._handlers

    @pytest.mark.asyncio
    async def test_start_shutdown(self, scheduler):
        """Test start and shutdown."""
        scheduler.initialize()
        scheduler.start()
        assert scheduler._scheduler is not None
        scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_submit_job(self, scheduler):
        """Test submitting a job."""
        scheduler.initialize()
        scheduler.start()

        calls = []
        async def handler(job):
            calls.append(job)
            return {"result": "ok"}

        scheduler.register_handler(JobType.EXTRACT_MEMORIES, handler)

        job = MemoryJob(
            id="test-1",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id="conv-1",
            project_slug="test-project",
        )

        job_id = await scheduler.submit_job(job)
        assert job_id == "test-1"
        # Wait a bit for async execution
        import asyncio
        await asyncio.sleep(0.1)

        assert len(calls) == 1
        assert calls[0].id == "test-1"
        scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_schedule_cron(self, scheduler):
        """Test scheduling a cron job."""
        scheduler.initialize()
        scheduler.start()

        job_id = scheduler.schedule_cron(
            JobType.AUTO_DREAM,
            cron_expr="0 0 * * *",
        )
        assert job_id.startswith("cron_auto_dream_")
        scheduler.shutdown()
