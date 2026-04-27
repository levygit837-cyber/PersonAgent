"""Unit tests for MemoryRecallSelector."""

from __future__ import annotations

from pathlib import Path

import pytest

from personagent.domain.memory.models.memory_types import MemoryType
from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector


class MockLLMBackend:
    """Mock LLM backend que retorna uma seleção fixa."""

    def __init__(self, response: str = '{"selected_memories": ["user_role.md"]}') -> None:
        self._response = response

    async def chat_completion(self, **kwargs):
        class MockResult:
            content = self._response
        return MockResult()

    async def chat_completion_stream(self, **kwargs):
        yield {}

    async def health_check(self):
        return {"status": "ok"}

    async def get_model_info(self):
        return {}


class MockMemoryRepository:
    """Mock memory repository."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self._files = files or {}

    async def scan(self, memory_dir: Path, max_files: int = 200):
        from personagent.domain.memory.models.memory_file import MemoryHeader
        from personagent.domain.memory.models.memory_types import MemoryType
        headers = []
        for name, desc in self._files.items():
            path = memory_dir / name
            headers.append(MemoryHeader(
                filename=name,
                file_path=path,
                mtime_ms=1_000_000,
                description=desc,
                memory_type=MemoryType.USER,
                name=name.replace(".md", ""),
            ))
        return headers

    async def read(self, file_path: Path, max_lines: int = 200, max_bytes: int = 25_000):
        from personagent.domain.memory.models.memory_file import MemoryFile
        from personagent.domain.memory.models.memory_types import MemoryType
        return MemoryFile(
            path=file_path,
            memory_type=MemoryType.USER,
            name=file_path.stem,
            description=self._files.get(file_path.name, ""),
            content=f"Content of {file_path.name}",
            raw_content="",
            scope=MemoryType.USER,
        )

    async def write(self, memory_file):
        return memory_file.path

    async def delete(self, file_path: Path):
        return True

    async def read_index(self, memory_dir: Path):
        return None

    async def update_index(self, memory_dir: Path, entries, max_lines: int = 200, max_bytes: int = 25_000):
        return memory_dir / "MEMORY.md"

    async def get_memory_dir(self, project_slug: str, scope=None, agent_type=None):
        return Path("/tmp/mock_memory")

    async def list_by_type(self, memory_dir: Path, memory_type, max_files: int = 200):
        return await self.scan(memory_dir, max_files)


class TestMemoryRecallSelector:
    """Tests for MemoryRecallSelector."""

    @pytest.fixture
    def mock_repo(self):
        return MockMemoryRepository({
            "user_role.md": "User role description",
            "project_info.md": "Project info description",
        })

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    @pytest.fixture
    def selector(self, mock_llm, mock_repo):
        return MemoryRecallSelector(
            llm_backend=mock_llm,
            memory_repository=mock_repo,
            max_recall=5,
        )

    @pytest.mark.asyncio
    async def test_select_relevant_returns_memories(self, selector, tmp_path: Path):
        """Test that select_relevant returns selected memories."""
        memories = await selector.select_relevant(
            query="What is my role?",
            memory_dir=tmp_path,
        )

        assert len(memories) == 1
        assert isinstance(memories[0], RelevantMemory)
        assert "user_role" in memories[0].path

    @pytest.mark.asyncio
    async def test_select_relevant_empty_dir(self, selector, tmp_path: Path):
        """Test that empty directory returns empty list."""
        empty_repo = MockMemoryRepository({})
        selector_empty = MemoryRecallSelector(
            llm_backend=MockLLMBackend(),
            memory_repository=empty_repo,
        )

        memories = await selector_empty.select_relevant(
            query="test",
            memory_dir=tmp_path,
        )
        assert memories == []

    @pytest.mark.asyncio
    async def test_select_relevant_no_selection(self, selector, tmp_path: Path):
        """Test when LLM returns no selections."""
        llm_no_select = MockLLMBackend('{"selected_memories": []}')
        selector_no_select = MemoryRecallSelector(
            llm_backend=llm_no_select,
            memory_repository=selector._memory_repository,
        )

        memories = await selector_no_select.select_relevant(
            query="random query",
            memory_dir=tmp_path,
        )
        assert memories == []

    @pytest.mark.asyncio
    async def test_select_relevant_already_surfaced(self, selector, tmp_path: Path):
        """Test that already surfaced memories are skipped."""
        # The mock repo resolves paths relative to memory_dir, so use tmp_path
        memories = await selector.select_relevant(
            query="What is my role?",
            memory_dir=tmp_path,
            already_surfaced={str(tmp_path / "user_role.md")},
        )
        # Since user_role is the only file and it's already surfaced, should return empty
        assert len(memories) == 0

    @pytest.mark.asyncio
    async def test_parse_selection_json(self, selector):
        """Test JSON parsing of LLM response."""
        result = selector._parse_selection('{"selected_memories": ["a.md", "b.md"]}')
        assert result == ["a.md", "b.md"]

    @pytest.mark.asyncio
    async def test_parse_selection_fallback(self, selector):
        """Test fallback parsing for non-JSON responses."""
        result = selector._parse_selection("- file1.md\n- file2.md")
        assert "file1.md" in result
        assert "file2.md" in result
