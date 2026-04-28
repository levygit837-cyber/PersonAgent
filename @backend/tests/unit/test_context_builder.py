"""Unit tests for ContextBuilder."""

import shutil
import tempfile
from pathlib import Path

import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.domain.context.services.context_builder import ContextBuilder
from personagent.infrastructure.persistence.context import InMemoryContextRepository


class TestContextBuilder:
    """Tests for ContextBuilder."""

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
    def builder(self, temp_workspace, repository):
        """Create a ContextBuilder instance."""
        return ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
        )

    @pytest.mark.asyncio
    async def test_build_context_without_cache(self, builder):
        """Test building context without using cache."""
        result = await builder.build_context("conv-1", use_cache=False)

        assert isinstance(result.system_context, SystemContext)
        assert isinstance(result.user_context, UserContext)
        assert result.build_duration_ms >= 0
        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_build_context_with_cache(self, builder):
        """Test building context with cache."""
        # First build
        await builder.build_context("conv-1", use_cache=True)

        # Second build should use cache
        result2 = await builder.build_context("conv-1", use_cache=True)

        assert result2.metadata["source"] == "cache"

    @pytest.mark.asyncio
    async def test_build_context_cache_miss(self, builder):
        """Test cache miss for new conversation."""
        result = await builder.build_context("new-conv", use_cache=True)

        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_build_context_without_repository(self, temp_workspace):
        """Test building context without repository."""
        builder = ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=None,
            enable_persona_md=True,
        )

        result = await builder.build_context("conv-1", use_cache=False)

        assert result is not None
        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_build_context_with_persona_md_disabled(self, temp_workspace, repository):
        """Test building context with persona.md disabled."""
        # Create persona.md file
        persona_md = temp_workspace / "persona.md"
        persona_md.write_text("# Instructions")

        builder = ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=False,
        )

        result = await builder.build_context("conv-1", use_cache=False)

        assert result.user_context.persona_md is None or result.user_context.persona_md == ""

    @pytest.mark.asyncio
    async def test_build_context_with_persona_md_enabled(self, temp_workspace, repository):
        """Test building context with persona.md enabled."""
        # Create persona.md file
        persona_md = temp_workspace / "persona.md"
        persona_md.write_text("# Instructions")

        builder = ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
        )

        result = await builder.build_context("conv-1", use_cache=False)

        assert result.user_context.persona_md is not None
        assert "# Instructions" in result.user_context.persona_md

    @pytest.mark.asyncio
    async def test_build_context_includes_git_info(self, builder):
        """Test that git info is included in system context."""
        result = await builder.build_context("conv-1", use_cache=False)

        # Git info should be collected
        assert result.system_context.git_status is not None

    @pytest.mark.asyncio
    async def test_build_context_includes_environment(self, builder):
        """Test that environment variables are included."""
        result = await builder.build_context("conv-1", use_cache=False)

        # Environment should be collected
        assert isinstance(result.system_context.environment, dict)

    @pytest.mark.asyncio
    async def test_build_context_includes_workspace_root(self, builder, temp_workspace):
        """Test that workspace root is included."""
        result = await builder.build_context("conv-1", use_cache=False)

        assert result.system_context.workspace_root == str(temp_workspace)
        assert result.system_context.cwd == str(temp_workspace)

    @pytest.mark.asyncio
    async def test_build_context_includes_current_date(self, builder):
        """Test that current date is included."""
        result = await builder.build_context("conv-1", use_cache=False)

        assert result.user_context.current_date is not None
        assert len(result.user_context.current_date) == 10  # YYYY-MM-DD format

    @pytest.mark.asyncio
    async def test_build_context_with_additional_directories(self, temp_workspace, repository):
        """Test building context with additional directories."""
        # Create additional directory
        additional_dir = temp_workspace / "additional"
        additional_dir.mkdir()

        additional_claude = additional_dir / "persona.md"
        additional_claude.write_text("Additional content")

        builder = ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=True,
            additional_directories=[additional_dir],
        )

        result = await builder.build_context("conv-1", use_cache=False)

        # Should include content from additional directory
        assert len(result.user_context.memory_files) > 0

    @pytest.mark.asyncio
    async def test_clear_context(self, builder, repository):
        """Test clearing context."""
        # Build context first
        await builder.build_context("conv-1", use_cache=False)

        # Clear context
        await builder.clear_context("conv-1")

        # Context should be cleared from repository
        assert await repository.get_system_context("conv-1") is None
        assert await repository.get_user_context("conv-1") is None

    @pytest.mark.asyncio
    async def test_clear_context_without_repository(self, temp_workspace):
        """Test clearing context without repository."""
        builder = ContextBuilder(
            workspace_root=temp_workspace,
            context_repository=None,
            enable_persona_md=True,
        )

        # Should not raise error
        await builder.clear_context("conv-1")

    @pytest.mark.asyncio
    async def test_build_context_caches_result(self, builder, repository):
        """Test that build context caches the result."""
        await builder.build_context("conv-1", use_cache=False)

        # Check that it's cached
        cached_system = await repository.get_system_context("conv-1")
        cached_user = await repository.get_user_context("conv-1")

        assert cached_system is not None
        assert cached_user is not None

    @pytest.mark.asyncio
    async def test_build_context_total_context_size(self, builder):
        """Test that total_context_size is calculated."""
        result = await builder.build_context("conv-1", use_cache=False)

        size = result.total_context_size
        assert size >= 0
        assert isinstance(size, int)

    @pytest.mark.asyncio
    async def test_build_context_metadata(self, builder):
        """Test that metadata is included."""
        result = await builder.build_context("conv-1", use_cache=False)

        assert "source" in result.metadata
        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_build_context_performance(self, builder):
        """Test that build duration is reasonable."""
        result = await builder.build_context("conv-1", use_cache=False)

        # Should complete within reasonable time (< 5 seconds)
        assert result.build_duration_ms < 5000
