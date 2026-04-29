"""Unit tests for MemoryFormatter."""

from __future__ import annotations

from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.services.memory_formatter import MemoryFormatter


class TestMemoryFormatter:
    """Tests for MemoryFormatter."""

    def test_format_for_attachment(self):
        """Test formatting a single memory."""
        memory = RelevantMemory(
            path="/memory/user_role.md",
            content="I am a backend developer.",
            mtime_ms=1_000_000,
            header="2 days ago",
        )

        formatted = MemoryFormatter.format_for_attachment(memory)
        assert "# Memory: /memory/user_role.md" in formatted
        assert "_Saved 2 days ago_" in formatted
        assert "I am a backend developer." in formatted

    def test_format_for_attachment_truncated(self):
        """Test formatting with truncation note."""
        memory = RelevantMemory(
            path="/memory/long.md",
            content="Long content...",
            mtime_ms=1_000_000,
            header="1 day ago",
            truncated_at_line=50,
        )

        formatted = MemoryFormatter.format_for_attachment(memory)
        assert "truncated at line 50" in formatted

    def test_format_relevant_memories(self):
        """Test formatting multiple memories."""
        memories = [
            RelevantMemory(
                path="/memory/a.md",
                content="Content A",
                mtime_ms=1_000_000,
                header="1 day ago",
            ),
            RelevantMemory(
                path="/memory/b.md",
                content="Content B",
                mtime_ms=2_000_000,
                header="2 days ago",
            ),
        ]

        formatted = MemoryFormatter.format_relevant_memories(memories)
        assert len(formatted) == 2
        assert "Content A" in formatted[0]
        assert "Content B" in formatted[1]

    def test_format_memory_index(self):
        """Test formatting MEMORY.md index."""
        content = "- [user] **role**: My role\n- [project] **info**: Project info"
        formatted = MemoryFormatter.format_memory_index(content)
        assert "# Memory Index" in formatted
        assert "My role" in formatted

    def test_format_memory_index_none(self):
        """Test formatting None index."""
        assert MemoryFormatter.format_memory_index(None) is None
        assert MemoryFormatter.format_memory_index("") is None
