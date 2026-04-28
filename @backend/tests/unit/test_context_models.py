"""Unit tests for context domain models."""

from datetime import datetime
from pathlib import Path

import pytest

from personagent.domain.context.models import (
    ContextBuildResult,
    MemoryFile,
    SystemContext,
    UserContext,
)


class TestMemoryFile:
    """Tests for MemoryFile dataclass."""

    def test_create_memory_file_success(self):
        """Test successful MemoryFile creation."""
        path = Path("/test/file.md")
        content = "Test content"
        priority = 1

        memory_file = MemoryFile.create(path, content, priority)

        assert memory_file.path == path.expanduser().resolve()
        assert memory_file.content == content
        assert memory_file.priority == priority
        assert memory_file.is_injected is False

    def test_create_memory_file_invalid_content_type(self):
        """Test MemoryFile creation with invalid content type."""
        with pytest.raises(TypeError, match="content must be a string"):
            MemoryFile.create(Path("/test/file.md"), 123, 1)

    def test_create_memory_file_invalid_priority(self):
        """Test MemoryFile creation with invalid priority."""
        with pytest.raises(ValueError, match="priority must be an integer between 1 and 4"):
            MemoryFile.create(Path("/test/file.md"), "content", 0)

        with pytest.raises(ValueError, match="priority must be an integer between 1 and 4"):
            MemoryFile.create(Path("/test/file.md"), "content", 5)

    def test_create_memory_file_with_injection(self):
        """Test MemoryFile creation with is_injected flag."""
        memory_file = MemoryFile.create(
            Path("/test/file.md"),
            "content",
            1,
            is_injected=True,
        )
        assert memory_file.is_injected is True


class TestSystemContext:
    """Tests for SystemContext dataclass."""

    def test_create_default_system_context(self):
        """Test SystemContext creation with defaults."""
        context = SystemContext()

        assert context.git_status is None
        assert context.git_branch is None
        assert context.git_remote is None
        assert context.git_commit is None
        assert context.workspace_root == ""
        assert context.cwd == ""
        assert context.environment == {}
        assert context.cache_breaker is None
        assert isinstance(context.timestamp, datetime)

    def test_create_system_context_with_values(self):
        """Test SystemContext creation with values."""
        context = SystemContext(
            git_status={"is_git_repo": True},
            git_branch="main",
            git_remote="origin",
            git_commit="abc123",
            workspace_root="/workspace",
            cwd="/workspace",
            environment={"PATH": "/usr/bin"},
            cache_breaker="test",
        )

        assert context.git_status == {"is_git_repo": True}
        assert context.git_branch == "main"
        assert context.git_remote == "origin"
        assert context.git_commit == "abc123"
        assert context.workspace_root == "/workspace"
        assert context.cwd == "/workspace"
        assert context.environment == {"PATH": "/usr/bin"}
        assert context.cache_breaker == "test"

    def test_with_cache_breaker(self):
        """Test with_cache_breaker method."""
        context = SystemContext(
            git_branch="main",
            workspace_root="/workspace",
        )

        new_context = context.with_cache_breaker("test_breaker")

        assert new_context.cache_breaker == "test_breaker"
        assert new_context.git_branch == "main"
        assert new_context.workspace_root == "/workspace"
        # Original should be unchanged (frozen)
        assert context.cache_breaker is None


class TestUserContext:
    """Tests for UserContext dataclass."""

    def test_create_default_user_context(self):
        """Test UserContext creation with defaults."""
        context = UserContext()

        assert context.persona_md is None
        assert context.memory_files == ()
        assert context.current_date == ""
        assert context.user_settings == {}
        assert context.project_config == {}
        assert isinstance(context.timestamp, datetime)

    def test_create_user_context_with_values(self):
        """Test UserContext creation with values."""
        memory_file = MemoryFile.create(Path("/test/file.md"), "content", 1)

        context = UserContext(
            persona_md="# Instructions",
            memory_files=(memory_file,),
            current_date="2024-01-01",
            user_settings={"theme": "dark"},
            project_config={"name": "test"},
        )

        assert context.persona_md == "# Instructions"
        assert len(context.memory_files) == 1
        assert context.current_date == "2024-01-01"
        assert context.user_settings == {"theme": "dark"}
        assert context.project_config == {"name": "test"}

    def test_has_persona_md_property(self):
        """Test has_persona_md property."""
        context_with_md = UserContext(persona_md="# Instructions")
        assert context_with_md.has_persona_md is True

        context_without_md = UserContext(persona_md=None)
        assert context_without_md.has_persona_md is False

        context_empty_md = UserContext(persona_md="   ")
        assert context_empty_md.has_persona_md is False

    def test_has_memory_files_property(self):
        """Test has_memory_files property."""
        memory_file = MemoryFile.create(Path("/test/file.md"), "content", 1)

        context_with_files = UserContext(memory_files=(memory_file,))
        assert context_with_files.has_memory_files is True

        context_without_files = UserContext(memory_files=())
        assert context_without_files.has_memory_files is False

    def test_with_memory_files(self):
        """Test with_memory_files method."""
        memory_file1 = MemoryFile.create(Path("/test/file1.md"), "content1", 1)
        memory_file2 = MemoryFile.create(Path("/test/file2.md"), "content2", 2)

        context = UserContext(persona_md="# Instructions")
        new_context = context.with_memory_files([memory_file1, memory_file2])

        assert len(new_context.memory_files) == 2
        assert new_context.persona_md == "# Instructions"
        # Original should be unchanged (frozen)
        assert len(context.memory_files) == 0


class TestContextBuildResult:
    """Tests for ContextBuildResult dataclass."""

    def test_create_context_build_result(self):
        """Test ContextBuildResult creation."""
        system_context = SystemContext(git_branch="main")
        user_context = UserContext(persona_md="# Instructions")

        result = ContextBuildResult(
            system_context=system_context,
            user_context=user_context,
            build_duration_ms=100,
            metadata={"source": "built"},
        )

        assert result.system_context == system_context
        assert result.user_context == user_context
        assert result.build_duration_ms == 100
        assert result.metadata == {"source": "built"}

    def test_total_context_size_property(self):
        """Test total_context_size property."""
        memory_file = MemoryFile.create(Path("/test/file.md"), "content", 1)

        system_context = SystemContext(
            git_branch="main",
            workspace_root="/workspace",
        )
        user_context = UserContext(
            persona_md="# Instructions",
            memory_files=(memory_file,),
        )

        result = ContextBuildResult(
            system_context=system_context,
            user_context=user_context,
            build_duration_ms=100,
        )

        size = result.total_context_size
        assert size > 0
        assert isinstance(size, int)
