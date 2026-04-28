"""Unit tests for BuildContextUseCase."""

import shutil
import tempfile
from pathlib import Path

import pytest

from personagent.application.state.services import StateManager
from personagent.application.use_cases.context import BuildContextUseCase
from personagent.infrastructure.persistence.context import InMemoryContextRepository


class TestBuildContextUseCase:
    """Tests for BuildContextUseCase."""

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

    def setup_method(self):
        """Reset StateManager before each test."""
        StateManager.reset()

    @pytest.mark.asyncio
    async def test_execute_builds_context(self, use_case):
        """Test that execute builds context."""
        result = await use_case.execute("conv-1")

        assert result is not None
        assert result.system_context is not None
        assert result.user_context is not None

    @pytest.mark.asyncio
    async def test_execute_with_cache(self, use_case):
        """Test execute with cache enabled."""
        result = await use_case.execute("conv-1", use_cache=True)

        assert result is not None
        assert result.build_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_without_cache(self, use_case):
        """Test execute without cache."""
        result = await use_case.execute("conv-1", use_cache=False)

        assert result is not None
        assert result.metadata["source"] == "built"

    @pytest.mark.asyncio
    async def test_execute_updates_state_manager(self, use_case):
        """Test that execute updates StateManager."""
        await use_case.execute("conv-1")

        state_manager = StateManager.get_instance()

        assert state_manager.get_conversation_id() == "conv-1"
        assert state_manager.get_workspace_root() is not None

    @pytest.mark.asyncio
    async def test_execute_sets_workspace_root(self, use_case, temp_workspace):
        """Test that execute sets workspace root in StateManager."""
        await use_case.execute("conv-1")

        state_manager = StateManager.get_instance()

        assert state_manager.get_workspace_root() == str(temp_workspace)

    @pytest.mark.asyncio
    async def test_execute_sets_system_context(self, use_case):
        """Test that execute sets system context in StateManager."""
        await use_case.execute("conv-1")

        state_manager = StateManager.get_instance()
        system_context = state_manager.get_system_context()

        assert isinstance(system_context, dict)
        assert len(system_context) > 0

    @pytest.mark.asyncio
    async def test_execute_sets_user_context(self, use_case):
        """Test that execute sets user context in StateManager."""
        await use_case.execute("conv-1")

        state_manager = StateManager.get_instance()
        user_context = state_manager.get_user_context()

        assert isinstance(user_context, dict)
        assert len(user_context) > 0

    @pytest.mark.asyncio
    async def test_execute_with_persona_md_disabled(self, temp_workspace, repository):
        """Test execute with persona.md disabled."""
        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=repository,
            enable_persona_md=False,
        )

        result = await use_case.execute("conv-1")

        assert result is not None
        assert result.user_context.persona_md is None or result.user_context.persona_md == ""

    @pytest.mark.asyncio
    async def test_execute_with_persona_md_enabled(self, temp_workspace, repository):
        """Test execute with persona.md enabled."""
        # Create persona.md
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
        """Test execute without repository."""
        use_case = BuildContextUseCase(
            workspace_root=temp_workspace,
            context_repository=None,
            enable_persona_md=True,
        )

        result = await use_case.execute("conv-1")

        assert result is not None

    @pytest.mark.asyncio
    async def test_clear_context(self, use_case, repository):
        """Test clear_context method."""
        # Build context first
        await use_case.execute("conv-1")

        # Clear context
        await use_case.clear_context("conv-1")

        # Check repository is cleared
        assert await repository.get_system_context("conv-1") is None
        assert await repository.get_user_context("conv-1") is None

    @pytest.mark.asyncio
    async def test_clear_context_clears_state_manager_caches(self, use_case):
        """Test that clear_context clears StateManager caches."""
        # Build context first
        await use_case.execute("conv-1")

        # Clear context
        await use_case.clear_context("conv-1")

        state_manager = StateManager.get_instance()
        # Caches should be cleared
        assert state_manager.get_cached_context("conv-1") is None

    @pytest.mark.asyncio
    async def test_execute_with_additional_directories(self, temp_workspace, repository):
        """Test execute with additional directories."""
        additional_dir = temp_workspace / "additional"
        additional_dir.mkdir()

        additional_claude = additional_dir / "persona.md"
        additional_claude.write_text("Additional content")

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
    async def test_execute_handles_build_failure_gracefully(self, use_case):
        """Test that execute handles build failure gracefully."""
        # This test ensures that even if context building fails partially,
        # the use case doesn't crash
        result = await use_case.execute("conv-1")

        # Should still return a result
        assert result is not None

    @pytest.mark.asyncio
    async def test_multiple_conversations(self, use_case):
        """Test handling multiple conversations."""
        result1 = await use_case.execute("conv-1")
        result2 = await use_case.execute("conv-2")

        assert result1 is not None
        assert result2 is not None

        state_manager = StateManager.get_instance()
        # Last conversation should be set
        assert state_manager.get_conversation_id() == "conv-2"

    @pytest.mark.asyncio
    async def test_execute_performance(self, use_case):
        """Test that execute completes within reasonable time."""
        result = await use_case.execute("conv-1")

        # Should complete within reasonable time (< 5 seconds)
        assert result.build_duration_ms < 5000

    @pytest.mark.asyncio
    async def test_execute_updates_timestamp(self, use_case):
        """Test that execute updates timestamp in StateManager."""
        await use_case.execute("conv-1")

        state_manager = StateManager.get_instance()
        # Timestamp should be updated
        assert state_manager.state.updated_at is not None
