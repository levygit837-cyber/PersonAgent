"""Unit tests for InMemoryContextRepository."""


import pytest

from personagent.domain.context.models import SystemContext, UserContext
from personagent.infrastructure.persistence.context import InMemoryContextRepository


class TestInMemoryContextRepository:
    """Tests for InMemoryContextRepository."""

    @pytest.fixture
    def repository(self):
        """Create a fresh repository for each test."""
        return InMemoryContextRepository()

    @pytest.fixture
    def system_context(self):
        """Create a sample SystemContext."""
        return SystemContext(
            git_branch="main",
            git_commit="abc123",
            workspace_root="/workspace",
        )

    @pytest.fixture
    def user_context(self):
        """Create a sample UserContext."""
        return UserContext(
            claude_md="# Instructions",
            current_date="2024-01-01",
        )

    @pytest.mark.asyncio
    async def test_save_and_get_system_context(self, repository, system_context):
        """Test saving and retrieving system context."""
        await repository.save_system_context("conv-1", system_context)

        retrieved = await repository.get_system_context("conv-1")

        assert retrieved is not None
        assert retrieved.git_branch == "main"
        assert retrieved.git_commit == "abc123"

    @pytest.mark.asyncio
    async def test_get_system_context_not_found(self, repository):
        """Test getting non-existent system context."""
        retrieved = await repository.get_system_context("nonexistent")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_save_and_get_user_context(self, repository, user_context):
        """Test saving and retrieving user context."""
        await repository.save_user_context("conv-1", user_context)

        retrieved = await repository.get_user_context("conv-1")

        assert retrieved is not None
        assert retrieved.claude_md == "# Instructions"
        assert retrieved.current_date == "2024-01-01"

    @pytest.mark.asyncio
    async def test_get_user_context_not_found(self, repository):
        """Test getting non-existent user context."""
        retrieved = await repository.get_user_context("nonexistent")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_clear_context(self, repository, system_context, user_context):
        """Test clearing context for a conversation."""
        await repository.save_system_context("conv-1", system_context)
        await repository.save_user_context("conv-1", user_context)

        await repository.clear_context("conv-1")

        assert await repository.get_system_context("conv-1") is None
        assert await repository.get_user_context("conv-1") is None

    @pytest.mark.asyncio
    async def test_clear_context_nonexistent(self, repository):
        """Test clearing non-existent context (should not raise error)."""
        await repository.clear_context("nonexistent")

        # Should not raise any error

    @pytest.mark.asyncio
    async def test_save_and_get_metadata(self, repository):
        """Test saving and retrieving metadata."""
        await repository.set_metadata("key1", "value1")

        retrieved = await repository.get_metadata("key1")

        assert retrieved == "value1"

    @pytest.mark.asyncio
    async def test_get_metadata_not_found(self, repository):
        """Test getting non-existent metadata."""
        retrieved = await repository.get_metadata("nonexistent")

        assert retrieved is None

    @pytest.mark.asyncio
    async def test_multiple_conversations(self, repository, system_context):
        """Test handling multiple conversations."""
        await repository.save_system_context("conv-1", system_context)
        await repository.save_system_context("conv-2", system_context)

        retrieved1 = await repository.get_system_context("conv-1")
        retrieved2 = await repository.get_system_context("conv-2")

        assert retrieved1 is not None
        assert retrieved2 is not None
        assert retrieved1.git_branch == "main"
        assert retrieved2.git_branch == "main"

    @pytest.mark.asyncio
    async def test_overwrite_system_context(self, repository, system_context):
        """Test overwriting existing system context."""
        await repository.save_system_context("conv-1", system_context)

        # Update context
        updated_context = SystemContext(git_branch="develop")
        await repository.save_system_context("conv-1", updated_context)

        retrieved = await repository.get_system_context("conv-1")

        assert retrieved.git_branch == "develop"

    @pytest.mark.asyncio
    async def test_overwrite_user_context(self, repository, user_context):
        """Test overwriting existing user context."""
        await repository.save_user_context("conv-1", user_context)

        # Update context
        updated_context = UserContext(claude_md="# New Instructions")
        await repository.save_user_context("conv-1", updated_context)

        retrieved = await repository.get_user_context("conv-1")

        assert retrieved.claude_md == "# New Instructions"

    @pytest.mark.asyncio
    async def test_clear_one_conversation_does_not_affect_others(
        self, repository, system_context
    ):
        """Test clearing one conversation doesn't affect others."""
        await repository.save_system_context("conv-1", system_context)
        await repository.save_system_context("conv-2", system_context)

        await repository.clear_context("conv-1")

        assert await repository.get_system_context("conv-1") is None
        assert await repository.get_system_context("conv-2") is not None

    def test_clear_all(self, repository, system_context, user_context):
        """Test clear_all method."""
        # Use sync method for clear_all
        repository._system_context_cache["conv-1"] = system_context
        repository._user_context_cache["conv-1"] = user_context
        repository._metadata_cache["key1"] = "value1"

        repository.clear_all()

        assert len(repository._system_context_cache) == 0
        assert len(repository._user_context_cache) == 0
        assert len(repository._metadata_cache) == 0

    @pytest.mark.asyncio
    async def test_metadata_persistence_across_context_operations(
        self, repository, system_context
    ):
        """Test that metadata persists even when contexts are cleared."""
        await repository.set_metadata("key1", "value1")
        await repository.save_system_context("conv-1", system_context)
        await repository.clear_context("conv-1")

        # Metadata should still be available
        assert await repository.get_metadata("key1") == "value1"

    @pytest.mark.asyncio
    async def test_complex_metadata_values(self, repository):
        """Test storing complex values in metadata."""
        complex_value = {"nested": {"data": [1, 2, 3]}}
        await repository.set_metadata("complex", complex_value)

        retrieved = await repository.get_metadata("complex")

        assert retrieved == complex_value

    @pytest.mark.asyncio
    async def test_none_metadata_value(self, repository):
        """Test storing None as metadata value."""
        await repository.set_metadata("null_key", None)

        retrieved = await repository.get_metadata("null_key")

        assert retrieved is None
