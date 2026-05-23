"""Unit tests for BuildContextUseCase."""

import shutil
import tempfile
from pathlib import Path

import pytest

from personagent.application.state import RequestContext
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.infrastructure.persistence.context import InMemoryContextRepository


class TestBuildContextUseCase:
    """Tests for BuildContextUseCase.

    These tests intentionally exercise the *returned* value of the use case
    (``ContextBuildResult`` and ``RequestContext``). The previous version
    asserted state on a process-wide singleton, which is exactly the
    pattern we removed in this refactor.
    """

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace for testing."""
        temp_dir = tempfile.mkdtemp()
        workspace = Path(temp_dir)
        yield workspace
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def repository(self):
        """Create a fresh repository for each test."""
        return InMemoryContextRepository()

    @pytest.fixture
    def use_case(self, temp_workspace, repository):
        """Create a BuildContextUseCase instance."""
        return BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
        )

    @pytest.mark.asyncio
    async def test_execute_builds_context(self, use_case):
        """``execute`` returns a populated ``ContextBuildResult``."""
        result = await use_case.execute("conv-1")

        assert result is not None
        assert result.system_context is not None
        assert result.user_context is not None

    @pytest.mark.asyncio
    async def test_execute_with_cache(self, use_case):
        """Cache-enabled call still produces a build_duration metric."""
        result = await use_case.execute("conv-1", use_cache=True)

        assert result is not None
        assert result.build_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_without_cache(self, use_case):
        """Cache-disabled call reports ``source=built``."""
        result = await use_case.execute("conv-1", use_cache=False)

        assert result is not None
        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_build_request_context_returns_immutable_snapshot(
        self, use_case, temp_workspace
    ):
        """``build_request_context`` returns a frozen RequestContext."""
        ctx = await use_case.build_request_context(
            "conv-1", permission_mode="auto"
        )

        assert isinstance(ctx, RequestContext)
        assert ctx.conversation_id == "conv-1"
        assert ctx.workspace_root == str(temp_workspace)
        assert ctx.permission_mode == "auto"
        assert ctx.system_context is not None
        assert ctx.user_context is not None
        assert ctx.request_id  # auto-generated

        # Frozen dataclasses raise on attribute assignment.
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.conversation_id = "tampered"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_build_request_context_propagates_tenant_and_user(
        self, use_case
    ):
        """Multi-tenant fields round-trip through the snapshot."""
        ctx = await use_case.build_request_context(
            "conv-1",
            tenant_id="acme",
            user_id="levy",
            request_id="req-fixed",
        )

        assert ctx.tenant_id == "acme"
        assert ctx.user_id == "levy"
        assert ctx.request_id == "req-fixed"

    @pytest.mark.asyncio
    async def test_request_context_with_overrides_preserves_request_id(
        self, use_case
    ):
        """``with_overrides`` clones the context without losing identity."""
        ctx = await use_case.build_request_context("conv-1")
        refined = ctx.with_overrides(permission_mode="ask")

        assert refined is not ctx
        assert refined.request_id == ctx.request_id
        assert refined.permission_mode == "ask"
        assert refined.conversation_id == ctx.conversation_id

    @pytest.mark.asyncio
    async def test_execute_with_persona_md_disabled(self, temp_workspace, repository):
        """persona.md skipped when the flag is off."""
        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=False,
        )

        result = await use_case.execute("conv-1")

        assert result is not None
        assert (
            result.user_context.persona_md is None
            or result.user_context.persona_md == ""
        )

    @pytest.mark.asyncio
    async def test_execute_with_persona_md_enabled(self, temp_workspace, repository):
        """persona.md picked up from the workspace root."""
        persona_md = temp_workspace / "persona.md"
        persona_md.write_text("# Instructions")

        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
        )

        result = await use_case.execute("conv-1")

        assert result is not None
        assert result.user_context.persona_md is not None
        assert "# Instructions" in result.user_context.persona_md

    @pytest.mark.asyncio
    async def test_execute_without_repository(self, temp_workspace):
        """Use case works without a context cache repository."""
        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=None,
            enable_persona_md=True,
        )

        result = await use_case.execute("conv-1")

        assert result is not None

    @pytest.mark.asyncio
    async def test_clear_context(self, use_case, repository):
        """``clear_context`` removes the cached entry from the repository."""
        await use_case.execute("conv-1")
        await use_case.clear_context("conv-1")

        assert await repository.get_system_context("conv-1") is None
        assert await repository.get_user_context("conv-1") is None

    @pytest.mark.asyncio
    async def test_execute_with_additional_directories(self, temp_workspace, repository):
        """Additional directories contribute memory files."""
        additional_dir = temp_workspace / "additional"
        additional_dir.mkdir()
        (additional_dir / "persona.md").write_text("Additional content")

        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
            additional_directories=[additional_dir],
        )

        result = await use_case.execute("conv-1")

        assert result is not None
        assert len(result.user_context.memory_files) > 0

    @pytest.mark.asyncio
    async def test_multiple_conversations_do_not_leak_into_each_other(
        self, use_case
    ):
        """Two contexts built back-to-back stay independent.

        Under the old singleton implementation, the second call clobbered
        the first one's ``conversation_id`` -- this assertion guards
        against any regression of that behaviour.
        """
        first = await use_case.build_request_context("conv-1")
        second = await use_case.build_request_context("conv-2")

        assert first.conversation_id == "conv-1"
        assert second.conversation_id == "conv-2"
        assert first.request_id != second.request_id

    @pytest.mark.asyncio
    async def test_execute_performance(self, use_case):
        """Sanity check that build_context completes quickly."""
        result = await use_case.execute("conv-1")

        assert result.build_duration_ms < 5000
