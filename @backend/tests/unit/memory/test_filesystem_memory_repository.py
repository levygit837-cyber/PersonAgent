"""Unit tests for FileSystemMemoryRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.services.memory_scanner import MemoryScanner
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)


class TestFileSystemMemoryRepository:
    """Tests for FileSystemMemoryRepository."""

    @pytest.fixture
    def repo(self, tmp_path: Path):
        """Create a FileSystemMemoryRepository with a temp root."""
        return FileSystemMemoryRepository(root_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_scan_empty_dir(self, repo, tmp_path: Path):
        """Test scanning an empty memory directory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        headers = await repo.scan(memory_dir)
        assert headers == []

    @pytest.mark.asyncio
    async def test_scan_with_files(self, repo, tmp_path: Path):
        """Test scanning a directory with valid memory files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        (memory_dir / "feedback_tests.md").write_text(
            '---\nname: feedback_tests\ndescription: How to write tests\ntype: feedback\n---\n\n'
            "Always use pytest with fixtures.",
            encoding="utf-8",
        )

        headers = await repo.scan(memory_dir)
        assert len(headers) == 1
        assert headers[0].filename == "feedback_tests.md"
        assert headers[0].memory_type == MemoryType.FEEDBACK

    @pytest.mark.asyncio
    async def test_read_valid_file(self, repo, tmp_path: Path):
        """Test reading a valid memory file."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        file_path = memory_dir / "user_role.md"
        file_path.write_text(
            '---\nname: user_role\ndescription: Developer role\ntype: user\n---\n\n'
            "I work with Python.",
            encoding="utf-8",
        )

        memory = await repo.read(file_path)
        assert memory is not None
        assert memory.name == "user_role"
        assert memory.memory_type == MemoryType.USER
        assert "Python" in memory.content

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, repo, tmp_path: Path):
        """Test reading a non-existent file."""
        memory = await repo.read(tmp_path / "does_not_exist.md")
        assert memory is None

    @pytest.mark.asyncio
    async def test_write_memory_file(self, repo, tmp_path: Path):
        """Test writing a memory file."""
        memory_dir = tmp_path / "memory"
        memory_file = MemoryFile(
            path=memory_dir / "new_memory.md",
            memory_type=MemoryType.PROJECT,
            name="new_memory",
            description="A new memory",
            content="This is the content.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )

        written_path = await repo.write(memory_file)
        assert written_path.exists()

        content = written_path.read_text(encoding="utf-8")
        assert "---" in content
        assert 'name: "new_memory"' in content
        assert 'type: "project"' in content
        assert "This is the content." in content

    @pytest.mark.asyncio
    async def test_delete_existing(self, repo, tmp_path: Path):
        """Test deleting an existing memory file."""
        file_path = tmp_path / "to_delete.md"
        file_path.write_text("delete me")

        result = await repo.delete(file_path)
        assert result is True
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo, tmp_path: Path):
        """Test deleting a non-existent file."""
        result = await repo.delete(tmp_path / "does_not_exist.md")
        assert result is False

    @pytest.mark.asyncio
    async def test_read_index(self, repo, tmp_path: Path):
        """Test reading MEMORY.md index."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        index_path = memory_dir / "MEMORY.md"
        index_path.write_text("# Memory Index\n\n- [user] **role**: My role\n")

        index = await repo.read_index(memory_dir)
        assert index is not None
        assert index.entrypoint_path == index_path
        assert "Memory Index" in index.content
        assert index.line_count == 4  # # Memory Index, blank, - [user], trailing newline

    @pytest.mark.asyncio
    async def test_read_index_missing(self, repo, tmp_path: Path):
        """Test reading a missing MEMORY.md."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        index = await repo.read_index(memory_dir)
        assert index is None

    @pytest.mark.asyncio
    async def test_update_index(self, repo, tmp_path: Path):
        """Test updating the MEMORY.md index."""
        memory_dir = tmp_path / "memory"
        entries = [
            {"name": "role", "description": "My role", "type": "user"},
            {"name": "project_info", "description": "Project details", "type": "project"},
        ]

        index_path = await repo.update_index(memory_dir, entries)
        assert index_path.exists()

        content = index_path.read_text(encoding="utf-8")
        assert "# Memory Index" in content
        assert "[user] **role**" in content
        assert "[project] **project_info**" in content

    @pytest.mark.asyncio
    async def test_get_memory_dir_private(self, repo):
        """Test getting private memory directory."""
        path = await repo.get_memory_dir("my-project", scope=MemoryScope.PRIVATE)
        assert path.name == "memory"
        assert "my-project" in str(path)

    @pytest.mark.asyncio
    async def test_get_memory_dir_team(self, repo):
        """Test getting team memory directory."""
        path = await repo.get_memory_dir("my-project", scope=MemoryScope.TEAM)
        assert path.name == "team"

    @pytest.mark.asyncio
    async def test_get_memory_dir_user_scope(self, repo):
        """Test getting user-scope memory directory."""
        path = await repo.get_memory_dir("my-project", scope=MemoryScope.USER_SCOPE, agent_type="personagent")
        assert "agent-memory" in str(path)
        assert "personagent" in str(path)

    @pytest.mark.asyncio
    async def test_list_by_type(self, repo, tmp_path: Path):
        """Test listing memories filtered by type."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        (memory_dir / "user_role.md").write_text(
            '---\nname: user_role\ndescription: Role\ntype: user\n---\n\nContent',
            encoding="utf-8",
        )
        (memory_dir / "project_info.md").write_text(
            '---\nname: project_info\ndescription: Info\ntype: project\n---\n\nContent',
            encoding="utf-8",
        )

        user_headers = await repo.list_by_type(memory_dir, MemoryType.USER)
        assert len(user_headers) == 1
        assert user_headers[0].filename == "user_role.md"

    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, repo, tmp_path: Path):
        """Test that path traversal is rejected."""
        # Path with .. that resolves outside root
        malicious = tmp_path / ".." / "etc" / "passwd"

        with pytest.raises(ValueError):
            await repo.read(malicious)

        # Direct path traversal string
        with pytest.raises(ValueError, match="Path traversal"):
            await repo.read(tmp_path / "foo/../bar" / ".." / "secret.md")

    @pytest.mark.asyncio
    async def test_containment_validation(self, repo, tmp_path: Path):
        """Test that paths outside root_dir are rejected."""
        outside = Path("/tmp/outside.txt")

        with pytest.raises(ValueError, match="outside memory root"):
            await repo.read(outside)
