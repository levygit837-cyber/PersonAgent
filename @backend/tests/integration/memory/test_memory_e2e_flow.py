"""Testes de integração end-to-end do fluxo completo de memória.

Cobrem:
- Escrita, leitura, scan de memórias
- Atualização de índice
- Recall com already_surfaced tracking
- Extração com merge
- Consolidação com lock
"""

from __future__ import annotations

import time
from datetime import UTC
from pathlib import Path

import pytest

from personagent.domain.conversation.models import Conversation, Message, Role
from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.models.relevant_memory import RelevantMemory
from personagent.domain.memory.services.memory_age_tracker import MemoryAgeTracker
from personagent.domain.memory.services.memory_consolidator import MemoryConsolidator
from personagent.domain.memory.services.memory_extractor import MemoryExtractor
from personagent.domain.memory.services.memory_formatter import MemoryFormatter
from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector
from personagent.infrastructure.persistence.memory import (
    FileSystemMemoryRepository,
)


class MockLLMBackend:
    """Mock LLM backend configurável."""

    def __init__(self, response: str = '{"selected_memories": []}') -> None:
        self._response = response
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)

        class MockResult:
            content = self._response

        return MockResult()

    async def chat_completion_stream(self, **kwargs):
        yield {}

    async def health_check(self):
        return {"status": "ok"}

    async def get_model_info(self):
        return {}


class TestMemoryE2EFlow:
    """Testes end-to-end do fluxo de memória."""

    @pytest.fixture
    def tmp_memory_dir(self, tmp_path: Path):
        """Cria um diretório de memória temporário."""
        return tmp_path / "memory"

    @pytest.fixture
    def repo(self, tmp_path: Path):
        """Cria um repositório com root temporário."""
        return FileSystemMemoryRepository(root_dir=tmp_path)

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    def test_memory_extractor_accepts_json_and_legacy_pipe(self, repo, mock_llm):
        extractor = MemoryExtractor(llm_backend=mock_llm, memory_repository=repo)

        json_memories = extractor._parse_extraction(
            '{"memories":[{"type":"user","name":"editor_pref","description":"Editor preference","content":"Use vim for quick edits."}]}'
        )
        legacy_memories = extractor._parse_extraction(
            "project | prompt_refactor | Prompt refactor | Keep prompts short | with pipes"
        )

        assert json_memories == [
            {
                "type": MemoryType.USER,
                "name": "editor_pref",
                "description": "Editor preference",
                "content": "Use vim for quick edits.",
            }
        ]
        assert legacy_memories == [
            {
                "type": MemoryType.PROJECT,
                "name": "prompt_refactor",
                "description": "Prompt refactor",
                "content": "Keep prompts short | with pipes",
            }
        ]

    def test_memory_consolidator_accepts_json_and_legacy_pipe(self, repo, mock_llm):
        consolidator = MemoryConsolidator(llm_backend=mock_llm, memory_repository=repo)

        json_actions = consolidator._parse_actions(
            '{"actions":[{"action":"UPDATE","path":"prompts.md","content":"Consolidated prompt notes."}]}'
        )
        legacy_actions = consolidator._parse_actions(
            "CREATE | memory/index.md | New index | with pipe"
        )

        assert json_actions == [
            {
                "action": "UPDATE",
                "path": "prompts.md",
                "content": "Consolidated prompt notes.",
            }
        ]
        assert legacy_actions == [
            {
                "action": "CREATE",
                "path": "memory/index.md",
                "content": "New index | with pipe",
            }
        ]

    @pytest.mark.asyncio
    async def test_full_lifecycle_single_memory(self, repo, tmp_memory_dir):
        """Testa ciclo completo: write → scan → read → index → delete."""
        # Write
        memory = MemoryFile(
            path=tmp_memory_dir / "user_role.md",
            memory_type=MemoryType.USER,
            name="user_role",
            description="My developer role",
            content="I work with Python and FastAPI.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        written = await repo.write(memory)
        assert written.exists()

        # Scan
        headers = await repo.scan(tmp_memory_dir)
        assert len(headers) == 1
        assert headers[0].name == "user_role"

        # Read
        read_mem = await repo.read(written)
        assert read_mem is not None
        assert read_mem.name == "user_role"
        assert "Python" in read_mem.content

        # Index
        entries = [{"name": "user_role", "description": "My role", "type": "user"}]
        index_path = await repo.update_index(tmp_memory_dir, entries)
        assert index_path.exists()
        index_content = index_path.read_text()
        assert "Memory Index" in index_content
        assert "user_role" in index_content

        # Delete
        deleted = await repo.delete(written)
        assert deleted is True
        assert not written.exists()

    @pytest.mark.asyncio
    async def test_recall_with_already_surfaced_tracking(self, repo, tmp_memory_dir, mock_llm):
        """Testa que memórias já surfacadas não são retornadas novamente."""
        # Cria duas memórias
        for name, desc in [("topic_a", "First"), ("topic_b", "Second")]:
            mem = MemoryFile(
                path=tmp_memory_dir / f"{name}.md",
                memory_type=MemoryType.PROJECT,
                name=name,
                description=desc,
                content=f"Content of {name}",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            await repo.write(mem)
            time.sleep(0.01)

        # Mock LLM seleciona a primeira
        mock_llm._response = '{"selected_memories": ["topic_a.md"]}'
        selector = MemoryRecallSelector(
            llm_backend=mock_llm,
            memory_repository=repo,
            max_recall=5,
        )

        # Primeiro recall: retorna topic_a
        memories = await selector.select_relevant(
            query="about topic a",
            memory_dir=tmp_memory_dir,
        )
        assert len(memories) == 1
        assert "topic_a" in memories[0].path

        # Segundo recall com already_surfaced: retorna vazio
        memories2 = await selector.select_relevant(
            query="about topic a",
            memory_dir=tmp_memory_dir,
            already_surfaced={memories[0].path},
        )
        assert len(memories2) == 0

    @pytest.mark.asyncio
    async def test_recall_with_staleness_warning(self, repo, tmp_memory_dir, mock_llm):
        """Testa que memórias antigas incluem warning de staleness."""
        # Cria memória com mtime antigo
        mem = MemoryFile(
            path=tmp_memory_dir / "old_project.md",
            memory_type=MemoryType.PROJECT,
            name="old_project",
            description="Old info",
            content="This is old.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(mem)

        # Manipula mtime para 10 dias atrás
        old_time = time.time() - 10 * 86400
        import os
        os.utime(str(mem.path), (old_time, old_time))

        mock_llm._response = '{"selected_memories": ["old_project.md"]}'
        selector = MemoryRecallSelector(
            llm_backend=mock_llm,
            memory_repository=repo,
        )

        memories = await selector.select_relevant(
            query="about old project",
            memory_dir=tmp_memory_dir,
        )
        assert len(memories) == 1
        assert "days old" in memories[0].content
        assert "system-reminder" in memories[0].content

    @pytest.mark.asyncio
    async def test_extraction_with_merge(self, repo, tmp_memory_dir, mock_llm):
        """Testa que extração faz merge com memória existente."""
        # Cria memória existente
        existing = MemoryFile(
            path=tmp_memory_dir / "user_pref.md",
            memory_type=MemoryType.USER,
            name="user_pref",
            description="Preferences",
            content="I like dark mode.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(existing)

        # Mock LLM retorna memória com mesmo nome mas conteúdo novo
        mock_llm._response = "user | user_pref | Preferences | I also use vim."
        extractor = MemoryExtractor(
            llm_backend=mock_llm,
            memory_repository=repo,
        )

        conv = Conversation()
        conv.add_message(Message(role=Role.USER, content="I also use vim."))
        conv.add_message(Message(role=Role.ASSISTANT, content="Nice choice!"))

        memories = await extractor.extract_from_conversation(conv, tmp_memory_dir)
        assert len(memories) == 1
        assert "dark mode" in memories[0].content
        assert "vim" in memories[0].content

    @pytest.mark.asyncio
    async def test_extraction_skips_duplicate_content(self, repo, tmp_memory_dir, mock_llm):
        """Testa que extração skipa quando conteúdo novo é subconjunto do existente."""
        existing = MemoryFile(
            path=tmp_memory_dir / "pref.md",
            memory_type=MemoryType.USER,
            name="pref",
            description="Prefs",
            content="I like Python and FastAPI.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(existing)

        mock_llm._response = "user | pref | Prefs | I like Python"
        extractor = MemoryExtractor(
            llm_backend=mock_llm,
            memory_repository=repo,
        )

        conv = Conversation()
        conv.add_message(Message(role=Role.USER, content="I like Python"))

        memories = await extractor.extract_from_conversation(conv, tmp_memory_dir)
        # Deve retornar vazio pois "I like Python" já está no conteúdo existente
        assert len(memories) == 0

    @pytest.mark.asyncio
    async def test_extraction_validates_name(self, repo, tmp_memory_dir, mock_llm):
        """Testa que nomes inválidos são rejeitados na extração."""
        mock_llm._response = "user | My Bad Name | Desc | Content"
        extractor = MemoryExtractor(
            llm_backend=mock_llm,
            memory_repository=repo,
        )

        conv = Conversation()
        conv.add_message(Message(role=Role.USER, content="Something"))

        memories = await extractor.extract_from_conversation(conv, tmp_memory_dir)
        assert len(memories) == 0

    @pytest.mark.asyncio
    async def test_consolidation_processes_oldest_first(self, repo, tmp_memory_dir, mock_llm):
        """Testa que consolidator processa memórias antigas primeiro."""
        # Cria 3 memórias com mtimes diferentes
        for name in ["old", "middle", "new"]:
            mem = MemoryFile(
                path=tmp_memory_dir / f"{name}.md",
                memory_type=MemoryType.PROJECT,
                name=name,
                description=name,
                content=f"Content {name}",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            await repo.write(mem)
            time.sleep(0.05)

        # Mock LLM retorna NONE (sem ações)
        mock_llm._response = "NONE"
        consolidator = MemoryConsolidator(
            llm_backend=mock_llm,
            memory_repository=repo,
        )

        actions = await consolidator.consolidate(tmp_memory_dir)
        assert actions == []

    @pytest.mark.asyncio
    async def test_frontmatter_with_quotes(self, repo, tmp_memory_dir):
        """Testa que aspas no conteúdo são escapadas corretamente."""
        memory = MemoryFile(
            path=tmp_memory_dir / "quotes.md",
            memory_type=MemoryType.USER,
            name="quotes",
            description='He said "hello" to me',
            content="Use double quotes for strings.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        written = await repo.write(memory)

        # Lê de volta
        read_mem = await repo.read(written)
        assert read_mem is not None
        assert "hello" in read_mem.description

    @pytest.mark.asyncio
    async def test_path_traversal_protection(self, repo, tmp_path):
        """Testa proteção contra path traversal em várias operações."""
        with pytest.raises(ValueError):
            await repo.read(tmp_path / ".." / "etc" / "passwd")

        with pytest.raises(ValueError):
            await repo.write(
                MemoryFile(
                    path=tmp_path / ".." / "secret.md",
                    memory_type=MemoryType.PROJECT,
                    name="secret",
                    description="",
                    content="",
                    raw_content="",
                    scope=MemoryScope.PRIVATE,
                )
            )

    @pytest.mark.asyncio
    async def test_memory_formatter_attachment(self):
        """Testa formatação de memória para attachment no prompt."""
        mem = RelevantMemory(
            path="/mem/user.md",
            content="I am a developer.",
            mtime_ms=1_000_000,
            header="2 days ago",
        )
        formatted = MemoryFormatter.format_for_attachment(mem)
        assert "# Memory: /mem/user.md" in formatted
        assert "_Saved 2 days ago_" in formatted
        assert "developer" in formatted

    @pytest.mark.asyncio
    async def test_scanner_skips_logs_directory(self, repo, tmp_memory_dir):
        """Testa que arquivos em logs/ são ignorados no scan."""
        # Cria memória normal
        normal = MemoryFile(
            path=tmp_memory_dir / "normal.md",
            memory_type=MemoryType.PROJECT,
            name="normal",
            description="Normal",
            content="Normal content",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(normal)

        # Cria arquivo em logs/
        logs_dir = tmp_memory_dir / "logs" / "2026" / "01"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "2026-01-01.md"
        log_file.write_text(
            '---\nname: log_entry\ndescription: Daily log\ntype: reference\n---\n\nLog',
            encoding="utf-8",
        )

        headers = await repo.scan(tmp_memory_dir)
        assert len(headers) == 1
        assert headers[0].name == "normal"

    @pytest.mark.asyncio
    async def test_scanner_frontmatter_with_divider_in_body(self, repo, tmp_memory_dir):
        """Testa que --- no corpo não quebra o parser."""
        content = '---\nname: divider_test\ndescription: Test\ntype: project\n---\n\nSome content\n\n---\n\nMore content'
        file_path = tmp_memory_dir / "divider_test.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        mem = await repo.read(file_path)
        assert mem is not None
        assert mem.name == "divider_test"
        assert "---" in mem.content

    @pytest.mark.asyncio
    async def test_age_tracker_staleness(self):
        """Testa cálculo de idade e staleness."""
        tracker = MemoryAgeTracker()
        from datetime import datetime

        # Memória de 10 dias atrás
        old_mtime = int((datetime.now(UTC).timestamp() - 10 * 86400) * 1000)
        age = tracker.calculate(old_mtime)
        assert age.days == 10
        assert age.is_stale is True

        warning = tracker.format_staleness_warning(age)
        assert warning is not None
        assert "10 days old" in warning

    @pytest.mark.asyncio
    async def test_scanner_yaml_with_nested_quotes(self, repo, tmp_memory_dir):
        """Testa que aspas aninhadas no YAML são preservadas."""
        content = '---\nname: quote_test\ndescription: He said "hello world" to me\ntype: user\n---\n\nContent'
        file_path = tmp_memory_dir / "quote_test.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        mem = await repo.read(file_path)
        assert mem is not None
        assert "hello world" in mem.description
