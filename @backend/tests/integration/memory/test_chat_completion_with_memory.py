"""Testes de integração do ChatCompletionUseCase com sistema de memória.

Valida que recall e extração funcionam corretamente durante o fluxo de chat.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from personagent.application.dto.chat_dto import ChatRequestDTO
from personagent.application.jobs.memory_job_scheduler import MemoryJobScheduler
from personagent.application.use_cases.chat_completion import ChatCompletionUseCase
from personagent.application.use_cases.memory.recall_memory import RecallMemoryUseCase
from personagent.domain.memory.models.memory_file import MemoryFile
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType
from personagent.domain.memory.services.memory_recall_selector import MemoryRecallSelector
from personagent.domain.models.conversation import Conversation
from personagent.infrastructure.persistence.memory.filesystem_memory_repository import (
    FileSystemMemoryRepository,
)


class MockConversationRepo:
    """Mock de ConversationRepository."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    async def create(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation

    async def update(self, conversation: Conversation) -> None:
        self._conversations[str(conversation.id)] = conversation


class MockLLMBackend:
    """Mock LLM que responde com conteúdo fixo."""

    def __init__(self, response: str = "Hello!") -> None:
        self._response = response
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        from personagent.domain.models.inference_result import InferenceResult
        return InferenceResult(content=self._response)

    async def chat_completion_stream(self, **kwargs):
        from personagent.domain.models.inference_result import StreamChunk
        yield StreamChunk(content=self._response, finish_reason="stop")

    async def health_check(self):
        return {"status": "ok"}

    async def get_model_info(self):
        return {}


class TestChatCompletionWithMemory:
    """Testes do ChatCompletionUseCase integrado com memória."""

    @pytest.fixture
    def tmp_root(self, tmp_path: Path):
        return tmp_path

    @pytest.fixture
    def repo(self, tmp_root: Path):
        return FileSystemMemoryRepository(root_dir=tmp_root)

    @pytest.fixture
    def mock_llm(self):
        return MockLLMBackend()

    @pytest.fixture
    def conv_repo(self):
        return MockConversationRepo()

    def _create_use_case(
        self,
        conv_repo,
        mock_llm,
        repo,
        enable_recall: bool = True,
        enable_extraction: bool = True,
    ) -> ChatCompletionUseCase:
        """Factory para criar ChatCompletionUseCase com memória."""
        recall_uc = None
        if enable_recall:
            selector = MemoryRecallSelector(
                llm_backend=mock_llm,
                memory_repository=repo,
                max_recall=5,
            )
            recall_uc = RecallMemoryUseCase(selector)

        scheduler = None
        if enable_extraction:
            scheduler = MemoryJobScheduler()
            scheduler.initialize()

        return ChatCompletionUseCase(
            conversation_repo=conv_repo,
            llm_backend=mock_llm,
            recall_memory_use_case=recall_uc,
            memory_job_scheduler=scheduler,
            memory_repository=repo,
        )

    @pytest.mark.asyncio
    async def test_recall_injects_relevant_memories(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa que memórias relevantes são injetadas no prompt."""
        # Cria memória no repo
        mem_dir = tmp_root / "projects" / "default" / "memory"
        mem_dir.mkdir(parents=True)
        mem = MemoryFile(
            path=mem_dir / "python_pref.md",
            memory_type=MemoryType.USER,
            name="python_pref",
            description="I prefer Python",
            content="I always choose Python for backend projects.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(mem)

        # Mock LLM do selector seleciona a memória
        mock_llm._response = '{"selected_memories": ["python_pref.md"]}'

        use_case = self._create_use_case(conv_repo, mock_llm, repo)
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="What language should I use?",
        )

        relevant = await use_case._recall_relevant_memories(
            request,
            type("Context", (), {
                "system_context": type("SysCtx", (), {"workspace_root": "/tmp/default"})(),
            })(),
            conv,
        )
        assert len(relevant) == 1
        assert "Python" in relevant[0]

        # Verifica que already_surfaced foi atualizado
        assert "_surfaced_memory_paths" in conv.metadata
        assert len(conv.metadata["_surfaced_memory_paths"]) == 1

    @pytest.mark.asyncio
    async def test_recall_deduplicates_already_surfaced(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa que memórias já surfacadas não são retornadas novamente."""
        mem_dir = tmp_root / "projects" / "default" / "memory"
        mem_dir.mkdir(parents=True)
        mem = MemoryFile(
            path=mem_dir / "pref.md",
            memory_type=MemoryType.USER,
            name="pref",
            description="My preference",
            content="I like Python.",
            raw_content="",
            scope=MemoryScope.PRIVATE,
        )
        await repo.write(mem)

        mock_llm._response = '{"selected_memories": ["pref.md"]}'

        use_case = self._create_use_case(conv_repo, mock_llm, repo)
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="What do I like?",
        )

        ctx = type("Context", (), {
            "system_context": type("SysCtx", (), {"workspace_root": "/tmp/default"})(),
        })()

        # Primeiro recall
        relevant1 = await use_case._recall_relevant_memories(request, ctx, conv)
        assert len(relevant1) == 1

        # Segundo recall com mesma query — deve retornar vazio
        relevant2 = await use_case._recall_relevant_memories(request, ctx, conv)
        assert len(relevant2) == 0

    @pytest.mark.asyncio
    async def test_trigger_extraction_debounce(self, repo, mock_llm, conv_repo, tmp_root):
        """Testa debounce de extração (não dispara mais de uma vez por minuto)."""
        use_case = self._create_use_case(conv_repo, mock_llm, repo, enable_recall=False)

        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(
            conversation_id=str(conv.id),
            message="Hello",
        )

        # Primeiro trigger
        await use_case._trigger_memory_extraction(conv, request)
        assert "_last_memory_extraction" in conv.metadata

        # Segundo trigger imediato — deve ser skipado pelo debounce
        await use_case._trigger_memory_extraction(conv, request)
        # O timestamp não deve mudar
        first_time = conv.metadata["_last_memory_extraction"]

        # Simula tempo passado removendo o timestamp
        del conv.metadata["_last_memory_extraction"]
        await use_case._trigger_memory_extraction(conv, request)
        second_time = conv.metadata["_last_memory_extraction"]
        assert second_time != first_time

    @pytest.mark.asyncio
    async def test_recall_disabled_returns_empty(self, repo, mock_llm, conv_repo):
        """Testa que recall retorna vazio quando desabilitado."""
        use_case = self._create_use_case(
            conv_repo, mock_llm, repo, enable_recall=False
        )
        conv = Conversation()
        await conv_repo.create(conv)

        request = ChatRequestDTO(message="Test")
        ctx = type("Context", (), {
            "system_context": type("SysCtx", (), {"workspace_root": "/tmp"})(),
        })()

        relevant = await use_case._recall_relevant_memories(request, ctx, conv)
        assert relevant == []

    @pytest.mark.asyncio
    async def test_sanitize_project_slug(self, repo, mock_llm, conv_repo):
        """Testa sanitização de project_slug."""
        use_case = self._create_use_case(conv_repo, mock_llm, repo)

        # Slug com espaços e caracteres especiais
        slug = use_case._sanitize_project_slug("/path/to/My Project v2.0!")
        assert slug == "my_project_v2_0_"
        assert " " not in slug
        assert "!" not in slug

        # Root vazio
        assert use_case._sanitize_project_slug("") == "default"
        assert use_case._sanitize_project_slug(None) == "default"
