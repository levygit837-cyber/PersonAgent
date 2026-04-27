"""Unit tests for MemoryScanner."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.services.memory_scanner import MemoryScanner


class TestMemoryScanner:
    """Tests for MemoryScanner."""

    @pytest.fixture
    def scanner(self):
        """Create a MemoryScanner instance."""
        return MemoryScanner(max_files=200)

    @pytest.fixture
    def temp_memory_dir(self, tmp_path: Path):
        """Create a temporary memory directory with sample files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Valid memory file with frontmatter
        (memory_dir / "user_role.md").write_text(
            '---\nname: user_role\ndescription: My role as a developer\ntype: user\n---\n\n'
            'I am a senior backend developer working with Python and FastAPI.',
            encoding="utf-8",
        )
        time.sleep(0.01)

        # Another valid file
        (memory_dir / "project_deadline.md").write_text(
            '---\nname: project_deadline\ndescription: Q2 release deadline\ntype: project\n---\n\n'
            'The release is scheduled for June 15th.',
            encoding="utf-8",
        )
        time.sleep(0.01)

        # File without frontmatter (should be ignored)
        (memory_dir / "invalid.md").write_text(
            "This file has no frontmatter and should be ignored.",
            encoding="utf-8",
        )

        # File in logs subdirectory (should be ignored)
        logs_dir = memory_dir / "logs" / "2026" / "04"
        logs_dir.mkdir(parents=True)
        (logs_dir / "2026-04-27.md").write_text(
            '---\nname: daily_log\ndescription: Daily conversation log\ntype: reference\n---\n\nLog entry.',
            encoding="utf-8",
        )

        return memory_dir

    @pytest.mark.asyncio
    async def test_scan_directory_returns_valid_headers(self, scanner, temp_memory_dir):
        """Test that scan_directory returns only valid memory headers."""
        headers = scanner.scan_directory(temp_memory_dir)

        assert len(headers) == 2
        filenames = {h.filename for h in headers}
        assert "user_role.md" in filenames
        assert "project_deadline.md" in filenames
        assert "invalid.md" not in filenames
        assert "2026-04-27.md" not in filenames

    @pytest.mark.asyncio
    async def test_scan_directory_orders_by_mtime(self, scanner, temp_memory_dir):
        """Test that headers are ordered by mtime (most recent first)."""
        headers = scanner.scan_directory(temp_memory_dir)

        assert len(headers) == 2
        # project_deadline was written last
        assert headers[0].filename == "project_deadline.md"
        assert headers[1].filename == "user_role.md"

    @pytest.mark.asyncio
    async def test_scan_directory_empty_dir(self, scanner, tmp_path: Path):
        """Test scanning an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        headers = scanner.scan_directory(empty_dir)
        assert headers == []

    @pytest.mark.asyncio
    async def test_scan_directory_nonexistent(self, scanner, tmp_path: Path):
        """Test scanning a non-existent directory."""
        nonexistent = tmp_path / "does_not_exist"

        headers = scanner.scan_directory(nonexistent)
        assert headers == []

    @pytest.mark.asyncio
    async def test_parse_file_valid(self, scanner, temp_memory_dir):
        """Test parsing a valid memory file."""
        file_path = temp_memory_dir / "user_role.md"
        memory = scanner.parse_file(file_path)

        assert memory is not None
        assert memory.name == "user_role"
        assert memory.description == "My role as a developer"
        assert memory.memory_type == MemoryType.USER
        assert "senior backend developer" in memory.content
        assert memory.scope == MemoryScope.PRIVATE
        assert not memory.is_truncated

    @pytest.mark.asyncio
    async def test_parse_file_truncate_lines(self, scanner, tmp_path: Path):
        """Test that parse_file truncates content exceeding max_lines."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        content = "\n".join(f"Line {i}" for i in range(300))
        (memory_dir / "long.md").write_text(
            f'---\nname: long\ndescription: Long file\ntype: project\n---\n\n{content}',
            encoding="utf-8",
        )

        memory = scanner.parse_file(memory_dir / "long.md", max_lines=10)
        assert memory is not None
        assert memory.is_truncated
        assert len(memory.content.split("\n")) == 10

    @pytest.mark.asyncio
    async def test_parse_file_truncate_bytes(self, scanner, tmp_path: Path):
        """Test that parse_file truncates content exceeding max_bytes."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        long_text = "A" * 50_000
        (memory_dir / "big.md").write_text(
            f'---\nname: big\ndescription: Big file\ntype: project\n---\n\n{long_text}',
            encoding="utf-8",
        )

        memory = scanner.parse_file(memory_dir / "big.md", max_bytes=1000)
        assert memory is not None
        assert memory.is_truncated
        assert len(memory.raw_content.encode("utf-8")) <= 1000

    @pytest.mark.asyncio
    async def test_parse_file_no_frontmatter(self, scanner, tmp_path: Path):
        """Test that files without frontmatter return None."""
        no_frontmatter = tmp_path / "no_frontmatter.md"
        no_frontmatter.write_text("Just content without frontmatter.")

        memory = scanner.parse_file(no_frontmatter)
        assert memory is None

    @pytest.mark.asyncio
    async def test_validate_name(self, scanner):
        """Test name validation."""
        assert scanner.validate_name("valid_name") is True
        assert scanner.validate_name("valid_name_123") is True
        assert scanner.validate_name("invalid-name") is False
        assert scanner.validate_name("InvalidName") is False
        assert scanner.validate_name("123_starts_with_number") is False
        assert scanner.validate_name("") is False

    @pytest.mark.asyncio
    async def test_build_manifest(self, scanner, temp_memory_dir):
        """Test building the memory manifest."""
        headers = scanner.scan_directory(temp_memory_dir)
        manifest = scanner.build_manifest(headers)

        assert "user_role.md" in manifest
        assert "project_deadline.md" in manifest
        assert "[user]" in manifest
        assert "[project]" in manifest
        assert "My role as a developer" in manifest
