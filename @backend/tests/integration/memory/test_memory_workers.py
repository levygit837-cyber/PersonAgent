"""Testes de integração dos workers de memória.

Cobrem ExtractMemoryWorker e ConsolidateMemoryWorker.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from personagent.application.jobs.memory_job import JobType, MemoryJob
from personagent.application.jobs.workers.consolidate_memory_worker import ConsolidateMemoryWorker
from personagent.application.jobs.workers.extract_memory_worker import ExtractMemoryWorker
from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.services.memory_consolidator import MemoryConsolidator
from personagent.domain.memory.services.memory_extractor import MemoryExtractor
from personagent.domain.models.conversation import Conversation, Message, Role
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)


class MockConversationRepo:
    """Mock de ConversationRepository."""

    def __init__(self, conversations: dict[str, Conversation] | None = None) -> None:
        self._conversations = conversations or {}

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    async def create(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation

    async def update(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation


class MockLLMBackend:
    """Mock LLM configurável."""

    def __init__(self, response: str = "") -> None:
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


class TestExtractMemoryWorker:
    """Testes do ExtractMemoryWorker."""

    @pytest.fixture
    def tmp_memory_dir(self, tmp_path: Path):
        return tmp_path / "memory"

    @pytest.fixture
    def repo(self, tmp_path: Path):
        return FileSystemMemoryRepository(root_dir=tmp_path)

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    @pytest.mark.asyncio
    async def test_extract_worker_creates_memories(self, repo, tmp_memory_dir, mock_llm):
        """Testa que worker extrai e persiste memórias."""
        conv = Conversation()
        conv.add_message(Message(role=Role.USER, content="I prefer Python."))
        conv.add_message(Message(role=Role.ASSISTANT, content="Great!"))

        mock_llm._response = "user | python_pref | Language preference | I prefer Python for backend."
        conv_repo = MockConversationRepo({str(conv.id): conv})

        extractor = MemoryExtractor(llm_backend=mock_llm, memory_repository=repo)
        worker = ExtractMemoryWorker(
            conversation_repo=conv_repo,
            memory_repository=repo,
            memory_extractor=extractor,
        )

        job = MemoryJob(
            id="test-1",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id=str(conv.id),
            project_slug="test-project",
        )
        result = await worker(job)
        assert result["extracted"] == 1
        assert "python_pref.md" in result["files"][0]

    @pytest.mark.asyncio
    async def test_extract_worker_skips_when_agent_wrote(self, repo, tmp_memory_dir, mock_llm):
        """Testa que worker skipa quando agente já escreveu memória."""
        conv = Conversation()
        conv.add_message(Message(role=Role.USER, content="Something"))
        conv.add_message(
            Message(
                role=Role.ASSISTANT,
                content="Done",
                tool_calls=[{
                    "function": {
                        "name": "write_file",
                        "arguments": '{"path": "memory/test.md"}',
                    },
                }],
            )
        )

        conv_repo = MockConversationRepo({str(conv.id): conv})
        extractor = MemoryExtractor(llm_backend=mock_llm, memory_repository=repo)
        worker = ExtractMemoryWorker(
            conversation_repo=conv_repo,
            memory_repository=repo,
            memory_extractor=extractor,
        )

        job = MemoryJob(
            id="test-2",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id=str(conv.id),
            project_slug="test-project",
        )
        result = await worker(job)
        assert result.get("skipped") == "agent_already_wrote"

    @pytest.mark.asyncio
    async def test_extract_worker_no_conversation_id(self, repo, tmp_memory_dir, mock_llm):
        """Testa que worker retorna erro sem conversation_id."""
        extractor = MemoryExtractor(llm_backend=mock_llm, memory_repository=repo)
        worker = ExtractMemoryWorker(
            conversation_repo=MockConversationRepo(),
            memory_repository=repo,
            memory_extractor=extractor,
        )

        job = MemoryJob(
            id="test-3",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id=None,
            project_slug="test-project",
        )
        result = await worker(job)
        assert result["extracted"] == 0
        assert "error" in result

    @pytest.mark.asyncio
    async def test_extract_worker_conversation_not_found(self, repo, tmp_memory_dir, mock_llm):
        """Testa que worker retorna erro quando conversa não existe."""
        extractor = MemoryExtractor(llm_backend=mock_llm, memory_repository=repo)
        worker = ExtractMemoryWorker(
            conversation_repo=MockConversationRepo(),
            memory_repository=repo,
            memory_extractor=extractor,
        )

        job = MemoryJob(
            id="test-4",
            type=JobType.EXTRACT_MEMORIES,
            conversation_id="nonexistent",
            project_slug="test-project",
        )
        result = await worker(job)
        assert result["extracted"] == 0
        assert "not found" in result.get("error", "").lower()


class TestConsolidateMemoryWorker:
    """Testes do ConsolidateMemoryWorker."""

    @pytest.fixture
    def repo(self, tmp_path: Path):
        return FileSystemMemoryRepository(root_dir=tmp_path)

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    @pytest.mark.asyncio
    async def test_consolidate_worker_executes_actions(self, repo, mock_llm):
        """Testa que worker executa ações de consolidação."""
        # Cria memórias para consolidar
        tmp_path = repo.root_dir / "projects" / "test-project" / "memory"
        tmp_path.mkdir(parents=True)

        for name in ["old_a", "old_b"]:
            mem = MemoryFile(
                path=tmp_path / f"{name}.md",
                memory_type=MemoryType.PROJECT,
                name=name,
                description=name,
                content=f"Content {name}",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            await repo.write(mem)
            time.sleep(0.01)

        # Mock LLM retorna ação de merge
        mock_llm._response = "UPDATE | merged.md | Merged content from old_a and old_b"

        consolidator = MemoryConsolidator(llm_backend=mock_llm, memory_repository=repo)
        worker = ConsolidateMemoryWorker(
            memory_repository=repo,
            memory_consolidator=consolidator,
        )

        job = MemoryJob(
            id="test-5",
            type=JobType.AUTO_DREAM,
            conversation_id=None,
            project_slug="test-project",
        )
        result = await worker(job)
        assert result["actions"] == 1
        assert result["executed"] == 1

    @pytest.mark.asyncio
    async def test_consolidate_worker_rejects_invalid_paths(self, repo, mock_llm):
        """Testa que worker rejeita paths inválidos nas ações."""
        tmp_path = repo.root_dir / "projects" / "test-project" / "memory"
        tmp_path.mkdir(parents=True)

        for name in ["valid_a", "valid_b"]:
            mem = MemoryFile(
                path=tmp_path / f"{name}.md",
                memory_type=MemoryType.PROJECT,
                name=name,
                description=name,
                content=f"Content {name}",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            await repo.write(mem)
            time.sleep(0.01)

        # Mock LLM tenta path traversal
        mock_llm._response = "CREATE | ../../../etc/passwd | Evil content"

        consolidator = MemoryConsolidator(llm_backend=mock_llm, memory_repository=repo)
        worker = ConsolidateMemoryWorker(
            memory_repository=repo,
            memory_consolidator=consolidator,
        )

        job = MemoryJob(
            id="test-6",
            type=JobType.AUTO_DREAM,
            conversation_id=None,
            project_slug="test-project",
        )
        result = await worker(job)
        # A ação deve falhar, então executed = 0
        assert result["actions"] == 1
        assert result["executed"] == 0

    @pytest.mark.asyncio
    async def test_consolidate_worker_lock_prevents_concurrent(self, repo, mock_llm):
        """Testa que lock impede execução concorrente."""
        import fcntl
        import os

        tmp_path = repo.root_dir / "projects" / "test-project" / "memory"
        tmp_path.mkdir(parents=True)

        for name in ["lock_a", "lock_b"]:
            mem = MemoryFile(
                path=tmp_path / f"{name}.md",
                memory_type=MemoryType.PROJECT,
                name=name,
                description=name,
                content=f"Content {name}",
                raw_content="",
                scope=MemoryScope.PRIVATE,
            )
            await repo.write(mem)
            time.sleep(0.01)

        mock_llm._response = "NONE"
        consolidator = MemoryConsolidator(llm_backend=mock_llm, memory_repository=repo)
        worker = ConsolidateMemoryWorker(
            memory_repository=repo,
            memory_consolidator=consolidator,
        )

        job = MemoryJob(
            id="test-7",
            type=JobType.AUTO_DREAM,
            conversation_id=None,
            project_slug="test-project",
        )

        # Primeira execução deve adquirir lock e completar
        result1 = await worker(job)
        assert result1.get("skipped") is not True

        # Simula lock ocupado criando e adquirindo o lock file manualmente
        lock_path = tmp_path / ".consolidation.lock"
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        try:
            # Segunda execução deve ser skipada porque lock está ocupado
            result2 = await worker(job)
            assert result2.get("skipped") is True
            assert result2.get("reason") == "lock_busy"
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
